# Databento Signal-Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. In skipp-algo, land each phase via the **skipp-pr-flow** skill (sibling worktree + ledger-drift-guard + PR). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Den zeitkritischen Echtzeit-Signalpfad von FMP-Quote-Polling (15-min-verzögert, bandbreiten-gedeckelt) auf einen eingebetteten Databento-Live-Feed (echtzeit, flat-rate) umstellen, ohne die erprobte A0/A1/A2-Signal-Logik oder die Snapshot-Schnittstelle zu ändern.

**Architektur (Strategie A — Datenquellen-Swap, minimal-invasiv):** `realtime_signals.py` bleibt vollständig erhalten (A0/A1/A2-Leiter, trade_context, Slack-Notify, Snapshot-Write). Ersetzt wird NUR die Datenquelle in `RealtimeEngine._fetch()`: die drei FMP-Client-Aufrufe (`get_stable_batch_quotes` / `get_stable_batch_aftermarket_quotes` / `get_stable_batch_aftermarket_trades`) werden hinter einer Quelle-Abstraktion durch einen Databento-gespeisten Adapter ersetzt, der aus einem prozess-internen Live-Bar-Cache (`db.Live`, ohlcv-1s) + einer täglichen Referenzdatei (prev_close + ADV) FMP-kompatible Quote-Rows baut. Der Rest der Kette — Snapshot `latest_realtime_signals.json` (schema v2) → `live_overlay_daemon._get_signal_fields` → `/smc_live` → Sidecar — bleibt byte-identisch.

**Tech-Stack:** Python 3.12, `databento` (db.Live), bestehende Bausteine aus `services/a0_fast_detector/` (`live_runtime.py`, `a0_stream*`, `history.py`, Referenz-Bootstrap) und `services/live_overlay_daemon/feed.py` (gehärteter Reconnect/Supervisor/Ingest-Thread als Referenzimplementierung). Railway (`smc-signals-producer`).

## Global Constraints

- **Snapshot-Schema unverändert:** `latest_realtime_signals.json` behält `{"signals":[RealtimeSignal.to_dict()…], "signal_count","a0_count","a1_count","a2_count","updated_epoch","signal_schema_version":2}`. Kein Consumer (`live_overlay_daemon/compute.py::_get_signal_fields`, Zeile ~1413) darf angefasst werden müssen.
- **Fail-closed Frische:** `updated_epoch` muss bei jedem Poll gesetzt werden; ein toter Feed darf keinen frischen Snapshot vortäuschen (siehe `_signals_snapshot_is_fresh`, compute.py).
- **Datenquellen-Feature-Flag:** Umschaltung ausschließlich über eine env-Var (`RT_QUOTE_SOURCE=fmp|databento`, default `fmp`), damit Rollback ein reiner Redeploy ist. Kein Code-Pfad wird gelöscht, bis das Cutover-Gate erfüllt ist.
- **`decide_core_level` bleibt Single-Source-of-Truth:** derselbe Core wie heute (`open_prep/a0_contract.py`), den FMP-Producer und a0_fast_detector bereits teilen. Keine parallele Signal-Mathematik.
- **Ledger-/Guard-Pflicht:** produktive `.py`-Änderungen laufen durch `pre-push-guard` (ruff + line-pinned ledger tests). Neue `subprocess`/`open`/`global`-Sites im selben Commit im Ledger reconcilen.
- **Nicht-Ziel (bleibt zwingend FMP):** News/Sentiment (`newsstack_fmp`), Fundamentals/Earnings/Insider/13F/Analyst (`open_prep/macro.py` Ultimate-Pfade), Macro/Economic-Calendar/Treasury/Sector, und `^VIX` (nicht auf EQUS.MINI). Diese Migration fasst NUR den Preis/Quote-Strom an.

---

## Was migriert wird (zeitkritisch) vs. was bleibt

