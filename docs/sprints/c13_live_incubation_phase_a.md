# Sprint C13 — Live-Inkubation Phase A scharf schalten

**Datum:** 2026-04-27
**Owner:** Steffen Preuss
**Voraussetzung:** PR #331 grün und gemerged
**Ziel:** Vom „methodisch komplett“ zum ersten echten Track-Record-Datenpunkt

**Status (2026-05-14):** **CLOSED — NO-GO** am Sprint-Tag 16 von 28. Sign-off-Dokument: [`docs/c8_phase_a_signoff_2026-05-14.md`](../c8_phase_a_signoff_2026-05-14.md). Begründung: T1 (IBKR Paper-Onboarding) blockiert die gesamte Daten-Aufnahme; 0 closed trades in allen 4 Familien an Tag 16; alle 9 Cron-Runs schreiben leere Records (`metrics={}, n_events=null`). Folge-Sprint: **C13b — Daten-Aufnahme entsperren** ([`docs/sprints/c13b_data_intake_unblock.md`](c13b_data_intake_unblock.md)).

## Warum dieser Sprint

Die SMC-Calibration-Pipeline ist methodisch fertig (C1–C12 + Cross-Cutting). Was fehlt, ist **das Einschalten**: die produktive Schleife aus realen Setups → IBKR-Submissions → Outcomes → Drift-Berechnung → Calibration-Report. Solange diese Schleife nicht läuft, bleibt der C12-Trigger BLOCKED, der Phase-B-Promotion-Gate aus PR #331 läuft trocken, und der Track-Record-Gate sieht keine Daten.

