# SMC Deep Review — Priorisierte Befunde und Lösungs-Blueprints

Date: 2026-04-17
Branch: `main` @ `b1def692`
Sources: Deep Review v9, Owner Review (2026-04-14), Final Status Review (2026-04-16), Measurement Baseline (2026-04-17)
Scope: 14 konsolidierte Findings mit Engineering-Ready Solution Blueprints

---

## Executive Summary

Dieses Dokument konsolidiert alle priorisierten Befunde aus vier
aufeinanderfolgenden Review-Phasen des SMC Long-Dip Suite Systems in ein
einheitliches, engineering-ready Format. Es identifiziert 14 Findings (F-01
bis F-14), bewertet sie nach Prioritaet (P0–P2) und ordnet jedem Finding einen
konkreten Loesungs-Blueprint mit Abhaengigkeitsketten zu.

**Prioritaetsverteilung:**

| Prioritaet | Anzahl | Findings |
|------------|--------|----------|
| P0 (blocking) | 3 | F-01, F-03, F-09 |
| P1 (high) | 7 | F-02, F-04, F-05, F-06, F-08, F-12, F-14 |
| P2 (medium) | 4 | F-07, F-10, F-11, F-13 |

**Gesamtstatus:** System operativ funktional und strukturell solide.
Verbleibende Arbeit ist korrektur- und haertungsorientiert, nicht
architektonisch.

---

## Findings

### F-01 — Governance Enforcement Gaps [P0]

**Quelle:** Owner Review §I Decision 4, Final Status Review §7

**Befund:**
Measurement Governance wurde erst am 2026-04-16 auf Hard-Blocking promoviert
(3 Gates: `BRIER_ABOVE_THRESHOLD`, `BRIER_REGRESSION`, `ECE_ABOVE_THRESHOLD`).
Der Uebergang von advisory-only zu policy-relevant ist unvollstaendig.
Soft-Warn-Enforcement ist Ad-hoc, nicht systematisch. Langfristrisiko:
Weiche Governance erzeugt falsche Sicherheit.

**Evidenz:**
- `smc_integration/release_policy.py` definiert `HARD_BLOCKING_DEGRADATION_CODES`
- Bewusst ausgeschlossen: `MEASUREMENT_EVENT_COVERAGE_LOW` (Bootstrap-Deadlock),
  `MEASUREMENT_CALIBRATED_ECE_REGRESSION` (Rausch-anfaellig)
- Keine konsistente Degradation-State-Vetting ueber alle Release-Gates

**Betroffene Pfade:**
- `smc_integration/release_policy.py`
- `scripts/run_smc_release_gates.py`
- `tests/test_smc_integration_release_gate_scripts.py`

**Blueprint:**
1. Codify Graduation-Pfad: Jedes soft-gate erhaelt `promote_after_runs: N`
   und `promote_condition` in `release_policy.py`
2. Automatisierte Degradation-State-Vetting als CI-Step
3. Dashboard-Warnung fuer soft-gate Verletzungen (nicht nur log)
4. Nach Run #3 (≤ 14 Tage): `ECE_REGRESSION` und `EVENT_COVERAGE_LOW`
   zur Hard-Promotion evaluieren

**Abhaengigkeit:** F-14 (Quality-Floor muss kalibriert sein, bevor
weitere Gates hart werden)

---

### F-02 — Evidence Collector Linkage [P1]

**Quelle:** Measurement Baseline §7, Final Status Review §9

**Befund:**
Evidence Collection laeuft lokal (258 Events, Metriken innerhalb
Schwellenwerten), aber CI-Reproduzierbarkeit ist nicht bewiesen.
Lokaler macOS-Run kann in parquet-Bibliotheksversionen, verfuegbaren
Daten und Timing vom CI abweichen.

**Evidenz:**
- Baseline Run: 12 Pairs, 258 Events, alle Metriken unter Schwellenwert
- Kein CI-Run fuer `smc-measurement-benchmark` oder
  `smc-deeper-integration-gates` auf aktuellem HEAD dokumentiert
