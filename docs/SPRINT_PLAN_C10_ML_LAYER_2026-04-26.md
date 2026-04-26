# Sprint-Plan C10 — ML-Layer auf SMC-Familien

**Datum:** 2026-04-26
**Branch (geplant):** `sprint/c10-ml-layer`
**Status:** Plan, noch nicht implementiert
**Vorgänger:** C2 Walk-Forward, C3 Bootstrap-CI, C4 Permutation, C5 Regime-Stratifikation, C6 PSR/MinTRL, C7 Dashboard, C8 Live-Inkubation, C9 Drift-Alert
**Sprache:** Deutsch

---

## Ziel

Einen produktionsreifen ML-Layer einziehen, der pro SMC-Familie (`BOS`/`OB`/`FVG`/`SWEEP`) eine kalibrierte Erfolgs-Wahrscheinlichkeit `P(profitable | features)` liefert und nahtlos durch das bestehende Promotions-Gate läuft. Der Layer ist **additiv** zur regelbasierten Detection und wird nur dann live geschaltet, wenn er die Calibration-Track-Record-Hürden überspringt.

**Verbindlicher Vertrag:** Die KI ist nicht der Edge. Die kalibrierte und FDR-korrigierte KI ist der Edge. Modell-Outputs werden ohne Ausnahme durch Brier, BH-FDR, Permutation, PSR/MinTRL und Drift-Watchdog validiert — exakt wie regelbasierte Setups in C2-C9.

**Drei Phasen, sequentiell:**

1. **Phase A — XGBoost MVP** (Pfad A)
2. **Phase B — LightGBM mit Online-Recalibration** (Pfad B)
3. **Phase C — Microstructure-Feature-Erweiterung** (Industrie-Standard)

Out of Scope für C10: Deep Learning (Kategorie 2) und RL-Execution (Kategorie 3) — beide sind in C11/C12 als separate Add-ons platziert (siehe Abschnitt "Out-of-Scope mit Roadmap").

---

## Inventur (✅ vorhanden / ❌ Greenfield)

### Familien-Konstanten ✅ vorhanden