Phase-A ist explizit **paper-trading mit 10 % Sizing** ([`docs/c8_live_incubation_runbook.md`](https://github.com/skippALGO/skipp-algo/blob/main/docs/c8_live_incubation_runbook.md) §"Phase-A — Paper"). Risiko: null. Erkenntnis: maximal, weil die produktive Wiring zum ersten Mal läuft.

## Sprint-Scope (4 Wochen, 2026-04-28 bis 2026-05-25)

### T1 — IBKR Paper-Account-Onboarding (Tag 1–3)

**Ziel:** Live-Verbindung zu IBKR Paper-Trading. ⚙ operativ, nicht ⚠.

#### T1.0 Pre-Flight Account-Checkliste (vor jedem anderen T1-Step)

Alle vier Punkte MÜSSEN grün sein, bevor das erste Setup gegen Paper-Gateway geht ([IBKR API Market Data Subscriptions](https://www.interactivebrokers.com/campus/ibkr-api-page/market-data-subscriptions/)):

- [ ] **Account-Typ ist IBKR Pro** — IBKR Lite hat kein API-Trading; Demo-Accounts können keine Marktdaten abonnieren. Verifizieren in Client Portal → Settings → Account Configuration.
- [ ] **Mindest-Equity ≥ $500 USD** im Live-Account (Paper-Account selbst hat kein Cash, aber das Subscription-Minimum gilt für den Master-Live-Account, der die Daten zur Verfügung stellt). Plus etwaige Subscription-Kosten on top.
- [ ] **Subscriber-Status auf "Non-Professional"** — Default ist Professional → Pro-Rates 5–10× teurer. Client Portal → Settings → Market Data Subscriptions → Subscriber Status.
- [ ] **Market Data API Access aktiviert** in Client Portal → Market Data Subscriptions → API enable.

#### T1.1 Marktdaten-Abos

**Abos die für C13 Phase-A genutzt werden:**

- [ ] ✅ **US Real-Time Non Consolidated Streaming Quotes** (Gebühr erlassen) — kostenlos, IBKR Pro inkl., liefert Real-Time-Streaming für alle US-Stocks/ETFs via Cboe One + IEX. **API-fähig**: Standard-Pfad über `reqMktData()` ([IBKR Market Data Pricing](https://www.interactivebrokers.com/en/pricing/market-data-pricing.php)). Caveat: non-konsolidiert — keine echte NBBO; reicht aber für Phase-A Paper-Trading.
- [ ] ✅ **US-Investmentfonds (NP, L1)** (Gebühr erlassen) — kostenlos, aktivieren weil schadlos. Wird in der SMC-Pipeline NICHT konsumiert (Mutual Funds = Daily-NAV, keine Intraday-Setups), liegt brach als Optionalfeld.
- [ ] ✅ **NYSE Order Imbalances (NP)** ($1.00/Mo) — Pre-Open-Auction-Imbalance für NYSE-gelistete Stocks (~25-30 % des Watchlist-Universums: LAC, NIO, ZIM, JOBY, PINS, BFLY, TGNA, CDE). Keine Abhängigkeit zu anderen Abos. **API-fähig**: `reqMktData(id, contract, "225", False, False, [])` → Tick 34 (Auction Volume), 35 (Auction Price), 36 (Auction Imbalance), 61 (Regulatory Imbalance) ([TWS API Tick Types](https://interactivebrokers.github.io/tws-api/tick_types.html)). Auction-Imbalance wird ~09:28 ET veröffentlicht — 2 Minuten vor RTH-Open. Phase A: passive Erfassung (T8). Phase B: Pre-Trade-Filter.
- [ ] ✅ **NYSE MKT Order Imbalances (NP)** ($1.00/Mo) — analog für NYSE-American-(AMEX-)gelistete Stocks (~20 % des Watchlist-Universums: KULR, BATL, TMQ, INDO, AGIG, TMDE, CATX). Keine Abhängigkeit. Gleiche API-Pfad-Logik wie NYSE Order Imbalances.

**Abos für Phase-B aufgeschoben** (NICHT in C13):

- ⏳ US Securities Snapshot and Futures Value Bundle ($10/Mo, ab $30 Commissions waived) — vor Phase-B-Promotion subscriben, weil non-konsolidierte Quotes deine Slippage-Drift-Berechnung in [`scripts/compute_live_drift.py`](https://github.com/skippALGO/skipp-algo/blob/main/scripts/compute_live_drift.py) verfälschen können
- ⏳ OPRA Top of Book ($1.50/Mo) — nur falls SMC-Setups jemals auf Optionen erweitert werden; aktuell nicht in `EventFamily`

#### T1.2 Adapter-Smoke + Risk-Limits

- [ ] `scripts/smc_to_ibkr_adapter.py` gegen Paper-Gateway smoken: 1 Setup → IBKROrderIntent → erfolgreiche `placeOrder`-Antwort, ohne dass die Risk-Limits aus [`scripts/live_risk_limits.py`](https://github.com/skippALGO/skipp-algo/blob/main/scripts/live_risk_limits.py) den Killswitch auslösen
- [ ] `RiskLimits` mit realistischen Caps konfigurieren (max_notional_per_order, max_positions_open, max_daily_loss_bps) und in `cache/live/risk_limits.json` einfrieren
- [ ] Pre-Phase-A-Checkliste aus dem Runbook abhaken (alle Boxen grün)

**Akzeptanzkriterium:** 1 erfolgreicher Round-Trip Setup → Paper-Order → ausgeführt → audit-log-Eintrag, alles deterministisch reproduzierbar.

### T2 — Daily-Cron operativ (Tag 3–5)

**Ziel:** Die vier-Schritt-Pipeline aus dem Runbook täglich automatisch.

- [ ] Cron-Job (oder GitHub-Actions-Schedule) für die vier Schritte aus [`docs/c8_live_incubation_runbook.md:122-146`](https://github.com/skippALGO/skipp-algo/blob/main/docs/c8_live_incubation_runbook.md): backfill_live_outcomes → build_backtest_reference drift-input → build_backtest_reference backtest-reference → compute_live_drift
- [ ] Cron läuft täglich nach Marktschluss (US-East-Coast 16:30 ET + 30 min Buffer = 21:00 UTC während EDT / 22:00 UTC während EST; Sprintzeitraum 2026-04-28 bis 2026-05-25 liegt vollständig in EDT → 21:00 UTC)
- [ ] `cache/live/drift_YYYY-MM-DD.json` und `cache/live/incubation_YYYY-MM-DD.jsonl` werden geschrieben, atomic (Pin-Test [`tests/test_atomic_write_call_sites.py`](https://github.com/skippALGO/skipp-algo/blob/main/tests/test_atomic_write_call_sites.py))
- [ ] `terminal_tabs/drift_loader.py` rendert die letzten 7 Drift-Reports im Dashboard
- [ ] Cron-Failure-Alerting: Slack/Email bei Job-Failure (oder mindestens GitHub-Actions-Notification)

**Akzeptanzkriterium:** 5 aufeinanderfolgende Cron-Runs schreiben vollständige Drift-Reports ohne manuelle Intervention.

### T3 — Phase-A Setups & echte Trades (Woche 1–4)

**Ziel:** Die 28-Tage-Inkubation aus [`scripts/run_smc_live_incubation.py:107-118`](https://github.com/skippALGO/skipp-algo/blob/main/scripts/run_smc_live_incubation.py) durchziehen.

- [ ] Tägliche SMC-Setup-Generierung in `cache/live/setups_YYYYMMDD.jsonl` (über die existierende `smc_core/scoring.py`-Pipeline)
- [ ] `gate_status.json` aus dem aktuellen Track-Record-Gate (oder bei kaltem Start: alle Familien `amber`, mindestens `BOS` oder `FVG` mit echtem `amber` aus historischem Backtest)
- [ ] Tägliche Submission via `python -m scripts.run_smc_live_incubation --phase paper ...` (Runbook-Befehl)
- [ ] Ziel: ≥ 20 paper trades closed in 28 Tagen × 4 Familien = idealerweise 80+ closed trades insgesamt; minimal 20 pro Familie für Phase-A-Sign-off

**Operative Halt-Trigger** (aus Runbook):
- Killswitch-Fire einmal → halt + Debug, kein Phase-A-Sign-off
- Drift-Verdict `concerning` 2 Tage in Folge → halt + Debug
- Drift-Verdict `fail` jemals → halt + Post-Mortem

**Akzeptanzkriterium:** ≥ 20 paper trades pro Familie (BOS, OB, FVG, SWEEP), 28+ Tage live, kein Killswitch.

### T4 — Backtest-Slippage-Sample bauen (Woche 1–2, parallel zu T3)

**Ziel:** Phase-B-Promotion-Gate aus PR #331 entsperren. ✅ Code, ⚠ Daten.

Das Phase-B-Gate aus PR #331 (`scripts/check_phase_b_drift_readiness.py`) verbietet `slippage_ks_reference_type=synthetic_normal`. Solange kein echtes Backtest-Slippage-Sample existiert, BLOCKIERT Phase-B-Promotion strukturell — Phase-A kann darauf warten, Phase-B nicht.

- [ ] Historische Fills aus dem C1-Outcome-Backfill ([`open_prep/outcome_backfill.py`](https://github.com/skippALGO/skipp-algo/blob/main/open_prep/outcome_backfill.py)) extrahieren: für jeden gefüllten Trade Slippage in bps berechnen (`(fill_price − decision_price) / decision_price × 10000` mit Vorzeichen-Konvention nach Trade-Direction)
- [ ] Mindestens 200 Fills pro Familie sammeln (BOS, OB, FVG, SWEEP). Falls Backtest-Replay nötig: `scripts/walk_forward.py`-Outputs aus C2 mit synthetischen Fill-Modellen anreichern (Geometric Brownian-Motion-Slippage mit empirisch gefitteten Parametern aus den verfügbaren echten Fills)
- [ ] Output: `cache/calibration/backtest_slippage_samples_YYYY-MM-DD.json` mit Schema `{"family": {"slippage_bps": [...], "n": int, "source": "real_fills" | "replay"}}`
- [ ] `scripts/compute_live_drift.py` erweitern: `--slippage-reference cache/calibration/backtest_slippage_samples_*.json` als Argument; `slippage_ks_reference_type` setzt sich auf `backtest_samples` wenn das File geladen wird
- [ ] Test: `tests/test_check_phase_b_drift_readiness.py` läuft GREEN gegen einen Drift-Report mit `backtest_samples`

**Akzeptanzkriterium:** Phase-B-Gate flippt von BLOCKED auf grün, sobald ein Drift-Report mit echtem Slippage-Sample emittiert wird.

### T5 — `families[]` Producer scharf schalten (Woche 2)

**Ziel:** Den C12-Trigger aus dem leeren in den datentragenden Zustand bringen.

PR #331 hat den `families[]`-Producer in [`scripts/emit_public_calibration_report.py`](https://github.com/skippALGO/skipp-algo/blob/main/scripts/emit_public_calibration_report.py) eingebaut. T5 verdrahtet die echten Inputs.

- [ ] `emit_public_calibration_report.py --include-families` läuft täglich im Cron nach `compute_live_drift` und liest:
  - `cache/live/incubation_*.jsonl` für `live_days` (Tage seit ersterer Submission pro Familie) und `n_trades` (closed trades)
  - `cache/live/audit_killswitch_*.jsonl` für `kill_switch_fires`
  - `cache/live/drift_*.json` für `drift_verdict` pro Familie
- [ ] Output: `cache/calibration/calibration_report_public_YYYY-MM-DD.json` mit voll besetztem `families[]`-Array
- [ ] `scripts/check_c12_trigger.py` täglich gegen den Report fahren; aktueller Erwartungs-Status: BLOCKED mit `failure_breakdown` (zu wenig live_days)
- [ ] Dashboard-Tab `tab_live_incubation.py` zeigt für jede Familie: Trade-Count-Progress-Bar, Tage-Counter, Drift-Verdict-Ampel

**Akzeptanzkriterium:** `check_c12_trigger.py` gibt jeden Tag deterministisch BLOCKED mit nachvollziehbarer `failure_breakdown` zurück (z.B. "BOS: live_days=14 < 90, n_trades=12 < 30").

### T7 — Wall Street Horizon Earnings-Calendar-Hook (Woche 1–2)

**Ziel:** Externe Event-Daten (Earnings, Splits, Dividends) für Pre-Trade-Filter und C5-Regime-Stratifikation produktiv schalten. **Subscription bestätigt aktiv** ([Wall Street Horizon IBKR](https://www.wallstreethorizon.com/interactive-brokers)).

WSH ist ✅ über die TWS API verfügbar via `reqWshMetaData` + `reqWshEventData` ([TWS API Fundamentals](https://interactivebrokers.github.io/tws-api/fundamentals.html), [WSH Event Filters](https://interactivebrokers.github.io/tws-api/wshe_filters.html)). Repo hat bereits den Daten-Slot: [`smc_core/types.py:13`](https://github.com/skippALGO/skipp-algo/blob/main/smc_core/types.py) definiert `EventType = Literal["EARNINGS", "FOMC", "CPI", "NFP", "OPEX", "OTHER"]`. Heute ist das Feld unbedient.

#### T7.1 WSH-API-Wrapper bauen

- [ ] Neuer Modul `open_prep/wsh_events.py` mit:
  - `fetch_wsh_metadata(client) -> dict` — ruft `reqWshMetaData(reqId=1100)`, parst die JSON-Antwort aus `wshMetaData`-Callback, gibt verfügbare `event_types` und `filters` zurück. **Pflicht: einmal pro Tag nach TWS-Restart aufrufen** ([WSH Filters Doc](https://interactivebrokers.github.io/tws-api/wshe_filters.html))
  - `fetch_wsh_events(client, conIds: list[int], start_date: str, end_date: str, event_types: tuple[str, ...] = ("wsh_ed", "wshe_bod", "wshe_options"), limit: int = 100) -> list[dict]` — baut JSON-Filter (`{"country": "All", "watchlist": [conIds], "wsh_ed": "true", ...}`), ruft `reqWshEventData(reqId, WshEventData(filter=...))`, sammelt aus `wshEventData`-Callback. WSH-Hinweis: keine konkurrenten Requests, sequentiell durchgehen
  - `map_wsh_event_to_internal(wsh_event: dict) -> SmcEvent` — mappt WSH-Event-Tags auf den existierenden `EventType`-Literal (`wsh_ed` → `EARNINGS`, `wshe_fomc` → `FOMC` falls vorhanden, sonst `OTHER`)
  - Atomic-write Cache: `cache/live/wsh_events_YYYY-MM-DD.json` (gepinnt durch [`tests/test_atomic_write_call_sites.py`](https://github.com/skippALGO/skipp-algo/blob/main/tests/test_atomic_write_call_sites.py) nach PR #331-Erweiterung auf `open_prep/`)
- [ ] Tests `tests/test_wsh_events.py`:
  - Fixture mit dummy `wshMetaData`-JSON (echte WSH-Antwort als golden-file pinnen) → Filter-JSON-Builder produziert deterministisch erwartete Strings
  - Fixture mit dummy `wshEventData`-JSON für AAPL → Mapping liefert korrekte `SmcEvent`-Liste
  - Negative-Path: WSH-API-Disconnect → `RuntimeError` mit klarer Message, kein silent-`None`

#### T7.2 Pre-Trade-Earnings-Filter

- [ ] In `scripts/run_smc_live_incubation.py` einen Pre-Submission-Hook ergänzen: bevor ein Setup an IBKR geht, gegen `cache/live/wsh_events_YYYY-MM-DD.json` prüfen, ob für das Symbol ein `EARNINGS`-Event in den nächsten 24h liegt. Falls ja → Setup als `skipped_due_to_earnings_window` ins audit-log, **nicht** submitten
- [ ] Konfigurierbar machen: Default `earnings_blackout_hours = 24`, in `cache/live/risk_limits.json` parametrierbar
- [ ] Tests: 3 Setup-Szenarien (Earnings in 12h → skip, in 48h → pass, kein Earnings → pass), Audit-Log enthält Skip-Reason

#### T7.3 C5-Regime-Bucket „earnings_window“

- [ ] [`scripts/regime_stratification.py`](https://github.com/skippALGO/skipp-algo/blob/main/scripts/regime_stratification.py) liest `regime_at_entry` schon — Producer ergänzen, der für jeden Trade beim Audit-Log-Schreiben einen zusätzlichen Bucket-Tag setzt: `earnings_window: True` falls `EARNINGS` in ±48h um Trade-Entry, sonst `False`
- [ ] Stratifizierte Drift-Auswertung: pro Familie × `earnings_window`-Bucket separate Drift-Verdicts. Erwartung: Earnings-Window-Trades zeigen höhere Slippage-Variance — wenn das durch Stratifikation aus dem Aggregate herausgerechnet wird, fällt das `concerning`-Drift-Rauschen in der Pipeline
- [ ] Output-Erweiterung in [`scripts/emit_public_calibration_report.py`](https://github.com/skippALGO/skipp-algo/blob/main/scripts/emit_public_calibration_report.py): zusätzlich `families_by_earnings_window` (additiv, Schema-Bump 1.4.0)

**Akzeptanzkriterium T7:**
- Daily-Cron lädt täglich 14 Tage Forward-Looking-Events für die aktuelle Watchlist (alle Symbole mit aktiven Setups in den letzten 30 Tagen) — Earnings, Dividenden, Options-Expiration
- Mind. 1 Setup im Sprint-Zeitraum wird durch den Earnings-Filter geskipped — verifizierbar via audit-log-Eintrag
- C5-Regime-Stratifikation zeigt für mind. 1 Familie messbare Hit-Rate-Differenz zwischen `earnings_window=True` und `False`

### T8 — Order-Imbalance-Hook (Woche 1–4, passive Erfassung)

**Ziel:** Opening-Auction-Imbalance-Daten für NYSE- und AMEX-gelistete Watchlist-Symbole täglich erfassen, **ohne** in Phase A die Trade-Logik zu verändern. Phase B: Pre-Trade-Filter und Setup-Scoring.

**Phase-A-Scope (passiv):**

#### T8.1 IBKR-Imbalance-Wrapper bauen

- [ ] Neues Modul `scripts/imbalance_data.py` mit Funktion `fetch_opening_imbalance(symbol, exchange, contract) -> ImbalanceSnapshot`
- [ ] Verwendet `reqMktData(reqId, contract, genericTickList="225", snapshot=False, regulatorySnapshot=False, mktDataOptions=[])` analog zu [`scripts/execute_ibkr_watchlist.py:702`](https://github.com/skippALGO/skipp-algo/blob/main/scripts/execute_ibkr_watchlist.py)
- [ ] EWrapper-Callbacks `tickPrice` (Tick 35 Auction Price) und `tickSize` (Tick 34 Auction Volume, 36 Auction Imbalance, 61 Regulatory Imbalance) abgreifen
- [ ] Polling-Fenster **09:28–09:30 ET** (15:28–15:30 Europe/Berlin Sommerzeit) — letzten Wert vor 09:30 als Snapshot persistieren
- [ ] Exchange-Routing: NYSE-Listings → NYSE-Imbalance-Feed, NYSE-American → NYSE-MKT-Feed; NASDAQ-Listings ohne Daten (kein Abo) → `imbalance_available=False`
- [ ] Snapshot-Schema: `{symbol, exchange, listing_exchange, ts_utc, auction_volume, auction_price, auction_imbalance_shares, auction_imbalance_side: Literal["BUY", "SELL", "NEUTRAL"], regulatory_imbalance_shares, schema_version: "1.0.0"}`

#### T8.2 Daily-Cron-Erweiterung

- [ ] Neuer Cron-Step **vor** dem Open: `scripts/collect_opening_imbalances.py --watchlist <csv> --output cache/live/imbalance_YYYY-MM-DD.jsonl` läuft 09:27 ET via Action-Schedule
- [ ] Atomic-Write (Pin-Test [`tests/test_atomic_write_call_sites.py`](https://github.com/skippALGO/skipp-algo/blob/main/tests/test_atomic_write_call_sites.py))
- [ ] Fehlertoleranz: kein Imbalance-Snapshot → `error: "NO_AUCTION_DATA"` Eintrag, Trade läuft trotzdem (Phase A blockiert NICHT)

#### T8.3 Backtest-Outcome-Join

- [ ] In `scripts/backfill_live_outcomes.py` einen Join-Step einbauen: für jeden geschlossenen Trade den Imbalance-Snapshot aus `cache/live/imbalance_*.jsonl` als Outcome-Annotation anhängen (`outcome.opening_imbalance_side`, `outcome.opening_imbalance_shares_normalized`)
- [ ] Normalisierung: `imbalance_shares / 30d_avg_volume` als Float-Bucket
- [ ] Schema: `outcomes.opening_imbalance` ist optional (NASDAQ-Listings haben es nicht)

#### T8.4 Korrelations-Report (am Sign-off, Tag 28+2)

- [ ] In `docs/c8_phase_a_signoff_2026-05-25.md` (T6) zusätzlicher Abschnitt: pro EventFamily ([`smc_core/scoring.py:33`](https://github.com/skippALGO/skipp-algo/blob/main/smc_core/scoring.py)) Hit-Rate-Vergleich `imbalance_aligned` (Imbalance-Side stimmt mit Trade-Direction überein) vs. `imbalance_opposed` vs. `imbalance_neutral`
- [ ] Bootstrap-CI 95 % aus C3-Modul auf die Subgroups anwenden, **ohne** Permutation-Test in Phase A — das ist Phase B (T8.5 Phase B)
- [ ] Verdict: Falls `|hit_rate_aligned - hit_rate_opposed| > 0.10` und CIs überlappen nicht → Phase-B-Filter lohnt sich; sonst Hook deaktivieren

**Phase-B-Vorbereitung (NICHT in C13, dokumentiert):**

- T8.5 (Phase B): Pre-Trade-Filter `imbalance_score` in [`smc_core/layering.py`](https://github.com/skippALGO/skipp-algo/blob/main/smc_core/layering.py) einbauen, analog zu `enriched_news_heat`. Aktivierung nur wenn T8.4 grün.
- T8.6 (Phase B): Neuen `EventType`-Member `"AUCTION_IMBALANCE"` in [`smc_core/types.py:13`](https://github.com/skippALGO/skipp-algo/blob/main/smc_core/types.py) — bisher unbedient, wird durch Imbalance-Snapshot gefüllt
- T8.7 (Phase B): C5-Regime-Bucket `imbalance_aligned` als zusätzliche Stratifikations-Dimension in `smc_core/scoring.py:36 _CALIBRATION_DIMENSIONS`

**Akzeptanzkriterium (Phase A):**
- 28+ Cron-Runs schreiben Imbalance-JSONL mit > 60 % Coverage der NYSE/AMEX-Listings im Watchlist (NASDAQ-Anteil zählt nicht)
- Backfill-Outcomes haben Imbalance-Annotation für alle NYSE/AMEX-Trades
- Korrelations-Report im Sign-off-Dokument vorhanden
- **Phase A blockiert nicht** auf fehlende Imbalance-Daten — der Hook ist passiv

**Out-of-Scope für Phase A:**
- Keine Pre-Trade-Filter-Aktivierung
- Kein Setup-Scoring-Anpassung
- NYSE ARCA Order Imbalances ($1.00/Mo + $1.50/Mo Network-B-Pflicht = $2.50/Mo Gesamt) bleibt **C14-Backlog**, weil ARCA primär ETFs listet und im Smallcap-Watchlist-Universum praktisch keine ARCA-Listings vorkommen

### T6 — Phase-A Sign-off-Review (Tag 28 + 2)

**Ziel:** Manueller Review-Pass durch dich. Kein Auto-Promotion (Runbook §"Why no auto-promotion").

- [ ] Sign-off-Checkliste aus Runbook §"Phase-A — Paper" abhaken:
  - [ ] ≥ 20 paper trades closed pro Familie
  - [ ] |paper-Sharpe / OOS-Sharpe − 1| < 0.30 (drift_score ≥ 0.70)
  - [ ] Slippage-K-S-p-value > 0.05 (gegen `synthetic_normal` ist OK in Phase-A)
  - [ ] Hit-Rate innerhalb C3-Bootstrap-CI
  - [ ] Killswitch nie gefeuert
- [ ] Sign-off-Dokument in `docs/c8_phase_a_signoff_2026-05-25.md` mit Tabellen pro Familie + Verdict
- [ ] **T8.4 Korrelations-Report** als eigener Abschnitt im Sign-off (Imbalance-Aligned vs. Opposed Hit-Rate)
- [ ] Bei GREEN: Sprint-Plan C14 (Phase-B Promotion) eröffnen

**Akzeptanzkriterium:** Klares GO/NO-GO pro Familie; bei NO-GO klar dokumentierter Halt-Grund + Debug-Plan.

## C14-Backlog (NICHT in C13)

Diese Marktdaten / Drittanbieter sind sinnvoll, aber gehören in Folge-Sprints:

- **Acuity Sentiment API (separat)** — Sentiment-IDs (Bullish/Bearish/Fear/Hype/News-Volume) per Asset über Acuity REST API ([Acuity Sentiment API Docs](https://knowledgebase.acuitytrading.com/en/acuity-client-knowledge-base/acuity-sentiment-api-documentation)). Repo hat bereits den Hook in [`smc_core/layering.py:34-180`](https://github.com/skippALGO/skipp-algo/blob/main/smc_core/layering.py) (`signed_news`, `enriched_news_heat`), heute unbedient. Caveat: Acuity-iFrame-Abo aus Client Portal liefert NUR Browser-Widget — die echte API ist eine separate Lizenz, Pricing nicht öffentlich. Erst nach Phase-A wenn klar ist, ob News-Heat tatsächlich Outcome-Variance erklärt.
- **TipRanks Basic, Trading Central Technical Insight, Reflexivity Basic, Passiv Community, The Economy Matters** — alle aktiv und kostenlos, aber für SMC-Pipeline ohne API-Wert (UI-Tools, Daily-Daten, konkurrierende TA-Methodik). Aktiviert lassen, NICHT integrieren.
- **NYSE ARCA Order Imbalances** ($1.00/Mo + $1.50/Mo Network-B-Pflicht = $2.50/Mo) — ARCA listet primär ETFs/ETPs; im aktuellen Smallcap-Watchlist-Universum praktisch keine ARCA-Listings. Erst dann sinnvoll, wenn das Universum auf ETF-Setups erweitert wird.
- **NASDAQ (Network C/UTP) L1** ($1.50/Mo), **NYSE (Network A/CTA) L1** ($1.50/Mo), **Network B L1** ($1.50/Mo) — konsolidierte NBBO-Quotes pro Listing-Exchange. Sinnvoll **nur** wenn T4 (Backtest-Slippage-Sample) zeigt, dass die Non-Konsolidierten US-RT-Quotes (Cboe + IEX) systematisch von der echten NBBO divergieren. Vorher = blinder Umbau.
- **Cboe One (NP, L1)** ($1.00/Mo standalone) — redundant zu US RT Non-Cons (IBKR-PRO), das bereits Cboe-BATS/BYX/EDGX/EDGEA/IEX-Aggregat liefert. Nur via Cboe One Add-On (Phase-B-Pfad mit Snapshot-Bundle) sinnvoll.

## Was Phase-A NICHT leistet (klar abgegrenzt)

- **Kein Track-Record-Gate-GREEN** — der Gate-Schwellwert (PSR ≥ MinTRL) ist nach 28 Tagen × 20 Trades statistisch zu dünn; das ist Phase-B-Aufgabe (90 Tage × 30 Trades)
- **Kein C12-Trigger-GREEN** — `MIN_LIVE_DAYS = 90` ([`scripts/check_c12_trigger.py:70`](https://github.com/skippALGO/skipp-algo/blob/main/scripts/check_c12_trigger.py)); RL-Execution-Layer bleibt während Phase-A komplett deaktiviert
- **Kein C10-ML-Trainer-Live-Schalten** — XGBoost-Trainer bekommt erst nach Phase-A genug echte Outcomes; ML-Recalibrator-Hot-Swap ist Phase-B-Sprint
- **Kein Marketing/Methodik-Release** — der Track-Record ist erst nach Phase-B "extern verkaufbar" (Runbook §"Phase-B"); Methodik-Doku bleibt privat

## Risiken & Gegenmaßnahmen

| Risiko | Wahrscheinlichkeit | Auswirkung | Gegenmaßnahme |
|---|---|---|---|
| IBKR-Paper-Gateway-Disconnect mitten im Trade | mittel | Trade-Halbfüllung, audit-Log-Inkonsistenz | `submit_fn`-Retry mit exponential backoff; bei 3 Failures → Killswitch |
| Drift-Verdict `concerning` 2× → erzwungener Halt | hoch in den ersten 2 Wochen | Phase-A-Verlängerung um 1–2 Wochen | Phase-A-Budget auf 6 Wochen statt 4 ansetzen |
| < 20 closed trades pro Familie in 28 Tagen | mittel (besonders SWEEP — selten) | Sign-off blockiert | Pro Familie eigenes Trade-Counter-Tracking; bei Unterschreitung Phase-A für die betroffene Familie verlängern, andere können promoviert werden |
| Backtest-Slippage-Sample nicht generierbar (zu wenig historische Fills) | mittel | T4 blockiert, Phase-B verzögert sich | Synthetic-Replay-Pfad als Fallback (T4 Bullet 2); explizite Markierung `source: "replay"` im Sample |
| Imbalance-Snapshot-Coverage < 60 % NYSE/AMEX-Listings (z. B. wegen 09:28-ET-Gateway-Reconnect) | mittel | T8.4-Report statistisch dünn, Verdict unsicher | Phase A blockiert NICHT; Coverage als Caveat im Sign-off; falls NO-GO durch Imbalance allein → 14 Tage zusätzliche passive Erfassung in C14 |
| 422 TWS-Quote-Lines bei gleichzeitiger Daily-Watchlist (5 Symbole) + Imbalance-Polling überschritten | niedrig | Imbalance-Polling failt für letzte Symbole | 5 Symbole × 1 Imbalance-Stream = 5 Lines, vernachlässigbar gegen 422; Booster nicht nötig |

## Definition of Done (Sprint C13)

✅ **MUSS** (für Sprint-Abschluss):
- Daily-Cron läuft 14+ Tage ohne manuelle Intervention
- `families[]`-Producer schreibt täglich vollständige Records
- `check_c12_trigger.py` läuft täglich, dokumentierter BLOCKED-Verdict
- Backtest-Slippage-Sample existiert für mind. 2 von 4 Familien (BOS + FVG sind realistisch)
- WSH-Earnings-Hook produktiv: Daily-Cache vorhanden, Pre-Trade-Filter aktiv, mind. 1 Earnings-Skip im audit-log dokumentiert
- Order-Imbalance-Hook passiv: 28+ Imbalance-JSONL-Snapshots geschrieben, Outcome-Join läuft, Korrelations-Report im Sign-off

🧪 **SOLL** (Phase-A-Promotion-Voraussetzung):
- 28+ Live-Tage erreicht
- ≥ 20 closed trades pro Familie
- Sign-off-Dokument geschrieben + GO/NO-GO entschieden

⚠ **NICE-TO-HAVE**:
- Backtest-Slippage-Sample für alle 4 Familien
- Cron-Failure-Alerting auf Slack
- Integrationstest für PPO/SAC mit `requirements-rl.txt` (deferred-Anker aus Deep-Review)

## Cleanup-Backlog (deferred Anker, nicht in Phase-A)

- Strategy-Permutation auf Schema B umrouten ([`scripts/strategy_permutation.py`](https://github.com/skippALGO/skipp-algo/blob/main/scripts/strategy_permutation.py))
- Output-Fixture-Pin zusätzlich zum AST-Pin
- C11 Skip-Anker-Trigger bei Phase-B-Sign-off automatisch öffnen
- `_atomic_append_audit` O(n²) → O(n) bei Phase-C-Migration

## Quellen & Referenzen

- Runbook: [`docs/c8_live_incubation_runbook.md`](https://github.com/skippALGO/skipp-algo/blob/main/docs/c8_live_incubation_runbook.md)
- Phase-Pass-Kriterien: [`scripts/run_smc_live_incubation.py:107-159`](https://github.com/skippALGO/skipp-algo/blob/main/scripts/run_smc_live_incubation.py)
- C12-Trigger: [`scripts/check_c12_trigger.py:70-71`](https://github.com/skippALGO/skipp-algo/blob/main/scripts/check_c12_trigger.py) (`MIN_LIVE_DAYS=90`, `MIN_LIVE_TRADES=30`)
- Phase-B-Promotion-Gate (aus PR #331): `scripts/check_phase_b_drift_readiness.py`
- Drift-Schema (aus PR #331): `schema_version=1.1.0` in `cache/live/drift_*.json`
- Deep-Review-Befunde: `DEEP_REVIEW_C1_C12_2026-04-27.md` (extern geteiltes Workspace-Artefakt, nicht im Repo eingecheckt)
- IBKR Tick Types (Auction 34/35/36/61): [TWS API Tick Types](https://interactivebrokers.github.io/tws-api/tick_types.html)
- IBKR Auction Columns Glossar: [Auction Columns Documentation](https://www.ibkrguides.com/traderworkstation/auction-columns.htm)
- NYSE Closing-Auction-Imbalance Methodik: [NYSE Imbalance Reference](https://www.nyse.com/data-insights/nyse-introduces-closing-auction-imbalance-analysis-tool)