- Bekannter Conda-vs-Venv-Python-Unterschied (pyarrow 19 vs. 23)

**Betroffene Pfade:**
- `.github/workflows/smc-measurement-benchmark.yml`
- `.github/workflows/smc-deeper-integration-gates.yml`
- `scripts/run_smc_measurement_benchmark.py`
- `artifacts/ci/measurement_benchmark/`

**Blueprint:**
1. CI-Measurement-Run auf aktuellem HEAD triggern
2. Artefakt-Vergleich: CI-Output vs. lokaler Baseline-Output
3. Delta-Toleranz definieren (akzeptable Abweichung zwischen Umgebungen)
4. CI-Reproduzierbarkeit als Gate-Voraussetzung fuer Release

**Abhaengigkeit:** F-03 (E2E Smoke muss gruene Tests liefern, bevor
CI-Measurement sinnvoll ist)

---

### F-03 — E2E Smoke in CI [P0]

**Quelle:** Final Status Review §9 "Muss", Deep Review v9 Phase 0-3

**Befund:**
7 Test-Failures auf HEAD (`77ac1652`): 4 aus Dashboard-Row-Index-Drift
(Trust-Tier-Einfuegung verschob Rows um 4), 3 aus Governance-Gate-
Klassifikations-Drift (erwartet soft-warn, jetzt hard-blocking).
Keine vollstaendige TradingView-Binding+Runtime-Reverifikation seit
2026-04-05 (vor Split-Surface-Aenderungen).

**Evidenz:**
- 1999 passed / 7 failed / 4 skipped (4727 collected, SMC scope)
- 4 Failures in `test_smc_bus_v2_semantics.py` — Row-Index-Drift
- 3 Failures in `test_smc_integration_release_gate_scripts.py` —
  Gate-Promotion-Mismatch
- Ursache: NICHT Produkt-Regression, sondern Test-Erwartungs-Drift
  durch 2 juengere Product-Commits

**Betroffene Pfade:**
- `tests/test_smc_bus_v2_semantics.py`
- `tests/test_smc_integration_release_gate_scripts.py`
- `SMC_Dashboard.pine` (Row-Numbering)
- `smc_integration/release_policy.py` (Gate-Promotion)

**Blueprint:**
1. Row-Index-Konstanten in `test_smc_bus_v2_semantics.py` um +4 anpassen
2. Gate-Klassifikation in `test_smc_integration_release_gate_scripts.py`
   von `soft-warn` auf `hard-blocking` aktualisieren
3. TradingView-Preflight-Rerun auf aktuellem HEAD ausfuehren
4. Geschaetzter Aufwand: ~30 Minuten (mechanische Anpassung)

**Abhaengigkeit:** Keine — sofort ausfuehrbar, entblockt F-02 und F-09

---

### F-04 — Provider Failure Semantics [P1]

**Quelle:** Deep Review v6 §B V-5, Deep Review v9 V-7

**Befund:**
Technical-Fallback-Bug (`fetch_technical_tradingview()` rief intern
`terminal_fmp_technicals.fetch_fmp_technicals` auf) wurde behoben.
Provider-Failure-Gruende werden jedoch nicht maschinenlesbar
klassifiziert — nur generisches "stale", nicht spezifische
Fehlerklasse pro Domain.

**Evidenz:**
- Bug in v6 gefixt: TradingView-Fallback war FMP-abhaengig
- Benzinga-Fallback validiert (Deep Review v9 V-7)
- Provider-Status im Dashboard sichtbar (Rows 18-21)
- Fehlende: Strukturierte Fehlerklassen (auth, quota, data-quality,
  unavailable) als maschinenlesbares Feld

**Betroffene Pfade:**
- `smc_integration/service.py`
- `smc_integration/providers/`
- `smc_core/provider_health.py` (falls vorhanden)
- Dashboard Provider-State Rows