| FMP-Nutzung | Zeitkritisch? | Databento-ersetzbar? | Aktion in diesem Plan |
|---|---|---|---|
| `batch-quote` (realtime_signals, 900 Sym, 20/5/2 s) | **Ja — der Kern** | Ja (ohlcv-1s) | **Phase 1–3: schwenken** |
| `batch-aftermarket-quote/-trade` (extended shadow) | Ja (pre/post-market) | Teilw. (EQUS.MINI deckt 04:00–20:00 ET) | Phase 4: nachziehen |
| `historical-chart/1min` (Kalibrierung, wöchentl.) | Nein | Ja | Optional später, kein Zeitdruck |
| `eod-bulk` / `historical-price-eod` (open_prep batch) | Nein | Ja (EQUS.SUMMARY) | Nicht in diesem Plan |
| `^VIX` quote (overlay, 30 min) | Nein | **Nein** (nicht auf EQUS.MINI) | **Bleibt FMP** |
| News / Fundamentals / Macro | tlw. | **Nein** | **Bleibt FMP** |

---

## File Structure

- **Neu** `open_prep/quote_source.py` — Quelle-Abstraktion: `QuoteSource` Protocol + `FMPQuoteSource` (Wrapper um heutige 3 Client-Calls) + `DatabentoQuoteSource` (Bar-Cache → FMP-kompatible Rows). Eine Verantwortung: Symbolliste → Liste FMP-schema-kompatibler Quote-Rows.
- **Neu** `open_prep/databento_quote_feed.py` — prozess-interner `db.Live`-Consumer (ohlcv-1s, explizite Symbolliste), Thread-sicherer Per-Symbol-Bar-Cache mit Reconnect/Replay. Portiert die gehärteten Muster aus `services/live_overlay_daemon/feed.py` + `services/a0_fast_detector/live_runtime.py`.
- **Neu** `open_prep/quote_reference.py` — lädt/served die tägliche Referenz (prev_close + ADV pro Symbol), wiederverwendet den Bootstrap aus `services/a0_fast_detector/history.py` / bootstrap. Liefert genau die zwei Felder, die FMP-batch-quote NICHT hat.
- **Modify** `open_prep/realtime_signals.py:2646` (`_fetch`) — die 3 direkten `self.client.get_stable_*`-Aufrufe hinter `self._quote_source.fetch(symbols, session)` kapseln; Konstruktion der Quelle aus `RT_QUOTE_SOURCE`.
- **Modify** `services/a0_fast_detector/` bzw. Referenz-Bootstrap — Referenzdatei auf das **liquide Produktions-Universum** ausweiten (heute nur ~58 Micro-Caps).
- **Test** `tests/test_quote_source_parity.py`, `tests/test_databento_quote_feed.py`, `tests/test_quote_reference.py`.

---

## Phase 0 — Architektur fixieren & Referenzdaten für das echte Universum

**Zweck:** Zwei Vorbedingungen härten, bevor Code entsteht: (a) die Row-Kompatibilität exakt spezifizieren, (b) die prev_close/ADV-Referenz für die ~900 liquiden Produktionssymbole erzeugen (heute existiert sie nur für die Micro-Cap-Shadow-Liste).

### Task 0.1 — Row-Kontrakt der FMP-Quelle einfrieren

**Files:**
- Analyse: `open_prep/realtime_signals.py:2646-2760` (`_fetch`), `:2725-2730`, `:3279-3351`
- Create: `docs/databento_quote_row_contract.md`

**Interfaces:**
- Produces: die exakte Feldliste, die `_fetch()` + downstream aus einer Quote-Row liest: `symbol`, `price`, `previousClose`, `volume`, `timestamp` (Pflicht); `avgVolume` (heute FMP-fehlend → Fallback `watchlist_avg_volumes`); ggf. `dayHigh/dayLow/open`. Diese Liste ist der Kontrakt für `QuoteSource`.

- [ ] **Step 1:** Alle `row.get("…")` / `.get("price|previousClose|volume|avgVolume|timestamp")`-Zugriffe im Fetch-/Detektionspfad auflisten (grep bereits durchgeführt: Zeilen 1782,1785,2292,2398,2625,2672,2684,2725-2730,3279,3339-3351). Jede in `docs/databento_quote_row_contract.md` mit Typ + Bedeutung + Null-Verhalten dokumentieren.
- [ ] **Step 2:** Pro Feld notieren, wie es aus einem Databento `ohlcv-1s`-Bar + Referenz ableitbar ist (`price`=last close, `volume`=kumuliertes Regular-Vol, `previousClose`+`avgVolume`=Referenz, `timestamp`=ts_event). Lücken markieren (z. B. `dayHigh/dayLow` = laufendes Session-Max/Min aus dem Bar-Cache).
- [ ] **Step 3:** Commit (`docs:`).