[`smc_core/scoring.py:33`](https://github.com/skippALGO/skipp-algo/blob/main/smc_core/scoring.py): `EventFamily = Literal["BOS", "OB", "FVG", "SWEEP"]`. `_FAMILY_ORDER` Zeile 34 fixiert die Reihenfolge.

`FamilyScoringMetrics` Klasse ab Zeile 59 ist die Schnittstelle, in die der ML-Output sich einklinken kann (Feld `family_metrics` ab Zeile 151).

### HERO-Feature-Vokabular ✅ vorhanden

`HERO_BIAS_VOCAB`, `HERO_MARKET_MODE_VOCAB`, `HERO_TRUST_VOCAB`, `HERO_SETUP_QUALITY_VOCAB`, `HERO_ACTION_VOCAB` sind durch [`tests/test_hero_observed_vocab_pin.py`](https://github.com/skippALGO/skipp-algo/blob/main/tests/test_hero_observed_vocab_pin.py) festgenagelt — pinned vocabularies, deterministische Werte. Genau das brauchen wir als ML-Input.

### Event-Ledger ✅ vorhanden

Aus C2/C3-Vorarbeiten existiert ein deterministischer Event-Ledger mit `(timestamp, family, features, outcome)` Tupeln. Bereits durch Walk-Forward-Pipeline genutzt.

### Calibration-Pipeline ✅ vorhanden

Brier, ECE, BH-FDR, Phipson-Smyth aus C2/C3/C4 — frei konsumierbar für ML-Outputs. ⚙️ operativ getestet in [PR #243](https://github.com/skippALGO/skipp-algo/pull/243), [#245](https://github.com/skippALGO/skipp-algo/pull/245).

### Promotions-Gate ✅ vorhanden

17-Punkte-Gate aus C7/C8. ML-Output muss exakt dieselben Hürden überspringen wie regelbasierte Setups.

### Drift-Watchdog ✅ vorhanden

C9 mit CUSUM, PSI, Page-Hinkley, KS-Test über die Outcome-Verteilung. Wird auf ML-Probability-Outputs zusätzlich gespiegelt (siehe Phase B).

### ML-Modelle ❌ Greenfield

Es gibt heute **keinen** XGBoost/LightGBM/CatBoost im Repo. Greenfield-Implementierung in `ml/` Modul.

### Microstructure-Features ❌ Greenfield

Order-Book-Features (Bid-Ask-Imbalance, Volume-Imbalance, VPIN), Realized Volatility, Time-of-Day-Encoding sind nicht im Repo. Greenfield in Phase C.

---

## Methoden-Foundation

### Phase A — XGBoost MVP pro Familie

**Architektur:** Vier separate Klassifikatoren, einer pro Familie. Bewusst **keine** gemeinsame Multi-Task-Architektur — Familien sind unterschiedliche statistische Populationen, getrennte Modelle erlauben pro-Familie-Tuning und pro-Familie-Promotions.

- Modell: `xgboost.XGBClassifier` mit `objective="binary:logistic"`, `eval_metric="logloss"`, `early_stopping_rounds=50`
- Inputs: HERO-Features + Familien-spezifische Strukturmetriken aus `FamilyScoringMetrics`
- Output: `P(profitable | features) ∈ [0, 1]`
- Definition "profitable": Outcome-Label aus dem Event-Ledger (TP-Hit vor SL-Hit innerhalb des Setup-Horizons)
- Hyperparameter-Tuning: `optuna` Bayesian Optimization auf Walk-Forward-Folds, **kein** Grid-Search auf Full-Sample
- Feature-Importance via SHAP für Erklärbarkeit (auditierbarer Track-Record)

**Akademische Basis:**
- [López de Prado 2018 Advances in Financial Machine Learning](https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086) — purged k-fold cross-validation, meta-labeling, fractional differentiation
- [Chen-Guestrin 2016 XGBoost](https://arxiv.org/abs/1603.02754) — Original-Paper
- [Lundberg-Lee 2017 SHAP](https://arxiv.org/abs/1705.07874) — Feature-Attribution

### Phase B — LightGBM mit Online-Recalibration

**Architektur:** Wie Phase A, aber mit Production-Hardening.

- Modell: `lightgbm.LGBMClassifier` (~5-10× schneller als XGBoost bei vergleichbarer Performance laut [Ke et al. 2017](https://papers.nips.cc/paper/2017/hash/6449f44a102fde848669bdd9eb6b76fa-Abstract.html))
- **Probability-Calibration** in zwei Stufen:
  - Stufe 1: Isotonic Regression auf Validation-Fold (sklearn `CalibratedClassifierCV(method="isotonic", cv="prefit")`)
  - Stufe 2: Platt Scaling als Fallback bei kleinen Sample-Größen (n < 200 pro Bin)
  - Auswahl Stufe 1 vs. 2 datengetrieben via Brier-Score auf Held-out
- **Walk-Forward-Refit-Plan:**
  - Refit-Frequenz: alle 4 Wochen oder bei Drift-Trigger, je nachdem was zuerst eintritt
  - Hot-Reload: Modell-Artifact via `joblib`, Atomic-Swap im Deployment
  - Versioning: Modell-Artifacts in `models/{family}/v{date}_{sha}.joblib`, registriert in `models/registry.json`
- **Drift-Detection auf Probability-Outputs:**
  - PSI auf Score-Distribution (10 Buckets, Schwelle 0,2 für Refit-Trigger, 0,25 für Alarm)
  - KS-Test gegen Baseline-Score-Distribution
  - Spiegelung in C9-Drift-Watchdog (gleiche Alert-Pipeline)

**Akademische Basis:**
- [Platt 1999 Probabilistic Outputs for SVMs](https://www.researchgate.net/publication/2594015) — Platt Scaling
- [Zadrozny-Elkan 2002 Transforming classifier scores into probabilities](https://www.cs.cornell.edu/courses/cs678/2007sp/ZadroznyElkan.pdf) — Isotonic Regression für Kalibrierung
- [Niculescu-Mizil-Caruana 2005 Predicting good probabilities with supervised learning](https://www.cs.cornell.edu/~alexn/papers/calibration.icml05.crc.rev3.pdf) — Vergleich beider Methoden
- [Ke et al. 2017 LightGBM](https://papers.nips.cc/paper/2017/hash/6449f44a102fde848669bdd9eb6b76fa-Abstract.html)

### Phase C — Microstructure-Feature-Erweiterung

**Architektur:** Die Modelle aus Phase B bleiben, die Feature-Bibliothek wird erweitert.

- **Order-Book-Features** (Tick/Sub-Sekunden):
  - Bid-Ask-Imbalance: `(bid_size - ask_size) / (bid_size + ask_size)` über letzte K Ticks
  - Volume-Imbalance auf Bar-Ebene: signed volume nach Tick-Rule
  - Trade-Flow-Toxicity: VPIN nach [Easley-López de Prado-O'Hara 2012](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1695596)
- **Volatility-Features:**
  - Realized Volatility (RV) über rolling Windows
  - Bipower Variation für Jump-Detection
  - Garman-Klass und Parkinson Estimator als robuste OHLC-RV-Approximationen
- **Time-of-Day-Features:**
  - Cyclical Encoding (sin/cos Transformation für Tageszeit, Wochentag)
  - Session-Marker (Asia/London/NY-Open, Lunch-Break, Close)
- **Cross-Symbol-Features** (optional, falls Multi-Symbol-Stream):
  - Korrelations-Matrix über rolling Window
  - Lead-Lag-Beziehungen über Granger-Tests

**Akademische Basis:**
- [Cont-Sirignano 2019 Universal Features of Price Formation](https://arxiv.org/abs/1809.10711) — Microstructure-Universalität
- [Easley-López de Prado-O'Hara 2012 VPIN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1695596) — Trade-Flow-Toxicity
- [Andersen-Bollerslev 1998 Realized Volatility](https://www.jstor.org/stable/2527343) — RV-Foundation
- [Garman-Klass 1980](https://www.jstor.org/stable/2352358), [Parkinson 1980](https://www.jstor.org/stable/2352357) — OHLC-Volatility-Estimators

---

## Tasks

### T1 (Tag 1) — Inventur-Pin + Schema-Lock ⚙️

- Snapshot des aktuellen `FamilyScoringMetrics`-Schemas in `ml/schemas/v1_input_schema.json`
- HERO-Vokabular-SHA-Pin (gegen `tests/test_hero_observed_vocab_pin.py`) als ML-Feature-Manifest in `ml/schemas/v1_hero_features.json`
- Test: `tests/test_ml_input_schema_pin.py` — Schema-Hash gegen erwartetes SHA, bricht CI bei Schema-Drift
- Trainings-Ledger-Format definieren: Parquet mit Spalten `(event_id, ts_utc, family, features_blob, outcome_label, fold_id)`, deterministisch sortiert nach `(ts_utc, event_id)`

**Deliverable:** `ml/schemas/` mit gepinnten Schemas, Test grün, Doku in `ml/README.md`.

### T2 (Tag 1-3) — `ml/training/xgb_family_trainer.py` ⚙️🧪

Phase A Implementation.

- `XGBFamilyTrainer` Klasse, eine Instanz pro Familie
- Walk-Forward-Splits aus C2-Pipeline wiederverwendet (kein neues Splitting-Schema, sonst Test-Leak-Risiko)
- Training-Loop mit `early_stopping_rounds=50` auf Validation-Fold
- Hyperparameter via Optuna mit Pruning (median pruner), max 100 Trials pro Familie pro Fold
- Output: `models/{family}/xgb_v{date}.joblib` plus `models/{family}/xgb_v{date}_metrics.json` mit Brier, AUC, log-loss
- Test: `tests/test_xgb_family_trainer.py` — Smoke-Test auf synthetischen Daten, Reproduzierbarkeit (seed-fixed), keine Lookahead-Leaks (purged k-fold-Assertion)

**Deliverable:** Funktionsfähiger XGBoost-Trainer für alle vier Familien, Smoke-Test grün, Trainings-Run auf historischen Daten dokumentiert.

### T3 (Tag 3-4) — `ml/inference/family_predictor.py` ⚙️🧪

- `FamilyPredictor` Klasse — lädt Modell-Artifact, liefert `P(profitable | features)`
- Hot-Reload via Watchdog auf `models/registry.json`
- Atomic-Swap des Modell-Handles (Reader/Writer-Lock)
- Output-Format: `MLPrediction(family, probability, model_version, features_hash, inference_ts)` als Dataclass in `ml/types.py`
- Integration in bestehendes Event-Ledger: ML-Prediction wird als zusätzliches Feld in `FamilyScoringMetrics` aufgenommen (rückwärtskompatibel via Optional-Field)
- Test: `tests/test_family_predictor.py` — Inferenz-Reproduzierbarkeit, Versions-Pinning, Atomic-Swap-Race-Test

**Deliverable:** Live-Inferenz funktionsfähig, Integration ins Event-Ledger dokumentiert, Tests grün.

### T4 (Tag 4-5) — Calibration + Promotions-Gate-Integration ⚙️🧪

ML-Outputs gehen durch dieselbe Calibration- und Promotions-Pipeline wie regelbasierte Setups.

- `ml/calibration/probability_calibrator.py` — Isotonic + Platt mit Auto-Selection via Held-out Brier
- Anbindung an C2-Walk-Forward-Pipeline: ML-Probability als zusätzliche Spalte im Calibration-Ledger
- Anbindung an C3-Bootstrap-CI: Bootstrap auf ML-Hit-Rates pro Fold
- Anbindung an C4-Permutation: Permutationstest auf ML-vs-Baseline-Differential
- Anbindung an C6-PSR/MinTRL: PSR-Test auf ML-Strategie-Returns (nicht nur Hit-Rates)
- Test: `tests/test_ml_calibration_pipeline.py` — End-to-End vom Train zur Promotion-Entscheidung

**Deliverable:** ML-Familie kann durch Promotions-Gate gehen, mindestens eine simulierte Familie schafft Promotion auf historischen Daten (oder begründete Falsifikation).

### T5 (Tag 5-7) — Phase B: LightGBM-Migration ⚙️🧪

- `ml/training/lgbm_family_trainer.py` — strukturgleich zu XGBoost-Trainer, mit LightGBM-spezifischen Features (categorical handling, dart-boosting optional)
- A/B-Vergleich XGBoost vs. LightGBM auf Walk-Forward-Folds: Brier, AUC, Inference-Latency
- Auswahl-Kriterium: Brier ≤ 1% schlechter UND Inference-Latency ≤ 50% besser → LightGBM gewinnt
- Falls LightGBM gewinnt: `ml/training/xgb_family_trainer.py` bleibt als Fallback, nicht gelöscht
- Test: `tests/test_lgbm_family_trainer.py` analog T2

**Deliverable:** A/B-Bericht in `docs/ml/lgbm_vs_xgb_2026-XX-XX.md`, Default-Modell entschieden und dokumentiert.

### T6 (Tag 7-9) — Online-Recalibration + Refit-Cron ⚙️🧪

Phase B Hardening.

- `ml/calibration/online_recalibrator.py` — alle 4 Wochen oder bei Drift-Trigger
- Drift-Trigger ist PSI > 0,2 auf Probability-Distribution (Quelle: [Federal Reserve 2018 Population Stability Index](https://www.federalreserve.gov/econres/notes/feds-notes/credit-scoring-drift-and-population-stability-index-20180511.html))
- GitHub Actions Workflow `.github/workflows/ml_recalibration.yml` — wöchentlicher Cron, manueller Trigger via `workflow_dispatch`
- Refit-Output: neue Modell-Version in `models/{family}/`, alte Version bleibt für Rollback
- Test: `tests/test_online_recalibrator.py` — Drift-Trigger-Logik, Atomic-Swap, Rollback-Pfad

**Deliverable:** Cron läuft, Drift-Trigger getestet auf historischem Drift-Event aus C9-Backfill, Rollback-Plan dokumentiert.

### T7 (Tag 9-11) — Phase C: Microstructure-Features ⚙️🧪

- `ml/features/microstructure.py` — Bid-Ask-Imbalance, Volume-Imbalance, VPIN-Approximation auf Bar-Daten
- `ml/features/volatility.py` — Realized Volatility, Garman-Klass, Parkinson
- `ml/features/temporal.py` — Cyclical Encoding, Session-Marker
- Feature-Selection via SHAP-Importance auf Walk-Forward-Folds — neue Features werden nur dann produktiv, wenn sie SHAP-Top-20 erreichen
- Test: `tests/test_ml_microstructure_features.py` — deterministische Berechnung, Edge-Cases (zero-volume bars, gap-opens), Performance (< 100ms pro 10k bars)

**Deliverable:** Erweiterte Feature-Library, A/B-Vergleich Phase B vs. Phase C auf Brier/PSR, Promotions-Entscheidung pro Familie.

### T8 (Tag 11-12) — Drift-Watchdog-Spiegelung ⚙️🧪

- C9-Drift-Watchdog erweitern um ML-Probability-Distribution als zusätzlichen Detektor
- PSI, KS-Test, Page-Hinkley auf Score-Outputs (nicht nur auf Trade-Outcomes)
- Alert-Pipeline-Integration: separate Alert-Klasse `MLDriftAlert` in C9-Schema
- Dashboard-Panel `docs/calibration/ml_drift.html` (analog zu C9-Drift-Panel)
- Test: `tests/test_ml_drift_detection.py` — historisches Drift-Replay aus C9-Backfill

**Deliverable:** ML-Drift-Detection live, Dashboard-Panel verlinkt (intern, nicht öffentlich vor Promotion).

### T9 (Tag 12-13) — Doku + Sprint-Close 🧪

- `docs/ml/architecture.md` — System-Diagramm, Schnittstellen, Schema-Versionen
- `docs/ml/promotion_record.md` — pro Familie: hat ML das Gate übersprungen, mit welchen Metriken
- ADR-Template ausgefüllt: `docs/adr/2026-XX-ml-layer.md` — Entscheidung XGBoost vs. LightGBM, Begründung
- Eintrag in die konsolidierte Roadmap `docs/SPRINT_ROADMAP_C2_C9_CONSOLIDATED_2026-04-26.md` als zentralem Repo-Master-Doc
- Sprint-Retro in `docs/sprints/c10-retro.md`

**Deliverable:** Doku komplett, Sprint geschlossen, PR review-ready.

---

## Speed-Hebel-Anwendung

- **Wiederverwendung C2-C9:** Walk-Forward-Splits, Calibration-Pipeline, Promotions-Gate, Drift-Watchdog, Cron-Infrastruktur — nichts davon wird neu gebaut
- **Schema-Locking statt Re-Validation:** HERO-Vokabular ist bereits durch SHA-Pins gesichert, ML-Layer nutzt das ohne eigene Validation
- **Bibliotheken statt Eigenbau:** XGBoost, LightGBM, sklearn `CalibratedClassifierCV`, Optuna, SHAP — alle Industrie-Standard
- **Synthetische Smoke-Tests vor echten Trainings-Runs:** First-Pass auf generierten Daten zur CI-Stabilisierung, dann historische Daten
- **Modulare Phasen:** Phase A kann live, bevor B/C fertig sind — kein Big-Bang-Deployment

---

## Risiken + Gegenmaßnahmen

### Risiko 1 — Overfitting durch zu viele Features

**Symptom:** Train-Brier << Val-Brier, AUC-Gap > 0,1.
**Gegenmaßnahme:** Purged k-fold (López de Prado), Optuna mit Validation-Brier als Optimierungsziel, SHAP-basierte Feature-Selection mit Top-K-Cap (K=30 pro Familie).

### Risiko 2 — Lookahead-Leakage

**Symptom:** Suspicious-gut Performance auf Walk-Forward, Verschlechterung im Live-Test.
**Gegenmaßnahme:** Feature-Computation strikt auf historische Bars beschränkt, Embargoed Walk-Forward-Splits (Embargo-Periode 1 Bar nach Test-Window), Audit-Test `tests/test_ml_no_lookahead.py` der prüft, dass keine Feature einen Future-Timestamp referenziert.

### Risiko 3 — Probability-Decalibration über die Zeit

**Symptom:** Brier steigt monoton über mehrere Wochen, ohne dass der Markt sich offensichtlich ändert.
**Gegenmaßnahme:** Online-Recalibration alle 4 Wochen (T6), Auto-Rollback wenn neue Kalibrierung schlechter als alte (Brier-Regret-Test).

### Risiko 4 — Zu wenig Trainingsdaten pro Familie

**Symptom:** Eine oder mehrere Familien haben < 1000 Events im Trainings-Window.
**Gegenmaßnahme:** Minimum-Samples-Gate (n ≥ 1000 pro Familie pro Fold) bricht Promotion ab, Familie bleibt regelbasiert. Akzeptiertes Outcome — nicht jede Familie wird ML-fähig sein.

### Risiko 5 — ML-Layer überstimmt regelbasiertes System ohne Edge

**Symptom:** ML-Probability differenziert nicht stark genug von regelbasiertem Score.
**Gegenmaßnahme:** Permutationstest (C4) auf ML-vs-Baseline-Differential — wenn p > 0,10, wird ML-Layer für die Familie nicht aktiviert. Falsifikations-Vertrag bleibt intakt.

### Risiko 6 — Inference-Latency bricht Live-Pipeline

**Symptom:** Inferenz > 50ms pro Event, Live-Decisioning zu langsam.
**Gegenmaßnahme:** LightGBM-Default (T5), Treelite-Compilation als Fallback, Latency-SLA als Test in `tests/test_ml_inference_latency.py`.

### Risiko 7 — Modell-Artifact-Korruption oder Versions-Drift

**Symptom:** Atomic-Swap fehlschlägt, Inferenz nutzt veraltetes Modell.
**Gegenmaßnahme:** SHA-Hash auf Modell-Artifact in `models/registry.json`, Inferenz-Pfad verifiziert Hash vor Load, Inkonsistenz löst Alarm aus.

---

## Akzeptanzkriterien

C10 ist abgeschlossen, wenn:

1. **Phase A:** XGBoost-Trainer für alle vier Familien funktional, Tests grün, mindestens eine Familie hat dokumentierten Walk-Forward-Brier < 0,22 (gleiche Schwelle wie regelbasiert)
2. **Phase B:** LightGBM-A/B-Vergleich abgeschlossen, Default-Modell entschieden, Online-Recalibration via Cron läuft seit mindestens 1 Woche
3. **Phase C:** Microstructure-Features integriert, A/B-Bericht zeigt Brier-Verbesserung ≥ 5% gegenüber Phase B (oder begründete Falsifikation)
4. **Promotions-Gate:** Mindestens eine ML-Familie hat alle 17 Punkte überstanden ODER begründeter Falsifikations-Bericht für jede gescheiterte Familie liegt vor
5. **Drift-Watchdog:** ML-Probability-Drift in C9-Pipeline integriert, historischer Backfill bestätigt Trigger-Verhalten
6. **Doku:** ADR, Architecture-Doc, Promotion-Record, Sprint-Retro vorhanden
7. **Code-Qualität:** Coverage ≥ 80% auf `ml/` Modul, mypy strict, alle Tests grün

---

## Out-of-Scope mit Roadmap

Die folgenden Themen sind bewusst **nicht** in C10 — separate Sprint-Pläne bei Bedarf:

### C11 — Deep Learning auf Sequenzen (geplant, nicht zwingend)

**Inhalt:** LSTM/Transformer für Tick-Level-Vorhersage, sobald Tick-Daten-Stream verfügbar.
**Voraussetzung:** Mindestens 1M Tick-Samples pro Familie, GPU-Compute-Budget freigeschaltet.
**Quellen:** [Sirignano-Cont 2019 Deep Learning for Limit Order Books](https://arxiv.org/abs/1901.10380), [Lim-Zohren 2021 Time-series forecasting with deep learning: a survey](https://arxiv.org/abs/2004.13408).
**Begründung Aufschub:** Auf 5-min/15-min Bars eines Einzel-Symbols ist klassisches ML der bessere Hebel — Deep Learning lohnt sich erst bei Tick-Daten oder großem Symbol-Universum.

### C12 — Reinforcement Learning für Execution + Sizing (geplant für Post-Live)

**Inhalt:** DQN/PPO/SAC für Order-Slicing und Position-Sizing, sobald mindestens eine Familie live im Promotions-Gate ist.
**Voraussetzung:** Live-Track-Record mit echten Outcomes, Slippage-Modell kalibriert.
**Quellen:** [Nevmyvaka-Feng-Kearns 2006 Reinforcement Learning for Optimized Trade Execution](https://www.cis.upenn.edu/~mkearns/papers/rlexec.pdf), [JPMorgan LOXM 2017](https://www.jpmorgan.com/insights/markets/algorithmic-trading/jpmorgan-introduces-loxm-2017).
**Begründung Aufschub:** RL ist für **Execution-Optimierung**, nicht für Setup-Erkennung. Erst sinnvoll, wenn ein Setup live ist und Sizing-Entscheidungen anstehen.

### Foundation Models (TimesFM, Chronos, Time-LLM) — Forschungs-Spike

⚠ nur plausibel: Methodisch noch unreif für Production. Als 1-Tages-Forschungs-Spike geplant, nicht als Sprint. Die Bewertung wird nach C10-Abschluss im Rahmen dieses Spikes als separate Dokumentation unter `docs/` erstellt; der konkrete Zielpfad wird dabei festgelegt.

---

## Quellen

### Klassisches ML auf Microstructure
- [López de Prado 2018 Advances in Financial Machine Learning](https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086)
- [Cont-Sirignano 2019 Universal Features of Price Formation](https://arxiv.org/abs/1809.10711)
- [Chen-Guestrin 2016 XGBoost](https://arxiv.org/abs/1603.02754)
- [Ke et al. 2017 LightGBM NeurIPS](https://papers.nips.cc/paper/2017/hash/6449f44a102fde848669bdd9eb6b76fa-Abstract.html)
- [Lundberg-Lee 2017 SHAP NeurIPS](https://arxiv.org/abs/1705.07874)

### Probability Calibration
- [Platt 1999 Probabilistic Outputs for SVMs](https://www.researchgate.net/publication/2594015)
- [Zadrozny-Elkan 2002 Isotonic Regression](https://www.cs.cornell.edu/courses/cs678/2007sp/ZadroznyElkan.pdf)
- [Niculescu-Mizil-Caruana 2005 ICML](https://www.cs.cornell.edu/~alexn/papers/calibration.icml05.crc.rev3.pdf)
- [Kumar-Liang-Ma 2019 Verified Calibration NeurIPS](https://arxiv.org/abs/1909.10155)

### Microstructure-Features
- [Easley-López de Prado-O'Hara 2012 VPIN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1695596)
- [Andersen-Bollerslev 1998 Realized Volatility](https://www.jstor.org/stable/2527343)
- [Garman-Klass 1980](https://www.jstor.org/stable/2352358)
- [Parkinson 1980](https://www.jstor.org/stable/2352357)

### Drift-Detection
- [Federal Reserve 2018 Population Stability Index](https://www.federalreserve.gov/econres/notes/feds-notes/credit-scoring-drift-and-population-stability-index-20180511.html)
- [Page 1954 CUSUM](https://www.jstor.org/stable/2333009)

### Statistische Härtung (aus C2-C9, hier referenziert)
- [Bailey-López de Prado 2012 PSR/MinTRL](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1821643)
- [Benjamini-Hochberg 1995 FDR](https://www.jstor.org/stable/2346101)
- [Phipson-Smyth 2010 Permutation p-values](https://www.degruyter.com/document/doi/10.2202/1544-6115.1585/html)
- [Harvey-Liu-Zhu 2015 Backtesting](https://people.duke.edu/~charvey/Research/Published_Papers/P120_Backtesting.PDF)

### Out-of-Scope-Referenzen (für C11/C12)
- [Sirignano-Cont 2019 Deep Learning for Limit Order Books](https://arxiv.org/abs/1901.10380)
- [Lim-Zohren 2021 Time-series forecasting with deep learning: a survey](https://arxiv.org/abs/2004.13408)
- [Nevmyvaka-Feng-Kearns 2006 RL for Trade Execution](https://www.cis.upenn.edu/~mkearns/papers/rlexec.pdf)
- [JPMorgan LOXM 2017](https://www.jpmorgan.com/insights/markets/algorithmic-trading/jpmorgan-introduces-loxm-2017)

---

## Evidenz-Marker-Zusammenfassung

- ✅ im Code:
  - `EventFamily = Literal["BOS", "OB", "FVG", "SWEEP"]` in [`smc_core/scoring.py:33`](https://github.com/skippALGO/skipp-algo/blob/main/smc_core/scoring.py)
  - `_FAMILY_ORDER` in [`smc_core/scoring.py:34`](https://github.com/skippALGO/skipp-algo/blob/main/smc_core/scoring.py)
  - `FamilyScoringMetrics` ab [`smc_core/scoring.py:59`](https://github.com/skippALGO/skipp-algo/blob/main/smc_core/scoring.py)
  - HERO-Vokabular-Pins in [`tests/test_hero_observed_vocab_pin.py`](https://github.com/skippALGO/skipp-algo/blob/main/tests/test_hero_observed_vocab_pin.py)
- 🧪 getestet: Walk-Forward, Bootstrap-CI, Permutation, PSR, Drift-Detection — alles aus C2-C9 grün
- ⚙️ operativ: Calibration-Pipeline, Promotions-Gate, Cron-Infrastruktur, Drift-Watchdog — alle Production-erprobt aus PRs [#243](https://github.com/skippALGO/skipp-algo/pull/243), [#245](https://github.com/skippALGO/skipp-algo/pull/245), [#249](https://github.com/skippALGO/skipp-algo/pull/249), [#252](https://github.com/skippALGO/skipp-algo/pull/252)
- ⚠ nur plausibel: Erfolgswahrscheinlichkeit der ML-Familien hängt von echten Daten ab — keine garantierten Promotions, Falsifikations-Vertrag bleibt intakt