**Blueprint:**
1. Enum `ProviderFailureClass` definieren:
   `AUTH | QUOTA | DATA_QUALITY | UNAVAILABLE | TIMEOUT | UNKNOWN`
2. Jeder Provider-Aufruf liefert `(result, failure_class)` Tuple
3. Aggregation in Provider-Health-Gate: `failure_class` Verteilung
4. Dashboard-Anzeige: Failure-Klasse pro Provider (nicht nur "stale/ok")

**Abhaengigkeit:** F-05 (Finnhub-Mismatch nutzt gleiche Failure-Semantik)

---

### F-05 — Finnhub Mismatch [P1]

**Quelle:** Deep Review v6 §B V-3, Measurement Baseline

**Befund:**
NewsAPI.ai-Pfad-Divergenz zwischen Live-News und Library-Refresh nicht
erklaert. Beide Pfade lesen `NEWSAPI_AI_KEY` vom selben Secret, aber
Library-Refresh kann in Auth, Cursor-State, Data-Quality oder
Runtime-Bedingungen vom Live-News-Workflow abweichen.

**Evidenz:**
- Live-News-Pfad: `scripts/fetch_live_news.py`
- Library-Refresh-Pfad: `.github/workflows/smc-library-refresh.yml`
- Gleicher Secret-Key, unterschiedliche Laufzeitbedingungen
- Kein instrumentiertes Failure-Reason-Logging fuer Library-NewsAPI

**Betroffene Pfade:**
- `scripts/fetch_live_news.py`
- `.github/workflows/smc-library-refresh.yml`
- `smc_integration/providers/newsapi_ai.py` (falls vorhanden)

**Blueprint:**
1. Instrumentiertes Failure-Logging fuer Library-NewsAPI-Pfad
2. Vergleichs-Report: Live-News vs. Library-Refresh Output-Schema
3. Divergenz-Alarm: Wenn Live-News gruene und Library-Refresh rote
   Ergebnisse liefert (oder umgekehrt)
4. Dokumentation der erwarteten Unterschiede

**Abhaengigkeit:** F-04 (gemeinsame Provider-Failure-Semantik)

---

### F-06 — Dual Regime Systems [P1]

**Quelle:** Deep Review v9 V-3, Owner Review §E

**Befund:**
Volatility-Regime existiert sowohl in der Library (Backend:
`VOLATILITY_REGIME`, `VOLATILITY_MODEL_SOURCE`) als auch lokal im Pine
(`compute_vol_regime()`). Die Library-Werte werden jetzt im Dashboard
angezeigt, aber die Entscheidungslogik im Core Engine nutzt weiterhin
die lokale Berechnung. Dual-Regime-Risiko: Zwei unterschiedliche
Volatilitaets-Einschaetzungen koennen divergierende Signale erzeugen.

**Evidenz:**
- Backend exportiert: `VOLATILITY_REGIME`, `VOLATILITY_MODEL_SOURCE`,
  `ENSEMBLE_QUALITY_SCORE`, `ENSEMBLE_QUALITY_TIER`
- `SMC_Core_Engine.pine` hat lokale `compute_vol_regime()` Logik
- Dashboard zeigt Library-Werte (seit v9 Update)
- `NO_SHADOW_LOGIC_POLICY.md` existiert als Richtlinie

**Betroffene Pfade:**
- `SMC_Core_Engine.pine` — lokale Volatility-Logik
- `pine/generated/smc_micro_profiles_generated.pine` — Library-Volatility
- `SMC_Dashboard.pine` — Anzeige beider Quellen
- `docs/NO_SHADOW_LOGIC_POLICY.md`

**Blueprint:**
1. Owner-Entscheidung: Library-Volatility als primaere Quelle ODER
   lokale Pine-Logik beibehalten