**Verifikation:** Dokument listet jedes vom Producer gelesene Quote-Feld mit Databento-Herleitung; keine offene Lücke.

### Task 0.2 — Referenz (prev_close + ADV) für das liquide Universum erzeugen

**Files:**
- Analyse: `services/a0_fast_detector/history.py`, `services/a0_fast_detector/bootstrap/`, `A0_FAST_REFERENCE_FILE` (`/app/bootstrap/a0-reference.json`)
- Modify/Create: Bootstrap-Skript, das die Referenz für die open_prep-Kandidatenliste (nicht die Micro-Cap-Shadow-Symbole) baut

**Interfaces:**
- Consumes: die tägliche open_prep-Kandidaten-Symbolliste (dieselbe, die der Producer via `DEFAULT_TOP_N=0` = ALL überwacht).
- Produces: `reference[symbol] = {previous_close, average_daily_volume, corporate_action_version, as_of_session}` — dasselbe Schema wie die bestehende `a0-reference.json`.

- [ ] **Step 1: Failing test.** `tests/test_quote_reference.py::test_reference_covers_producer_universe` — gegeben eine Kandidatenliste, erwartet dass die Referenz für jedes Symbol `previous_close>0` und `average_daily_volume>0` liefert.
- [ ] **Step 2:** Test laufen → FAIL (Referenz deckt heute nur Micro-Caps).
- [ ] **Step 3:** Bootstrap so parametrisieren, dass er die Symbolquelle aus der open_prep-Kandidatenliste zieht (via `EQUS.SUMMARY`/historical daily, wie a0_fast es für die 58 Symbole tut). Corporate-action-adjustiert (`databento-adjusted-ohlcv-1d-v1`).
- [ ] **Step 4:** Test laufen → PASS.
- [ ] **Step 5:** Referenz für 1 realen Handelstag erzeugen, stichprobenartig gegen FMP `previousClose` für 10 liquide Namen (AAPL/NVDA/SPY…) prüfen (< 0.5 % Abweichung erwartet, ex-Dividende ausgenommen).
- [ ] **Step 6:** Commit (`feat:`), via skipp-pr-flow.

**Verifikation:** Referenz-JSON deckt das volle Produktions-Universum; prev_close matcht FMP für liquide Namen; ADV vorhanden (schließt das FMP-`avgVolume`-Loch).

---

## Phase 1 — Databento-Quote-Quelle (der Kern)

### Task 1.1 — `QuoteSource`-Abstraktion + FMP-Wrapper (Verhalten unverändert)

**Files:**
- Create: `open_prep/quote_source.py`
- Modify: `open_prep/realtime_signals.py:2646` (`_fetch`)
- Test: `tests/test_quote_source_parity.py`

**Interfaces:**
- Produces: `class QuoteSource(Protocol): def fetch(self, symbols: list[str], session: str) -> list[dict]` (Rows im Kontrakt aus Task 0.1). `class FMPQuoteSource` kapselt die heutigen 3 Client-Aufrufe **unverändert**.

- [ ] **Step 1: Failing test.** `test_fmp_quote_source_matches_legacy_fetch` — mit gemocktem FMPClient liefert `FMPQuoteSource.fetch(...)` exakt dieselben Rows wie der heutige `_fetch`-Codepfad.
- [ ] **Step 2:** Test → FAIL (Klasse existiert nicht).
- [ ] **Step 3:** `FMPQuoteSource` implementieren = 1:1 Extraktion der 3 `self.client.get_stable_*`-Aufrufe + postmarket-Adaption (`build_postmarket_quotes`) aus `_fetch`.
- [ ] **Step 4:** `_fetch` so umbauen, dass es `self._quote_source.fetch(...)` aufruft; `RealtimeEngine.__init__` konstruiert `FMPQuoteSource` wenn `RT_QUOTE_SOURCE != "databento"`.
- [ ] **Step 5:** Test → PASS; zusätzlich die bestehende realtime_signals-Testsuite grün (`pytest tests/ -k realtime_signals -n 4`).
- [ ] **Step 6:** Commit (`refactor:` — reine Kapselung, kein Verhaltenswechsel), via skipp-pr-flow.

