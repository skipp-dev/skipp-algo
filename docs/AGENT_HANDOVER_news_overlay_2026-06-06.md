# Agent Handover — News Delivery & Live Overlay — 2026-06-06

Komplementär zu [AGENT_HANDOVER_2026-06-04.md](AGENT_HANDOVER_2026-06-04.md)
(jenes deckt ADR-0020 Options-Flow / ADR-0019 / CI-Governance ab). Dieses
Dokument übergibt den **News-Delivery-** und **Live-Overlay-Workstream**:
warum die TradingView-News-Auslieferung blockiert war, was gefixt wurde, wie
News heute den Nutzer erreichen, und die beschlossene Strategie für intraday-
frische Werte via `request.get()`.

---

## 1. Ausgangslage: News wurden gebaut, aber nicht ausgeliefert

**Symptom:** `smc-library-refresh.yml` schlug seit **2026-05-29 07:23** in jedem
Lauf fehl (letzter grüner Lauf 2026-05-28 21:54). Fehlerhafter Step: *Run
TradingView readonly preflight*. Die Enrichment-/Generate-Stufe (News-Wert)
lief erfolgreich — der News-Wert wurde **gebaut**, aber der Publish (und damit
die Auslieferung an TradingView) ist hinter dem Preflight gegated und kam nie
durch.

---

## 2. Verifizierte Root Cause (TV-Preflight v7-Dashboard)

Beweis: CI-Artefakt `tv_preflight_ci.attempt_1.json` aus Run 26916970392.

- Ziel `SMC Long-Dip Dashboard v7` ([SMC_Dashboard.pine](../SMC_Dashboard.pine))
  ist das **erste** Mainline-Ziel mit `addToChart:true` (SMC Core davor hat
  `addToChart:false` und passiert).
- Diagnostics: `auth_ok/chart_ok/editor_ok = true`, aber
  `monaco/textarea/contenteditable/pineContainer = 0/0`,
  `pineButtons:["V2\nSave"]`, `pineTexts:["Publish","Save",...]`.
- **Deutung:** TradingView öffnet das publizierte Skript an eine **ältere
  gespeicherte Version ("V2") gepinnt** = historische/read-only Ansicht mit nur
  Save/Publish, **ohne editierbares Code-Surface**. Beide Add-Pfade (Editor-
  Button + Indicators-Dialog) scheitern, weil es kein Editor-Surface gibt.
- **NICHT** Auth-Expiry, **NICHT** kaputter Pine-Code, **NICHT** der addToChart-
  Selektor, **NICHT** der News-Pfad. TradingView-seitige Verhaltensänderung.

**Warum der Restore nicht griff:** `restoreHistoricalScriptVersionIfNeeded`
wurde nur aufgerufen, *nachdem* `hasVisibleEditorHost == true`. Bei v7 ist der
Host nie sichtbar (kollabiert zu V2/Save/Publish), also wurde Restore nie
versucht und `ensurePineEditor` warf (geschluckt von `addCurrentScriptToChart`
`.catch`). SMC Core funktioniert, weil dessen historische Ansicht weiterhin
einen Host zeigt.

---

## 3. Fix (committet + gepusht)

Datei: [automation/tradingview/lib/tv_shared.ts](../automation/tradingview/lib/tv_shared.ts)
— additiv, regressionsfrei:

1. `restoreHistoricalScriptVersionIfNeeded`: erkennt den Zustand jetzt über
   **Banner-Text ODER** einen direkt sichtbaren „restore this version"-Control
   (der Banner-Text war der fragile, von TV entfernte Teil).
2. `ensurePineEditor`: versucht im No-Host-Recovery-Zweig den Restore + Host-
   Recheck, bevor es aufgibt. Wiederverwendet die für SMC Core bewährten
   Restore-Selektoren; no-op, wenn nicht zutreffend.

**Validierung:** `npm run tsc:check` sauber, `npm run tv:test` **116/116**.
**Commit:** `6bcd64ff` (auf `main` gepusht).