2. Bei Entscheidung fuer Library-Primaer:
   a. Core Engine auf Library-`VOLATILITY_REGIME` umstellen
   b. Lokale `compute_vol_regime()` als Fallback (nicht Shadow)
   c. Dashboard-Delta-Anzeige: Library vs. Lokal (Uebergangsphase)
3. Bei Entscheidung fuer Lokal-Primaer:
   a. Library-Volatility nur fuer Dashboard-Diagnostik nutzen
   b. Dokumentieren, warum lokale Logik bevorzugt wird
4. Shadow-Logic-Policy durchsetzen: Keine Dual-Signale in Produktion

**Abhaengigkeit:** Keine — erfordert Owner-Entscheidung, nicht Code

---

### F-07 — Base Generator Complexity [P2]

**Quelle:** Deep Review v5 V-1/K-3, Deep Review v9 V-5

**Befund:**
Generator getestet (69/69 Long-Dip-Regressionstests gruen), aber
nur fuer 6 Symbole x 2 Timeframes validiert. Vollstaendige
Referenzmatrix (12 Symbole x 4 Timeframes) nicht bestaetigt.
Event-Coverage an Randfaellen (sparse Events, sparse Timeframes)
nicht untersucht.

**Evidenz:**
- Baseline: AAPL, MSFT, AMZN, JPM, JNJ, XOM x 15m, 1H
- Fehlend: GOOG, META, NVDA, TSLA, UNH, V x 5m, 4H
- 17-25 Events/Pair — ueber Floor, aber unter Soft-Warn-Schwelle
- Kein Test fuer Symbole mit strukturell wenigen Events

**Betroffene Pfade:**
- `scripts/run_smc_measurement_benchmark.py`
- `smc_core/scoring.py`
- `smc_core/benchmark.py`
- `artifacts/ci/measurement_benchmark/`

**Blueprint:**
1. Run #2 (≤ 7 Tage): Gleiche 6 Symbole x 2 TFs — Regressions-Baseline
2. Run #3 (≤ 14 Tage): Expansion auf 12 Symbole x 4 TFs
3. Edge-Case-Report: Symbole mit <10 Events/Pair identifizieren
4. Generator-Stress-Test: Synthetische Randfaelle (leere Bars,
   lueckenhafte Zeitreihen)

**Abhaengigkeit:** F-03 (grüne Tests), F-14 (Quality-Floor-Kalibrierung)

---

### F-08 — Scripts-to-Integration Layer Violation [P1]

**Quelle:** Deep Review v9 V-4, Deep Review v5 V-4

**Befund:**
Scripts und Integration-Layer sind eng gekoppelt. `bias_merge.py` und
`benchmark.py` werden direkt in `smc_integration/service.py` und
`smc_integration/measurement_evidence.py` importiert. Keine saubere
Trennung zwischen internen und externen Interfaces.

**Evidenz:**
- `smc_integration/service.py` importiert `bias_merge`, `benchmark`
- `smc_integration/measurement_evidence.py` importiert `benchmark`
- Produktions-Scripts importieren aus `smc_core/` direkt
- Keine dokumentierte Public-vs-Private API-Grenze

**Betroffene Pfade:**
- `smc_integration/service.py`
- `smc_integration/measurement_evidence.py`
- `smc_core/bias_merge.py`
- `smc_core/benchmark.py`

**Blueprint:**
1. API-Contract-Layer definieren: `smc_core/__init__.py` als Public API
2. Integration-Layer darf nur Public API importieren
3. Scripts duerfen `smc_core` Internal nicht direkt importieren
4. Bestehende Imports durch Contract-Adapter ersetzen
5. Linting-Regel: `import smc_core.*` in `smc_integration/` nur via
   Public API erlaubt

**Abhaengigkeit:** Keine — rein architektonische Bereinigung

---

### F-09 — Release-Gates Softness [P0]

**Quelle:** Owner Review §I Decision 4, Final Status Review §7, Measurement Baseline §7

