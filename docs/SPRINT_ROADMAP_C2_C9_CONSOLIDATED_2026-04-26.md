# Sprint-Roadmap C2-C9 — Konsolidierte Master-Übersicht

**Datum:** 2026-04-26
**Owner:** Steffen Preuss
**Zweck:** Single-Source-of-Truth für Sprint-Reihenfolge, Abhängigkeiten, kritischen Pfad und Track-Record-Gate-Erfüllung.

## Strategische Leitlinie (verbatim)

> "Wenn die SMC-Calibration-Track-Record nicht eindeutig profitable Setups zeigt — dann habe ich nichts zu verkaufen. Solange das nicht klar und eindeutig ist, sind alle anderen Schritte sinnlos."

Alle Sprints C2-C9 dienen genau diesem Ziel: einen **statistisch belastbaren, live-validierten, automatisch überwachten Track-Record** zu produzieren, der extern verkaufbar ist.

## Sprint-Übersicht

| Sprint | Inhalt | Dauer (Speed-Stack) | Status | Plan |
|---|---|---|---|---|
| C1 | Outcome-Tracking-Pipeline | 7-10 Werktage | Plan fertig (vorige Session) | [SPRINT_PLAN_C1_OUTCOME_TRACKING_2026-04-25.md](sandbox:/home/user/workspace/SPRINT_PLAN_C1_OUTCOME_TRACKING_2026-04-25.md) |
| C2 | Walk-Forward-Pipeline | 7-10 Werktage | Plan in PR #243 | [SPRINT_PLAN_C2_WALK_FORWARD_2026-04-26.md](sandbox:/home/user/workspace/SPRINT_PLAN_C2_WALK_FORWARD_2026-04-26.md) |
| C3 | Bootstrap-CI | 3-6 Werktage | Plan in PR #243 | [SPRINT_PLAN_C3_BOOTSTRAP_CI_2026-04-26.md](sandbox:/home/user/workspace/SPRINT_PLAN_C3_BOOTSTRAP_CI_2026-04-26.md) |
| C4 | Permutation-Test | 2-5 Werktage | Plan in PR #243 | [SPRINT_PLAN_C4_PERMUTATION_TEST_2026-04-26.md](sandbox:/home/user/workspace/SPRINT_PLAN_C4_PERMUTATION_TEST_2026-04-26.md) |
| C5 | Regime-Stratifikation | 4-7 Werktage | Plan in PR #245 | [SPRINT_PLAN_C5_REGIME_STRATIFICATION_2026-04-26.md](sandbox:/home/user/workspace/SPRINT_PLAN_C5_REGIME_STRATIFICATION_2026-04-26.md) |
| C6 | Probabilistic-Sharpe + MinTRL | 3-5 Werktage | Plan in PR #245 | [SPRINT_PLAN_C6_PSR_MINTRL_2026-04-26.md](sandbox:/home/user/workspace/SPRINT_PLAN_C6_PSR_MINTRL_2026-04-26.md) |
| C7 | Dashboard-Frontend | 8-12 Werktage | Plan in PR #249 | [SPRINT_PLAN_C7_DASHBOARD_2026-04-26.md](sandbox:/home/user/workspace/SPRINT_PLAN_C7_DASHBOARD_2026-04-26.md) |
| C8 | Live-Incubation | 5-8 Werktage Setup + 3-6 Monate Wartezeit | Plan in PR #249 | [SPRINT_PLAN_C8_LIVE_INCUBATION_2026-04-26.md](sandbox:/home/user/workspace/SPRINT_PLAN_C8_LIVE_INCUBATION_2026-04-26.md) |
| C9 | Drift-Alert + Anomalie-Monitoring | 3-5 Werktage | Plan fertig | [SPRINT_PLAN_C9_DRIFT_ALERT_2026-04-26.md](sandbox:/home/user/workspace/SPRINT_PLAN_C9_DRIFT_ALERT_2026-04-26.md) |

## Abhängigkeits-Graph