### ⚠️ NICHT gegen Live-TradingView verifiziert
Aus der Agent-Umgebung nicht testbar (braucht `TV_STORAGE_STATE` /
`npm run tv:storage-state`). Lokale Verifikation:
`npm run tv:preflight:smc-mainline` bzw. `npm run tv:smoke-readonly`.
**Falls** die V2-Ansicht den „restore this version"-Control hinter dem
Versions-Button versteckt, ist der nächste Schritt: erst den Versions-Button
("V2") klicken, um den Restore-Affordance freizulegen. Die `-error.png`-
Screenshots (`automation/tradingview/reports/screenshots/`) werden heute
**nicht** als CI-Artefakt hochgeladen — Lücke: in den Upload-Pfad von
`smc-library-refresh.yml` aufnehmen, um Live-Diagnose zu ermöglichen.

---

## 4. Wie News heute den Nutzer erreichen (Consumer-1)

- **Consumer-1 = die publizierte SMC-Pine-Library auf TradingView**, kein
  interaktives Dashboard.
- News kommen als **eingebackene Konstanten** in der Library an:
  [SMC_Core_Engine.pine](../SMC_Core_Engine.pine) → `mp.NEWS_BEARISH_TICKERS`,
  `mp.NEWS_BULLISH_TICKERS`, `mp.NEWS_CATEGORY_MAP`, `mp.BREAKING_NEWS_TICKERS`,
  `mp.HIGH_IMPACT_NEWS_COUNT` etc.
- Aktualisierung = **Library neu publizieren** via Playwright-Flow
  ([smc-library-refresh.yml](../.github/workflows/smc-library-refresh.yml)),
  Cron **9×/Tag** (08/10/12/14/16/18/20/21/22 UTC, nach F-V8-D1 2026-06-16).
- Der newsapi-Snapshot wird stündlich aktualisiert (nach F-V8-D1: `2 * * * 1-5`,
  TTL 3300 s), aber Consumer-1 liest ihn nur beim 9×/Tag-Refresh. Es gibt einen
  48h-Stale-Gate
  ([smc_integration/repo_sources.py](../smc_integration/repo_sources.py),
  `_META_DOMAIN_STALE_HOURS = 48.0`). Quelle:
  [live_news_snapshot_json.py](../smc_integration/sources/live_news_snapshot_json.py)
  `load_raw_meta_input`.
- **Streamlit-Terminal ≠ Konsument-Pfad für Pine.** Streamlit
  ([streamlit_terminal.py](../streamlit_terminal.py),
  [docker-compose.yml](../docker-compose.yml)) ist ein **Menschen-UI**, läuft
  nur lokal/self-hosted, hat **keinen** Deploy-Workflow und kann von Pine
  **nicht** konsumiert werden.

**Kern-Constraint:** Pine kann zur Laufzeit nur über `request.get()` /
`request.seed()` externe Daten ziehen — nicht über die Library-Konstanten.

---

## 5. Beschlossene Strategie: Live Overlay via `request.get()` (Premium-only)

Vollständiges Planungsdokument:
[live_overlay_request_get_strategy_2026-06-04.md](live_overlay_request_get_strategy_2026-06-04.md)
(Commit `1a3440dd`, auf `main`).

**Modell: Slow Baseline + Fast Overlay**

| Kanal | Mechanismus | Cadence | Audience | Backtestbar |
|---|---|---|---|---|
| Slow Baseline (existiert) | eingebackene `mp.*`, Republish | 9×/Tag (nach F-V8-D1) | alle Tiers | ja (deterministisch) |
| Fast Overlay (geplant) | Pine `request.get()` → HTTPS-JSON | ~5 Min (pull) | **nur Premium+** | nein (live) |

**Produkt-Entscheidung (verriegelt, 2026-06-04):** Auslieferung **ausschließlich**
über Pine `request.get()` (TV Premium+). Lösungen, die der Nutzer installieren/
self-hosten muss (Streamlit-Terminal, Bot), sind **NO-GO** (Install-/Support-
Last). Non-Premium bleibt auf der 9×/Tag-Baseline (nach F-V8-D1); das Overlay ist ein
**Premium-Tier-Benefit**.

**Design-Regel:** Overlay augmentiert, ersetzt nie. Frisch → überschreibt
eingebackenen Default zur Laufzeit; stale/absent/unreachable → Fallback auf
`mp.*`. Backtests bleiben deterministisch (Overlay nur realtime).