**Befund:**
Mehrere Gates sind bewusst soft, um Bootstrap-Deadlock zu vermeiden
(0 Events → kein Publish → keine History → kein Gate). Soft-Warn-
Schwellenwerte werden nicht konsistent durchgesetzt. Kein codifizierter
Pfad zur Graduation von soft zu hard.

**Evidenz:**
- `MEASUREMENT_EVENT_COVERAGE_LOW` ausgeschlossen (Bootstrap-Deadlock)
- Soft-Warn: Brier ≤ 0.30, Event-Coverage ≥ 0.50 (nicht hard)
- Graduation geplant nach Run #3, aber nicht in Code codifiziert
- `min_history_runs = 2` fuer Regression, `3` fuer Calibration-Promotion

**Betroffene Pfade:**
- `smc_integration/release_policy.py`
- `scripts/run_smc_release_gates.py`
- `artifacts/ci/smc_release_gates_baseline_report.json`

**Blueprint:**
1. Graduation-Matrix in `release_policy.py`:
   ```
   GATE_GRADUATION = {
       "EVENT_COVERAGE_LOW": {
           "promote_after_runs": 3,
           "promote_condition": "coverage > 0.50 in 2/3 runs"
       },
       "ECE_REGRESSION": {
           "promote_after_runs": 5,
           "promote_condition": "regression < 0.08 in 4/5 runs"
       }
   }
   ```
2. Automatische Promotion bei Erreichen der Bedingung
3. Alarm bei Soft-Gate-Verletzung (nicht nur Log, sondern CI-Warning)
4. Rollback-Policy: Hard-Gate kann auf Soft zurueckgestuft werden
   mit dokumentierter Begruendung

**Abhaengigkeit:** F-01 (Governance-Framework muss stehen), F-14
(Quality-Floor muss kalibriert sein)

---

### F-10 — News/Sentiment Underuse [P2]

**Quelle:** Deep Review v9 V-5, Owner Review §E

**Befund:**
News-Polarity und Snippet-basiertes Scoring existieren in Tests,
werden aber in der Mainline-Pine-Surface nicht prominent genutzt.
`NEWS_BULLISH`/`NEWS_BEARISH` Diagnostik existiert, Dashboard-
Sichtbarkeit ist jedoch gering im Vergleich zu anderen Signalen.

**Evidenz:**
- `test_smc_news_scorer.py` — Tests gruene
- `NEWS_BULLISH`, `NEWS_BEARISH` in BUS-Payload
- Dashboard zeigt News-Felder, aber nicht als primaere Entscheidungs-
  unterstuetzung
- Owner Review fordert: "Visible moat > Internal moat"

**Betroffene Pfade:**
- `SMC_Dashboard.pine` — News-Anzeige-Rows
- `smc_core/news_scorer.py`
- `smc_integration/providers/` — News-Provider
- `pine/generated/smc_micro_profiles_generated.pine`

**Blueprint:**
1. Dashboard-Redesign: News-Sentiment als eigene prominente Section
2. Ampel-Indikator: News-Bias (Bullish/Bearish/Neutral) visuell hervor
3. Core Engine: News-Bias als optionaler Filter fuer Signal-Qualitaet
4. Erst nach Owner-Entscheidung (F-13): Umfang der News-Integration
   festlegen

**Abhaengigkeit:** F-13 (Product Identity bestimmt News-Gewichtung)

---

### F-11 — Staleness Modeling [P2]

**Quelle:** Measurement Baseline §3, Deep Review v6 V-1, Final Status Review §7

**Befund:**
Staleness-Window (7 Tage) und Monitoring-Kadenz definiert, aber
Rolling-Window-Enforcement nicht implementiert. Einzelner Baseline-Run
reicht nicht fuer Regressions-Erkennung (min. 2 Runs).

**Evidenz:**
- 7-Tage-Staleness-Window definiert
- 14-Tage-Evidence-Lookback
- Geplant: Run #2 ≤ 7 Tage, Run #3 ≤ 14 Tage
- Kein automatisierter Staleness-Alarm in CI
- Kein Rollback-Policy bei Degradation