**Verifikation:** Producer verhält sich bit-identisch; nur die Quelle ist jetzt austauschbar. **Dies ist ein reiner Refactor-PR — landet unabhängig.**

### Task 1.2 — Databento-Live-Bar-Cache

**Files:**
- Create: `open_prep/databento_quote_feed.py`
- Test: `tests/test_databento_quote_feed.py`
- Referenz-Impl: `services/live_overlay_daemon/feed.py`, `services/a0_fast_detector/live_runtime.py`, `open_prep/a0_stream*.py`

**Interfaces:**
- Produces: `class DatabentoQuoteFeed` mit `start()`, `stop()`, `latest_bar(symbol) -> BarState | None`, `cumulative_volume(symbol) -> int`, `session_high_low(symbol)`. Thread-sicherer Per-Symbol-Cache, gefüllt von einem `db.Live(EQUS.MINI, ohlcv-1s, symbols=…, stype_in=raw_symbol)`-Consumer mit Intraday-Replay ab Session-Open und Reconnect/Supervisor.

- [ ] **Step 1: Failing test.** `test_feed_ingests_ohlcv_and_serves_latest` — einen aufgezeichneten `ohlcv-1s`-Record-Stream (Fixture) einspeisen, erwarten dass `latest_bar` den letzten Close und `cumulative_volume` die Summe liefert.
- [ ] **Step 2:** Test → FAIL.
- [ ] **Step 3:** Consumer/Ingest/Reconnect aus `feed.py` portieren (nur Cache-Füllung, keine Compute-Threads). `END_OF_INTERVAL`-SystemMsg als „Sekunde vollständig"-Barriere nutzen. Reconnect + Intraday-Replay (`REPLAY_COMPLETED`) für Gap-Recovery.
- [ ] **Step 4:** Test → PASS.
- [ ] **Step 5:** `data_age`-Telemetrie mitführen (analog `open_prep/a0_contract.py::data_age_ms`), Gauge exportieren.
- [ ] **Step 6:** Commit (`feat:`), via skipp-pr-flow.

**Verifikation:** Feed füllt aus aufgezeichnetem Stream einen korrekten Bar-Cache; Reconnect/Replay durch Test abgedeckt; `data_age_ms` instrumentiert.

### Task 1.3 — `DatabentoQuoteSource` (Bar-Cache + Referenz → FMP-Row)

**Files:**
- Modify: `open_prep/quote_source.py` (Klasse ergänzen)
- Create: `open_prep/quote_reference.py`
- Test: `tests/test_quote_source_parity.py` (erweitern)

**Interfaces:**
- Consumes: `DatabentoQuoteFeed` (Task 1.2), `QuoteReference` (prev_close/ADV, Task 0.2).
- Produces: `class DatabentoQuoteSource(QuoteSource)` — `fetch()` liest pro Symbol aus dem Cache und baut eine Row im Kontrakt aus Task 0.1: `price`=latest close, `volume`=cumulative regular vol, `previousClose`+`avgVolume`=Referenz, `timestamp`=ts_event, `dayHigh/dayLow`=Session-High/Low aus Cache.

- [ ] **Step 1: Failing test.** `test_databento_source_row_matches_contract` — Cache + Referenz gegeben, erwartet vollständige, kontrakt-konforme Rows inkl. `avgVolume` (nicht null, anders als FMP).
- [ ] **Step 2:** Test → FAIL.
- [ ] **Step 3:** `DatabentoQuoteSource.fetch()` implementieren; fehlende Symbole (nicht im Cache) fail-closed als „kein Quote" (nicht als stale FMP-Row).
- [ ] **Step 4:** Test → PASS.
- [ ] **Step 5: Parität-Test.** `test_databento_vs_fmp_same_core_decision` — denselben `decide_core_level` über eine FMP-Row und die abgeleitete Databento-Row laufen lassen; bei gleichem prev_close/price/volume identische Core-Entscheidung erwarten.
- [ ] **Step 6:** Commit (`feat:`), via skipp-pr-flow.