```
                                        ┌─→ C5 (Regime-Stratifikation) ─┐
                                        │                                │
        ┌─→ C2 (Walk-Forward) ─┬──→ C3 (Bootstrap-CI) ─→ C6 (PSR/MinTRL)─┤
        │                     │                                          │
C1 ─────┤                     └──→ C4 (Permutation) ────────────────────┤
        │                                                                │
        └─→ C9 (Drift-Alert, Setup nutzt C1-Backtest) ──────┐            │
                                                            │            ↓
                                                            └──→ C7 (Dashboard)
                                                                          │
                                                                          ↓
                                                                  C8 (Live-Incubation)
                                                                          │
                                                                          ↓
                                                                  C9 (Drift-Alert, Live-Modus)
```

**Kritischer Pfad** (sequenziell, nicht parallelisierbar):

```
C1 → C2 → {C3, C4} → C7 → C8-Setup → C8-Wartezeit (3-6 Monate)
```

**Parallel zu kritischem Pfad** möglich:

- **C5** (braucht nur C1) — kann ab Tag 1 parallel
- **C6** (braucht C2+C3) — startet sobald C3 fertig
- **C9-Setup** (braucht C1-Backtest-Stream) — kann parallel zu C7 laufen, geht aber erst live nach C8

## Total-Aufwand-Schätzung

### Entwicklungszeit (sequenziell auf kritischem Pfad)

| Phase | Werktage Min | Werktage Max | Notiz |
|---|---|---|---|
| C1 | 7 | 10 | Outcome-Tracking — Voraussetzung für alles |
| C2 | 7 | 10 | Walk-Forward — Voraussetzung für C3, C6 |
| C3 + C4 (parallel) | 3 | 6 | Bootstrap parallel zu Permutation |
| C5 (parallel zu C2-C4) | 0 | 0 | Auf kritischem Pfad nicht relevant, wenn parallel ausgeführt |
| C6 | 3 | 5 | Nach C2+C3 |
| C7 | 8 | 12 | Dashboard nach C2-C6 |
| C8 Setup | 5 | 8 | Live-Pipeline-Build |
| C9 Setup | 0 | 0 | Parallel zu C7/C8, +0 wenn nicht auf kritischem Pfad |
| **Build-Total (kritischer Pfad)** | **33** | **51** | Werktage |

Bei **5 Werktagen/Woche** mit Speed-Stack: **6,5-10 Wochen** Build-Zeit.
Ohne Speed-Stack realistisch: **+30-50%** = 9-15 Wochen.

### Inkubationszeit (zwingend, nicht abkürzbar)

| Phase | Dauer | Notiz |
|---|---|---|
| C8 Phase A (IBKR Paper) | 4 Wochen | 100% Size, mind. 20 Paper-Trades |
| C8 Phase B (IBKR Live small) | 12-24 Wochen | 10-25% Size, mind. 30 Live-Trades |
| **Inkubations-Total** | **16-28 Wochen** | = 4-7 Monate |