**Betroffene Pfade:**
- `smc_integration/release_policy.py` — Staleness-Konfiguration
- `scripts/run_smc_release_gates.py` — Gate-Runner
- `.github/workflows/smc-deeper-integration-gates.yml` — Nightly

**Blueprint:**
1. Staleness-Check als CI-Step: Letzter Run > 7 Tage → Warning
2. Letzter Run > 14 Tage → Hard-Block (kein Release)
3. Rolling-Window: Letzte 5 Runs als Regressions-Vergleichsbasis
4. Automatisierter Alarm (GitHub Issue oder Slack) bei Staleness
5. Rollback-Policy: Bei 2 aufeinanderfolgenden Regressions-Runs
   → Release-Gate blockiert

**Abhaengigkeit:** F-07 (Base Generator muss stabile Runs liefern)

---

### F-12 — TradingView Publish Drift [P1]

**Quelle:** Final Status Review §6, Deep Review v9 V-6, Owner Review §G

**Befund:**
5 von 9 Libraries erfordern manuellen TradingView-Publish. Kein
automatisiertes Publish-Script existiert fuer diese. Code-Aenderungen
erfordern manuellen Re-Publish-Workflow, was Release-Velocity
reduziert und Drift-Risiko erhoehe.

**Evidenz:**
- Manual-Publish: `smc_core_types`, `smc_draw`, `smc_utils`,
  `smc_profile_engine`, `smc_context_resolvers`
- Auto-Publish: `smc_lifecycle_private`, `smc_bus_private`,
  `smc_observability_private`, `smc_micro_profiles_generated`
- `automation/tradingview/lib/tv_shared.ts` hat Modal-Recovery
- `.github/workflows/smc-library-refresh.yml` hat Retry-Logik

**Betroffene Pfade:**
- `automation/tradingview/`
- `.github/workflows/smc-library-refresh.yml`
- `SMC++/` — 5 Manual-Publish Libraries

**Blueprint:**
1. Publish-Script fuer Manual-Publish Libraries erstellen
2. Idempotenter Publish-Chain: Script erkennt "bereits aktuell" und
   ueberspringt
3. Chrome DevTools Protocol-basierte Automation (analog existierender
   `tv_shared.ts`)
4. Owner Review fordert: "Publish/Recovery chain toward idempotency"
5. Interim: Manueller Publish-Checklist als CI-Reminder bei
   Aenderungen an `SMC++/`

**Abhaengigkeit:** Keine — kann parallel zu allen anderen Findings
bearbeitet werden

---

### F-13 — Product Identity Breadth [P2]

**Quelle:** Owner Review §I Decision 1, §B Issue 2, §C Issue 1

**Befund:**
Produktidentitaet unklar: Long-spezialisiertes Decision-System ODER
breites SMC-Operating-System? Core Engine ist faktisch staerker auf
Long-Dip-Spezialisierung ausgelegt, als die generische SMC-Story
suggeriert. Wenn externe Breiten-Messaging der internen Spezialisierung
widerspricht, entsteht Trust-Risiko.

**Evidenz:**
- Core Engine: Long-Dip-Detection als Primaer-Feature
- Marketing/Docs: "Smart Money Concepts" suggeriert breiteres Spektrum
- Owner Review: "Definitively decide: Long-specialized decision system
  OR broader SMC operating system?"
- 69/69 Long-Dip-Regressionstests vs. 0 explizite Short/Neutral-Tests

**Betroffene Pfade:**
- `docs/SMC_PRODUCT_IDENTITY.md`
- `docs/smc-lite-pro-product-cut.md`
- `docs/SMC_GETTING_STARTED.md`
- Marketing/External Surfaces