**Verifikation:** Databento-Rows erfüllen den Kontrakt und erzeugen bei gleichem Input dieselbe Core-Entscheidung wie FMP; `avgVolume` ist jetzt vorhanden.

---

## Phase 2 — Integration & Shadow-Parallellauf

### Task 2.1 — Producer verdrahtet beide Quellen hinter dem Flag

**Files:**
- Modify: `open_prep/realtime_signals.py` (`RealtimeEngine.__init__`, Feed-Lifecycle), `services/signals_producer/` (Startup)

**Interfaces:**
- Consumes: `RT_QUOTE_SOURCE` (`fmp` default | `databento`). Bei `databento`: `DatabentoQuoteFeed.start()` beim Engine-Start, Symbolliste = Producer-Universum, Referenz täglich geladen.

- [ ] **Step 1: Failing test.** `test_engine_uses_databento_source_when_flagged` — mit `RT_QUOTE_SOURCE=databento` (+ gemocktem Feed) zieht der Poll-Zyklus Rows aus der Databento-Quelle, nicht vom FMP-Client.
- [ ] **Step 2:** Test → FAIL.
- [ ] **Step 3:** Feed-Lifecycle in Engine-Start/-Stop einhängen; Referenz-Reload pro Session-Rollover; `updated_epoch` weiterhin pro Poll setzen.
- [ ] **Step 4:** Test → PASS; volle realtime_signals-Suite grün.
- [ ] **Step 5:** Commit (`feat:`), via skipp-pr-flow.

**Verifikation:** Ein env-Flag schaltet die Quelle um; FMP-Pfad bleibt Default und unangetastet.

### Task 2.2 — Shadow-Deploy: Databento-Producer parallel, Snapshot getrennt

**Files:**
- Railway `smc-signals-producer` (2. Instanz oder `a0-fast-shadow` erweitern), env `RT_QUOTE_SOURCE=databento`, separater Snapshot-Pfad
- Reuse: das schon existierende A0-Parity-Journal (`RT_A0_PARITY_LOG_DIR`)

- [ ] **Step 1:** Zweiten Producer im Shadow starten (`RT_QUOTE_SOURCE=databento`), der in einen **separaten** Snapshot schreibt (nicht den produktiven `latest_realtime_signals.json`).
- [ ] **Step 2:** **`RT_A0_PARITY_LOG_DIR` jetzt auch am produktiven FMP-Producer setzen** (fehlt heute!) — erzeugt endlich die FMP-Gegenseite fürs Parity-Journal.
- [ ] **Step 3:** Über ≥3 saubere Handelstage `scripts.report_a0_parity` fahren (FMP-Journal × Databento-Journal, jetzt auf demselben liquiden Universum).
- [ ] **Step 4:** Divergenzen triagieren: erwartet sind Databento-**früher**-Fires (Echtzeit vs. 15-min-FMP) — das ist der gewünschte Effekt, kein Fehler. `rule_state_mismatch` untersuchen.

**Verifikation:** Parity-Report existiert erstmals auf liquiden Symbolen; Databento-Seite ist ≥ so früh wie FMP, ohne fehlende/spurious A0.

---

## Phase 3 — Cutover

### Task 3.1 — Produktiven Snapshot auf Databento umstellen

- [ ] **Step 1: Cutover-Gate** (analog Cloud-Worker-Runbook): ≥3 saubere Handelstage Shadow, Parity ohne unerklärte Divergenz, Feed-Reconnect real beobachtet, `data_age_ms` p99 < 2 s.
- [ ] **Step 2:** Produktiven `smc-signals-producer` auf `RT_QUOTE_SOURCE=databento` setzen (Redeploy). Snapshot-Pfad = produktiv.
- [ ] **Step 3:** `/smc_live` end-to-end verifizieren: `signal_level`/`trade_*` erscheinen, `updated_epoch` frisch, Sidecar-Panel zeigt Signale. FMP-Quote-Poll ist jetzt aus.
- [ ] **Step 4:** 1 Handelstag beobachten; Rollback = Flag zurück auf `fmp` + Redeploy (Codepfad noch vorhanden).