[QuantVPS](https://www.quantvps.com/blog/paper-trading-simulators) und [Reddit r/algotrading](https://www.reddit.com/r/algotrading/comments/uls93l/how_do_you_determine_if_a_you_are_going_deploy/) bestätigen die 3-Monate-Mindest-Inkubation einstimmig — **Verkürzungsversuch = invalide Stichprobe**.

### Time-to-Verkaufbarkeit

**Realistisches Best-Case-Szenario**:

```
6,5 Wochen Build + 16 Wochen Inkubation = 22,5 Wochen ≈ 5,2 Monate
```

**Realistisches Realistic-Case-Szenario**:

```
9 Wochen Build + 20 Wochen Inkubation = 29 Wochen ≈ 6,7 Monate
```

**Worst-Case** (ohne Speed-Stack, mit Phase-A-Wiederholung):

```
14 Wochen Build + 28 Wochen Inkubation = 42 Wochen ≈ 9,7 Monate
```

## Track-Record-Gate-Erfüllungs-Matrix

| Mindestanforderung | Mindestwert | Liefernder Sprint | Status nach Sprint |
|---|---|---|---|
| OOS-Trades n | ≥100, ideal ≥200 | C1 + C2 | C2-Fertigstellung |
| Win-Rate | ≥55% (R/R=1) oder ≥45% (R/R≥1.5) | C1 | C1-Fertigstellung |
| Sharpe annualisiert | ≥1.0 | C2 | C2-Fertigstellung |
| Bootstrap-95%-CI Untergrenze | >0.3 | C3 | C3-Fertigstellung |
| Max DD | <15% | C2 | C2-Fertigstellung |
| FDR-Rate | <10% | C4 | C4-Fertigstellung |
| Walk-Forward-Efficiency | >50% | C2 | C2-Fertigstellung |
| Permutation-p | <0.05 | C4 | C4-Fertigstellung |
| Per-Regime Hit-Rate-Streuung | <20% (max-min) | C5 | C5-Fertigstellung |
| **PSR(SR\*=0)** | **≥0.95** | **C6** | **C6-Fertigstellung** |
| **MinTRL(SR\*=0)** | **≤verfügbare n** | **C6** | **C6-Fertigstellung** |
| Track-Record-Gate-Sichtbarkeit | 3-Sekunden-Lesbarkeit | C7 | C7-Fertigstellung |
| **Live-Inkubations-Dauer** | **≥3 Monate, ideal 6** | **C8** | **C8-Phase-B-Pass** |
| **Live-Trades** | **≥30** | **C8** | **C8-Phase-B-Pass** |
| **Live-Sharpe ÷ Backtest-Sharpe** | **≥0.50** | **C8** | **C8-Phase-B-Pass** |
| Drift-Detection automatisch | Cron-Job aktiv | C9 | C9-Fertigstellung |
| Auto-Halt bei kritischem Drift | Hook ausgelöst | C9 | C9-Fertigstellung |

**Verkaufbarkeits-Schwelle**: alle 17 Mindestanforderungen erfüllt **AND** mindestens 1 SMC-Variante mit Status "green" **AND** C9-Drift-Verdict "stable" über letzte 14 Tage.

## Empfohlene Ausführungs-Reihenfolge

### Phase 1 (Wochen 1-2): C1-Reload + Foundation

1. C1-Bestätigung + Daten-Lock
2. C2-T1 (Inventur) parallel zu C5-T1 (Inventur) parallel zu C9-T1 (Inventur)

### Phase 2 (Wochen 2-4): C2-Build + Parallel-Spuren

1. C2-T2 bis T7 (Walk-Forward-Pipeline)
2. **Parallel**: C5-T2 bis T6 (Regime-Stratifikation auf C1-Daten)
3. **Parallel**: C9-T2 (Drift-Detektoren auf C1-Backtest-Stream als Validation)

### Phase 3 (Wochen 4-5): C3 + C4 + C6-Vorbereitung

1. C3-T1 bis T6 (Bootstrap-CI auf C2-Output)
2. **Parallel**: C4-T1 bis T6 (Permutation-Test auf C2-Output)
3. C6-T1 (Inventur — nur lesen)

### Phase 4 (Wochen 5-7): C6 + C7-Vorbereitung

1. C6-T2 bis T8 (PSR + MinTRL)
2. C7-T1 (Schema-Lock — alle Sprint-Outputs sind jetzt definiert)

### Phase 5 (Wochen 6-9): C7-Dashboard

1. C7-T2 bis T9 (Dashboard-Build)
2. C9-T3 bis T8 (Drift-Cron geht live, vorerst auf Backtest-Stream)

### Phase 6 (Wochen 9-11): C8-Setup + Phase A

1. C8-T1 bis T7 (Live-Pipeline-Build)
2. **Phase A startet** — IBKR Paper-Account, 4 Wochen

### Phase 7 (Wochen 11-15): C8-Phase A Inkubation

1. Tägliche C9-Cron-Checks
2. Wöchentliche manuelle Reviews
3. Bei Phase-A-Pass-Kriterien: Phase-B-Switch-Decision

### Phase 8 (Wochen 15-27+): C8-Phase B Inkubation

1. IBKR Live-Account, 10-25% Size
2. C9-Cron in Live-Modus
3. Mindestens 30 Live-Trades, 12-24 Wochen
4. Bei Phase-B-Pass: **Track-Record extern verkaufbar**

## Speed-Hebel-Konsolidierung

Aus den 8 Sprint-Plänen extrahiert, alphabetisch nach Hebel:

| Hebel | Anwendung | Status |
|---|---|---|
| AI-Repo-Tool (Cursor/Claude Code) | Skeleton-Generation für Detector-Klassen, Test-Pins, Streamlit-Tabs | Empfohlen ab Tag 1 jedes Sprints |
| Inventur Tag 1 jedes Sprints | Vermeidet Greenfield-Doppelarbeit | ✅ Pflicht-Disziplin in allen 8 Plänen |
| `joblib.Parallel` | Bootstrap, Permutation embarrassingly parallel | C3, C4 |
| `pytest-xdist` | Test-Parallelisierung | ✅ schon in `requirements.txt` |
| Reuse `_normal_cdf` (`run_ab_comparison.py:238`) | KS-Test, PSR ohne scipy-Hardabhängigkeit | C6, C9 |
| Reuse `benjamini_hochberg` (`run_ab_comparison.py:181`) | FDR-Korrektur | C3, C4 |
| Reuse `compute_walk_forward_cv_hr` (`smc_zone_priority_calibration.py:167-252`) | Walk-Forward-Skeleton | C2 |
| Reuse `dispatch_alerts` + Throttle-Logik (`open_prep/alerts.py`) | Multi-Channel Alerts | C9 |
| Reuse `execute_ibkr_watchlist.py` (1118 Zeilen) | Live-Order-Pipeline | C8 |
| Reuse `regime.py` (open_prep:26-298) | RISK_ON/OFF, TRENDING/RANGING | C5 |
| Reuse `streamlit_terminal.py` + `terminal_tabs/` | Dashboard-Stack | C7 |
| Reuse Cron-Pattern (`g23-ab-watchdog.yml`) | GitHub-Actions-Skeleton | C9 |
| Reuse `outcome_backfill.py:211` | Live→Calibration-Feedback | C8 |
| Reuse `emit_public_calibration_report.build_public_report` | Aggregator-Pattern | C7 |
| 2-Iterations-Limit pro Task | Vermeidet Over-Engineering | ✅ Pflicht in allen 8 Plänen |
| Sprint-Templates wiederverwenden | Reduziert Plan-Schreib-Zeit | ✅ Etabliert ab C2 |

## Anti-Hebel (was nicht beschleunigt werden kann)

| Anti-Hebel | Warum | Alternative |
|---|---|---|
| Live-Inkubation kürzer als 3 Monate | Stichprobe statistisch invalide ([Roguequant](https://roguequant.substack.com/p/the-75-win-rate-strategy-i-found), [Reddit](https://www.reddit.com/r/algotrading/comments/uls93l/how_do_you_determine_if_a_you_are_going_deploy/)) | Geduld; Dashboards intern fertig, externes Marketing erst danach |
| Position-Size live >25% in Phase B | Real-Geld-Risiko ohne Validation | Phase-A→B-Gate manuell signieren |
| Cloud-Migration vor Track-Record | Verschwendet Zeit, ändert nichts an Statistik | Cloud-Migration nach C8.B-Pass, nicht davor |
| Multi-Modell-Setup vor C8 | Multipliziert Hyperparameter-Sweep, erhöht DSR-Inflation in C6 | Erst 1 Variant durch C8 bringen, dann Skalieren |
| Dashboard-Polishing vor C8 | UX-Politur ohne Daten ist Verschwendung | Funktional in C7, Politur nach C8.B |

## Out-of-Scope der Sprint-Reihe (späterer Roadmap-Slot)

- Cloud-Migration (Container Apps Jobs) — geplant nach C8.B-Pass
- Multi-Strategie-Portfolio-Korrelations-Drift
- ML-basierte Anomalie-Detection (Isolation Forest, Autoencoder)
- Crypto-Exchanges via ccxt
- Auto-Sizing via Kelly-Kriterium
- Customer-Facing Marketing-Page
- Multi-User-Auth + Login

Diese kommen explizit **nach** Track-Record-Gate-Pass, nicht davor.

## Quellen (zentral, für die Sprint-Reihe)

### Statistische Methoden

- [Bailey & Lopez de Prado (2012) — Sharpe Ratio Efficient Frontier](http://boston.qwafafew.org/wp-content/uploads/sites/4/2017/01/Lopez_de_Prado_Sharpe.pdf)
- [Bailey & Lopez de Prado (2014) — Deflated Sharpe](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)
- [Wikipedia — Deflated Sharpe](https://en.wikipedia.org/wiki/Deflated_Sharpe_ratio)
- [Politis-Romano (1994) — Stationary Bootstrap](https://en.wikipedia.org/wiki/Bootstrapping_(statistics))
- [Stefan Jansen ML4T — Multiple Testing](https://stefan-jansen.github.io/machine-learning-for-trading/08_ml4t_workflow/01_multiple_testing/)
- [White (2000) — Reality Check](https://en.wikipedia.org/wiki/White%27s_reality_check)

### Live-Inkubation + Broker

- [QuantVPS — Paper-to-Live (März 2026)](https://www.quantvps.com/blog/paper-trading-simulators)
- [Alpaca — Paper vs Live Data-Backed (August 2025)](https://alpaca.markets/learn/paper-trading-vs-live-trading-a-data-backed-guide-on-when-to-start-trading-real-money)
- [QuantInsti — IBKR-Bot-Guide (März 2026)](https://www.quantinsti.com/articles/build-trading-bot-interactive-brokers-python-chatgpt/)
- [PickMyTrade — IBKR Automated Trading 2026](https://blog.pickmytrade.io/ibkr-automated-trading-system-guide-2026/)
- [Reddit r/algotrading — Live-Deploy-Kriterien](https://www.reddit.com/r/algotrading/comments/uls93l/how_do_you_determine_if_a_you_are_going_deploy/)
- [Roguequant — 75% Win-Rate (August 2025)](https://roguequant.substack.com/p/the-75-win-rate-strategy-i-found)

### Drift-Detection

- [OneUptime — Concept-Drift-Detection (Januar 2026)](https://oneuptime.com/blog/post/2026-01-30-concept-drift-detection/view)
- [MetricGate — Concept-Drift-Monitoring (April 2026)](https://metricgate.com/blogs/concept-drift-model-monitoring/)
- [Agility at Scale — AI-Drift-Monitoring (März 2026)](https://agility-at-scale.com/ai/generative/continuous-evaluation-and-drift-monitoring/)
- [AI Infrastructure Alliance — 8 Drift-Methoden](https://ai-infrastructure.org/8-concept-drift-detection-methods/)

### Dashboard-Stack

- [Streamlit Caching `cache_data` vs `cache_resource`](https://docs.kanaries.net/topics/Streamlit/streamlit-caching)
- [Reflex — Streamlit-vs-Dash (April 2026)](https://reflex.dev/blog/streamlit-vs-dash-python-dashboards/)

## Anti-Halluzinations-Pin

Alle in dieser Roadmap referenzierten Pfade, Zeilennummern, Symbole sind via `grep` und `read` im Repo `skippALGO/skipp-algo` belegt. Bei jeder Änderung des Repos sind die Referenzen neu zu verifizieren.

Letzte Verifikation: 2026-04-26 in `/tmp/skipp-review` auf `main`-Branch nach `git pull`.

## Extension scope: C10–C12 (post-2026-04-26 batch)

Diese Roadmap ist auf C2-C9 konsolidiert. Die folgenden Sprints
erweitern den Scope und sind in eigenen Plan-Dokumenten gepinnt:

| Sprint | Status | Plan-Dokument |
|---|---|---|
| **C10** — ML-Layer (XGBoost / LightGBM trainer) | scaffolded (schema-pin only); full sprint deferred | `docs/SPRINT_PLAN_C10_ML_LAYER_2026-04-26.md` (im PR #293) |
| **C11** — *reserviert / übersprungen* | nicht im aktuellen Plan; Nummer reserviert um die externe Sprint-Nummerierung stabil zu halten | — |
| **C12** — RL-Execution (trigger gate stub) | scaffolded (trigger-stub + Phase-B-anchor only); full sprint blockiert auf erfolgreiche C8-Phase-B-Inkubation | `docs/SPRINT_PLAN_C12_RL_EXECUTION_2026-04-26.md` (im PR #293) |

**C11-Skip-Begründung.** Die ursprünglich für C11 angedachte
Komponente (online-learning-Loop für Family-Brier-Decay) ist
strukturell auf den C8-Phase-B-Stream angewiesen, der frühestens nach
90 Tagen Live-Inkubation Daten liefert. Eine Vorab-Implementierung
würde gegen Synthetik-Daten kalibrieren — gleiche Fehlerklasse wie
"GREEN gegen Paper-Track" in C12. Die Nummer bleibt reserviert,
damit sich die externe Roadmap-Kommunikation nicht verschiebt; ein
Wiederaufnehmen ist nach C8-Phase-B-Sign-off vorgesehen.