**Blueprint:**
1. Owner-Entscheidung erzwingen (30-Tage-Deadline):
   - Option A: Long-Dip-Spezialist (klare Nische, hohe Glaubwuerdigkeit)
   - Option B: Breites SMC-System (erfordert Feature-Expansion)
2. Product-Cut-Manifest aktualisieren (`smc_bus_manifest.py`)
3. Dokumentation und Onboarding an Entscheidung anpassen
4. Hero-Surface definieren als unbestrittenes Produkt-Zentrum

**Abhaengigkeit:** Keine — strategische Entscheidung, kein Code

---

### F-14 — Quality-Floor Calibration [P1]

**Quelle:** Measurement Baseline §5-7, Final Status Review §7

**Befund:**
Quality-Schwellenwerte definiert, aber Einzellauf-Baseline
unzureichend fuer Kalibrierungs-Konfidenz. Kontextuelle
Kalibrations-Promotion erfordert `min_history_runs: 3` und
`min_recommended_run_ratio: 0.67`. Aktuelle Metriken komfortabel
unter Schwellenwerten (Brier 2.2–3.4x unter Ceiling, ECE 1.6–8.5x),
aber Stabilitaet ueber Zeit nicht bewiesen.

**Evidenz:**
- Calibrated Brier: 0.1682 (Mean) — Schwellenwert 0.60
- Calibrated ECE: 0.1319 (Mean) — Schwellenwert 0.30
- Hit Rate: 0.7585 (Mean)
- 258 Events total (4 Familien: BOS 46, FVG 96, OB 46, SWEEP 70)
- Einzellauf — keine Regressions-Detection moeglich

**Betroffene Pfade:**
- `smc_integration/release_policy.py` — Schwellenwerte
- `smc_core/scoring.py` — Scoring-Logik
- `smc_core/ensemble_quality.py` — Ensemble-Qualitaet
- `artifacts/ci/smc_release_gates_baseline_report.json`

**Blueprint:**
1. Run #2 (≤ 7 Tage): Regressions-Baseline aktivieren
2. Run #3 (≤ 14 Tage): Kontextuelle Kalibrations-Promotion
3. Schwellenwert-Review nach Run #3:
   - Brier-Ceiling: 0.60 → ggf. auf 0.40 verschaerfen
   - ECE-Ceiling: 0.30 → ggf. auf 0.20 verschaerfen
4. Threshold-Drift-Detection: Alarm bei >20% Verschlechterung
   gegenueber Median der letzten 3 Runs
5. Staendige Metrik-Historie in `artifacts/ci/measurement_history/`

**Abhaengigkeit:** F-03 (Tests muessen gruen sein), F-07 (Generator
muss stabil laufen)

---

## 5-Phasen-Umsetzungsplan

### Phase 1 — Sofort (Tag 1-3): Test-Reparatur und CI-Grundlage

| Aufgabe | Finding | Aufwand | Blocker |
|---------|---------|---------|---------|
| Test-Failures fixen (Row-Index, Gate-Klassifikation) | F-03 | ~30 Min | Keiner |
| TradingView-Preflight-Rerun | F-03 | ~20 Min | Keiner |
| CI-Measurement-Run triggern | F-02 | ~15 Min | F-03 |

**Exit-Kriterium:** 0 Test-Failures auf HEAD, CI-Measurement-Run gruen

### Phase 2 — Kurzfristig (Tag 4-14): Governance-Haertung

| Aufgabe | Finding | Aufwand | Blocker |
|---------|---------|---------|---------|
| Graduation-Matrix in `release_policy.py` | F-09, F-01 | 2-3 Std | F-03 |
| Provider-Failure-Enum definieren | F-04 | 1-2 Std | Keiner |
| Staleness-Check als CI-Step | F-11 | 1-2 Std | F-03 |
| Measurement Run #2 | F-14, F-07 | ~20 Min | F-02 |

**Exit-Kriterium:** Graduation-Matrix codifiziert, Provider-Failures
maschinenlesbar, Run #2 abgeschlossen