**Feld-Klassifikation nach Intraday-Änderungsrate** (Details im Plan-Doc §3):
- 🔴 Phase 1: News, Flow Qualifier (`REL_VOL`, `DELTA_PROXY_PCT`, `ATS_*`),
  Squeeze/ATR (`SQUEEZE_ON/RELEASED`, `ATR_REGIME`), VIX/Tone (`VIX_LEVEL`,
  `TONE`, `GLOBAL_HEAT`).
- 🟡 Phase 2: Session-Context, OB/FVG-Lifecycle, Structure-State, Sektor-
  Rotation, Signal-Quality.
- 🟢 baked lassen: PE, Treasury/Yields, Short-Interest, Earnings, Universe,
  Market-Regime (EOD/täglich).
- 🔴 **Event-Risk** (`MARKET/SYMBOL_EVENT_BLOCKED`) ist sicherheitskritisch →
  **escalation-only** (Overlay darf einen Block *hinzufügen*, nie entfernen);
  Fail-Safe: bei Ausfall „caution", nie „clear".

**Architektur:** EIN kombinierter Endpoint `GET /smc_live?symbol=&tf=` liefert
ein „live overlay"-JSON pro Symbol (nicht 30 Endpoints). Gerüst existiert als
[SMC_TV_Bridge.pine](../SMC_TV_Bridge.pine) (`request.get()`-Zeile heute
auskommentiert; `f_getField`-Parser für flache `"key":value`-Paare vorhanden).

---

## 6. Nächste Schritte (Phase 1, bei Freigabe)

1. **JSON-Contract** präzise festziehen (Plan-Doc §4.1) — nested vs. flach
   (`flow_rel_vol`) entscheiden, um `f_getField` ohne neuen Parser
   wiederzuverwenden.
2. **FastAPI-Endpoint-Skeleton**, das den vorhandenen 5-Min-Snapshot ausliefert
   (zentral gehostet, ein Service; Nutzer installieren nichts).
3. **Pine-Overlay-Merge-Logik** in [SMC_TV_Bridge.pine](../SMC_TV_Bridge.pine):
   `resolved = (overlay_fresh && has_field) ? overlay : baked_mp` mit
   `OVERLAY_MAX_AGE_SEC`.
4. **Empfehlung:** echten Code auf eigenem Branch (nicht direkt `main`), da
   parallel weitere Agents arbeiten.

**Offene Fragen vor Build** (Plan-Doc §8): gemessene Update-Frequenz pro Feld
verifizieren; Hosting-Ort; Premium-Entitlement-Durchsetzung (Endpoint kann den
TV-Nutzer nicht authentifizieren → „Premium-only" via Skript-Zugriff, nicht
API-seitig; Payload effektiv öffentlich → nichts Sensibles einbetten).

---

## 7. Lessons / Disziplin

- **Verify-before-claim:** Der TV-Fix ist evidenzbasiert (strukturierte
  Diagnostics), aber **nicht** live verifiziert — das wurde durchgehend ehrlich
  so kommuniziert und gehört in jeden Folgeschritt.
- **Credential-Boundary:** `TV_STORAGE_STATE` wird vom Agent nicht angefragt/
  verwendet; Live-Verifikation erfordert eine authentifizierte TV-Session.
- **Detection nicht lockern:** `collectVisibleChartScriptState` /
  `isScriptVisibleOnChart` bewusst NICHT aufgeweicht — würde false-positives
  riskieren (kaputter Publish käme durch). Der Fix ist rein additiv auf einem
  zu 100% fehlschlagenden Pfad.
- **Parallel-Agent-Hygiene:** Bei geteiltem Working-Tree nur den eigenen
  Dateipfad stagen (`git add -- <pfad>`, kein `git add -A`); fremde uncommitted
  Dateien (z.B. eine korrupte `plan-2-8-monthly-digest.yml` mit verirrtem `e`
  vor `timeout-minutes:`) nicht anfassen.

---

## 8. Referenzen

- Repo-Memory: [tv-preflight-v7-historical-version-2026-06-04.md] (intern)
- Commits: `6bcd64ff` (TV-Fix), `1a3440dd` (Strategie-Doc), beide auf `main`.
- Plan-Doc: [live_overlay_request_get_strategy_2026-06-04.md](live_overlay_request_get_strategy_2026-06-04.md)
- Anderer Workstream: [AGENT_HANDOVER_2026-06-04.md](AGENT_HANDOVER_2026-06-04.md)