**Verifikation:** Produktive Signale stammen aus Databento; `/smc_live` unverändert im Format; FMP-batch-quote-Traffic auf ~0.

### Task 3.2 — Bandbreiten-Effekt messen & FMP-Plan-Downgrade prüfen

- [ ] **Step 1:** Nach 1 Abrechnungswoche `provider_usage_bridge`-Bytes vergleichen: erwarteter Wegfall des `batch-quote`-Blocks (~11 GB @20s, mehr bei fast/ultra).
- [ ] **Step 2:** Verbleibende FMP-Bandbreite gegen Tier-Grenzen halten (News ~70 GB bleibt!). Falls Summe unter Premium (50 GB) fällt → **Downgrade Ultimate→Premium prüfen** — ABER erst verifizieren, dass keine genutzten Ultimate-only-Endpoints (insider/13F/political) gebraucht werden.
- [ ] **Step 3:** Entscheidung dokumentieren (`docs/`).

**Verifikation:** Gemessene Bandbreiten-Ersparnis; belegte Plan-Empfehlung.

---

## Phase 4 — Nachziehen (optional, nach stabilem Cutover)

- [ ] **Extended-Hours-Quotes** (`batch-aftermarket-quote/-trade`) auf Databento umstellen — EQUS.MINI deckt 04:00–20:00 ET; `_poll_extended_shadow` analog Phase 1 anbinden. Vorher prüfen, ob EQUS.MINI Pre/Post-Market-Volumen ausreichend abdeckt.
- [ ] **Kalibrierungs-Bars** (`historical-chart/1min`, `fetch_intraday_bars.py`) auf Databento historical umstellen — nicht zeitkritisch, reine Bandbreiten-/Konsistenz-Ersparnis.
- [ ] **`^VIX` bleibt FMP** — 1 Call/30 min, vernachlässigbar; nicht anfassen.

---

## Explizit NICHT in diesem Plan

News (`newsstack_fmp`), Fundamentals/Earnings/Analyst/Insider/13F (`macro.py` Ultimate), Macro/Economic-Calendar/Treasury/Sector, EOD-Batch-Pipeline (`run_open_prep`). Databento liefert dafür keine Daten; FMP bleibt Pflicht. Der News-Block (~70 GB/30d) ist der eigentliche Bandbreiten-Haupttreiber und wird von dieser Migration NICHT berührt — eine separate News-Bandbreiten-Optimierung (Poll-Intervall, Dedup) wäre ein eigener Plan.

## Rollback

Jede Phase ist über `RT_QUOTE_SOURCE=fmp` + Redeploy sofort umkehrbar; kein FMP-Codepfad wird vor erfülltem Cutover-Gate entfernt. Der FMP-Producer-Codepfad bleibt bis mindestens eine volle saubere Abrechnungsperiode nach Cutover erhalten.

## Architektur-Entscheidung (ENTSCHIEDEN 2026-07-25)

**Eingebetteter Databento-Feed im Producer, ohlcv-1s.** `smc-signals-producer` hält einen eigenen `db.Live`-Consumer (ohlcv-1s, explizite Producer-Symbolliste) im selben Prozess, füllt den Bar-Cache, aus dem `DatabentoQuoteSource` die FMP-kompatiblen Rows baut. Begründung: feinere Latenz (1 s statt der 1-min-Overlay-Kadenz des Daemons), Signal-Logik bleibt am Ort in `realtime_signals.py`, entkoppelt von der Overlay-Refresh-Kadenz. Der zweite Live-Stream (zusätzlich zum ALL_SYMBOLS-ohlcv-1m-Feed des `live_overlay_daemon`) ist akzeptiert; EQUS.MINI Standard hat kein Verbindungs-/Bandbreitenlimit. Falls Databento später ein Per-Session-Limit einführt, ist der Fallback dokumentiert: Signal-Compute in den Daemon ziehen und Snapshot dort schreiben.