### Phase 3 — Mittelfristig (Tag 15-30): Provider und Publish

| Aufgabe | Finding | Aufwand | Blocker |
|---------|---------|---------|---------|
| NewsAPI-Pfad-Divergenz instrumentieren | F-05 | 2-3 Std | F-04 |
| Publish-Script fuer Manual Libraries | F-12 | 4-6 Std | Keiner |
| Owner-Entscheidung Dual-Regime | F-06 | — | Keiner |
| Measurement Run #3 + Kalibrierung | F-14 | ~30 Min | Run #2 |
| Referenzmatrix-Expansion (12x4) | F-07 | 1-2 Std | Run #3 |

**Exit-Kriterium:** Alle Provider instrumentiert, Publish automatisiert,
Run #3 abgeschlossen, Kalibrations-Promotion evaluiert

### Phase 4 — Langfristig (Tag 30-60): Architektur und Produkt

| Aufgabe | Finding | Aufwand | Blocker |
|---------|---------|---------|---------|
| Scripts-to-Integration API-Contract | F-08 | 4-6 Std | Keiner |
| News-Sentiment Dashboard-Integration | F-10 | 3-4 Std | F-13 |
| Owner-Entscheidung Product Identity | F-13 | — | Keiner |
| Dual-Regime-Umsetzung (nach Entscheidung) | F-06 | 2-4 Std | F-06 Owner |

**Exit-Kriterium:** API-Grenzen definiert, News prominent im Dashboard,
Produkt-Positionierung entschieden

### Phase 5 — Konsolidierung (Tag 60-90): Haertung und Sichtbarkeit

| Aufgabe | Finding | Aufwand | Blocker |
|---------|---------|---------|---------|
| Hard-Gate-Promotion (ECE_REGRESSION, EVENT_COVERAGE) | F-01, F-09 | 1-2 Std | Phase 2-3 |
| Schwellenwert-Verschaerfung nach Kalibration | F-14 | 1-2 Std | Run #3+ |
| Rolling-Window Staleness Enforcement | F-11 | 2-3 Std | Phase 2 |
| Product Identity in Docs/Marketing umsetzen | F-13 | 2-3 Std | Phase 4 |

**Exit-Kriterium:** Alle Gates hart (wo angemessen), Metriken kalibriert,
Produktidentitaet konsistent

---

## Abhaengigkeitskette (kritischer Pfad)

```
F-03 (E2E Smoke) ──────┬── F-02 (Evidence CI)
                        │
                        ├── F-09 (Release-Gates) ── F-01 (Governance)
                        │
                        └── F-14 (Quality-Floor) ── F-01 (Governance)
                                    │
                                    └── F-07 (Generator) ── F-11 (Staleness)

F-04 (Provider Failure) ── F-05 (Finnhub Mismatch)

F-13 (Product Identity) ── F-10 (News/Sentiment)
                        ── F-06 (Dual Regime)

F-08 (Scripts-Integration) — unabhaengig
F-12 (TradingView Publish) — unabhaengig
```

**Kritischer Pfad:** F-03 → F-02 → F-14 → F-01 (Governance vollstaendig)

---

## Appendix: Quellen-Referenz

| Dokument | Pfad | Datum |
|----------|------|-------|
| Deep Review v9 Action Plan | `docs/smc_deep_review_v9_verified_action_plan.md` | 2026-04-13 |
| Owner Review | `docs/smc-owner-review-2026-04-14.md` | 2026-04-14 |
| Final Status Review | `docs/smc_final_status_review_2026-04-16.md` | 2026-04-16 |
| Measurement Baseline | `docs/smc_measurement_baseline_2026-04-17.md` | 2026-04-17 |
| Deep Review v5 Action Plan | `docs/smc_deep_review_v5_verified_action_plan.md` | 2026-04-08 |
| Deep Review v6 Action Plan | `docs/smc_deep_review_v6_verified_action_plan.md` | 2026-04-12 |
