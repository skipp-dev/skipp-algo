# Improvements-Roadmap C2 – C12

**Datum:** 2026-04-26
**Branch:** `docs/improvements-c2-c12-roadmap`
**Status:** Vorschlag — leitet zwölf Folge-Sprints (C2.1 … C12.1) und drei Cross-Cutting-Sprints (X1 … X3) ab.
**Vorgänger:** C2 Walk-Forward, C3 Bootstrap-CI, C4 Permutation, C5 Regime-Stratifikation, C6 PSR/MinTRL, C7 Dashboard, C8 Live-Inkubation, C9 Drift-Alert, C10 ML-Layer, C12 RL-Execution
**Sprache:** Deutsch

---

## Zweck

Konsolidierter Plan für die nächste Welle Härtungs-Sprints. Jeder Eintrag enthält:

1. **Motivation** — welcher konkrete Risk/Defekt heute existiert.
2. **Scope-Vertrag** — was gebaut wird, was explizit nicht.
3. **PR-Skelett** — Branch-Name, Dateien, Test-Strategie, Promotions-Gate-Kopplung.
4. **Trigger** — welcher Vorgänger-Sprint gemerged sein muss.

Reihenfolge ist nach Impact × Aufwand priorisiert. **Top-3 (X2, C3.1, C4.1)** sind die nächsten Implementierungs-Ziele und werden im Anschluss an diesen Roadmap-PR eröffnet.

---

## Cross-Cutting

### X1 — Alpha-Budget-Ledger

**Motivation:** C4 (Permutation, FDR) und C6 (PSR-Significance) verbrauchen unabhängig voneinander Type-I-Error-Budget. Sobald C5 (Regime-Stratifikation) und C10 (Per-Familie-ML) zusätzliche Hypothesen-Familien einführen, wird α stillschweigend mehrfach verwendet — keine Stelle in `tests/` schlägt heute Alarm.

**Scope-Vertrag:**
- Neu: `governance/alpha_ledger.py` — TypedDict `AlphaReservation(sprint, family, alpha, method, rationale)` + `register(reservation)`-API mit Persistenz unter `governance/alpha_ledger.json`.
- Neu: `tests/test_alpha_budget_inventory.py` — Sum-Check ≤ 0.05 global, ≤ 0.025 per family.
- Operativ: `governance/alpha_ledger.json` wird **statisch** als Inventar gepflegt (Governance-PR, kein Auto-Mutate). Die `register(...)`-API bleibt verfügbar, wird aber von Produktionscode aktuell nicht aufgerufen — eine neue Reservation ist eine bewusste Governance-Änderung und durchläuft Review.
- Out of Scope: Bonferroni/Holm-Routinen ändern (das macht weiterhin C4). Automatische Registrierung beim Modul-Import wird ausdrücklich **nicht** verfolgt (Load-Order- und Test-Isolations-Risiko).

**PR-Skelett:**
- Branch: `sprint/x1-alpha-budget-ledger`
- Dateien: `governance/__init__.py`, `governance/alpha_ledger.py`, `governance/alpha_ledger.json`, `tests/test_alpha_budget_inventory.py`
- Tests: Inventur-Snapshot + Negativ-Test (Doppel-Registrierung → `ValueError`).
- Gate-Kopplung: Read-only auf den Promotions-Gate-Layer (X2).

**Trigger:** Keiner — kann sofort starten.

---

### X2 — PromotionGate-Konsolidator

**Motivation:** Heute prüft jedes Sub-System Brier (C10) / FDR (C4) / PSR (C6) / MinTRL (C6) / PSI (C9) / Live-Brier (C8) separat. Audit „Warum ist Familie X nicht promoted?" erfordert manuelle Quer-Lese durch fünf Module. Das ist die häufigste Reibungsquelle in Reviews.

**Scope-Vertrag:**
- Neu: `governance/promotion_gate.py` mit `PromotionGate.evaluate(family) -> Decision`.
- `Decision = TypedDict("Decision", {"family": EventFamily, "promoted": bool, "blockers": list[Blocker], "metrics": dict[str, float], "schema_version": int})`
- Aggregator-only — verwendet die existierenden Funktionen aus `ml/`, `smc_core/`, `smc_integration/`, `rl/safety/`.
- Out of Scope: Logik-Änderungen an den Einzelchecks. Konfigurations-Änderungen am Gate (das bleibt 17-Punkte-Gate aus C7/C8).

**PR-Skelett:**
- Branch: `sprint/x2-promotion-gate-consolidator`
- Dateien: `governance/promotion_gate.py`, `governance/types.py`, `tests/test_promotion_gate.py`
- Tests: Snapshot je Familie auf den vier Standard-Posturen `green/yellow/orange/red`; Audit-String formatiert.
- Gate-Kopplung: Wird vom Dashboard (C7.1) gerendert.

**Trigger:** X1 gemerged (Decision-Schema referenziert Alpha-Ledger).

---

### X3 — Reproducibility-Manifeste

**Motivation:** C2/C3/C4/C6 schreiben Artifacts ohne einheitlichen Header. Re-Runs auf neuen Datasets können stillschweigend driften, ohne dass `(git_sha, schema_version, seed, dataset_fingerprint)` im Output erkennbar ist.

**Scope-Vertrag:**
- Neu: `governance/run_manifest.py` mit `build_manifest(sprint, **kwargs) -> RunManifest`-Helper.
- Migration: alle Sprint-Skripte unter `scripts/` injizieren das Manifest in ihre primären JSON-Outputs.
- CI-Gate: `tests/test_run_manifest_required.py` lädt jedes vom CI geschriebene Artifact und prüft Schema-Konformität.
- Out of Scope: Alte Artefakte rückwirkend taggen.

**PR-Skelett:**
- Branch: `sprint/x3-run-manifest`
- Dateien: `governance/run_manifest.py`, `tests/test_run_manifest_required.py`, Migration einer Referenz-CLI als Beispiel.
- Tests: Round-Trip (Manifest serialisiert + lädt deterministisch), Negativ (fehlendes Pflichtfeld).

**Trigger:** Keiner.

---

## Per-Sprint-Improvements

### C2.1 — Walk-Forward-Härtung (Embargo + Purging + Anchored)

**Motivation:** C2 läuft heute als rolling window ohne Embargo zwischen Train- und Test-Folds. Überlappende Setup-Labels (z. B. ein BOS, dessen Outcome-Bar im Train-Fold-Ende liegt, aber im Test-Fold-Anfang reportet wird) erzeugen Look-Ahead-Leakage. López-de-Prado-Standard.

**Scope-Vertrag:**
- Erweiterung: `WalkForwardConfig.scheme: Literal["rolling", "anchored", "expanding"] = "rolling"` (default unverändert).
- Erweiterung: `WalkForwardConfig.embargo_bars: int = 0` mit Empfehlungs-Default `= 2 * max_event_horizon`.
- Erweiterung: Purging über überlappende Outcome-Fenster.
- Out of Scope: Default-Schema ändern (das wird via separater Adoption-PR pro Konsumenten gemacht).

**PR-Skelett:**
- Branch: `sprint/c2.1-walkforward-embargo`
- Dateien: `smc_core/walk_forward.py` (Erweiterung), `tests/test_walk_forward_embargo.py`, `tests/test_walk_forward_anchored.py`
- Tests: Embargo schneidet Folds nachweisbar; anchored-Schema produziert monoton wachsendes Train-Set; Purging entfernt überlappende Labels nachweisbar.
- Gate-Kopplung: X2 PromotionGate liest `wf_scheme`/`wf_embargo` aus dem Run-Manifest (X3).

**Trigger:** X3 gemerged.

---

### C3.1 — Bootstrap BCa + Stationary

**Motivation:** Per-Familie-Buckets in C5 haben oft N < 50 Trades. Reines Percentile-Bootstrap unterschätzt CIs systematisch (Coverage ~85 % statt 95 %). Außerdem: serielle Korrelation in Per-Bar-Returns wird vom iid-Bootstrap zerstört.

**Scope-Vertrag:**
- Erweiterung: `bootstrap_ci(method: Literal["percentile", "basic", "bca"] = "percentile")`.
- Neu: `stationary_bootstrap(returns, block_avg_len)` (Politis-Romano).
- Migration: C6 PSR-Konfidenz-Intervalle wechseln auf BCa, sobald validiert.
- Out of Scope: Default-Methode global ändern.

**PR-Skelett:**
- Branch: `sprint/c3.1-bootstrap-bca`
- Dateien: `smc_core/bootstrap.py` (Erweiterung), `tests/test_bootstrap_bca_coverage.py`, `tests/test_stationary_bootstrap.py`
- Tests: Coverage-Simulation auf bekannter Verteilung (BCa ≥ 0.93, percentile ~0.85); stationary erhält Autokorrelation der Order-1.
- Gate-Kopplung: keine direkte; Konsumenten opt-in.

**Trigger:** X1 gemerged (Method-Choice landet im Alpha-Ledger als Rationale).

---

### C4.1 — Block-Permutation + Null-Cache

**Motivation:** Aktueller Permutation-Test bricht serielle Korrelation und unter­schätzt p-Werte für hochfrequente Strategien. Zusätzlich werden Null-Distributionen pro Lauf neu berechnet — bei 4 Familien × 5 Regimes × 1000 Permutationen kostet das pro CI-Lauf erhebliche Zeit.

**Scope-Vertrag:**
- Erweiterung: `permutation_test(block_size: int | None = None)`. None ⇒ legacy iid.
- Neu: `null_cache.parquet` mit Key `(family, regime, dataset_fingerprint, n_perms, block_size)`.
- Cache-Invalidation an `dataset_fingerprint` (X3 Manifest liefert ihn).
- Out of Scope: Adaptive Block-Length-Heuristik (separater Spike).

**PR-Skelett:**
- Branch: `sprint/c4.1-block-permutation-cache`
- Dateien: `smc_core/permutation.py` (Erweiterung), `smc_core/null_cache.py`, `tests/test_block_permutation.py`, `tests/test_null_cache.py`
- Tests: Block-Test reproduziert iid-p-Wert für `block_size=1`; Cache-Hit senkt Walltime in Smoke-Test.
- Gate-Kopplung: X2 PromotionGate konsumiert p-Werte; Cache-Hash landet im X3 Manifest.

**Trigger:** X3 gemerged.

---

### C5.1 — Regime-Min-Sample-Floor + Transition-Bucket

**Motivation:** Sparse Regimes (z. B. „macro-shock", „high-vol-asia") liefern N < 10 Trades und produzieren extrem wackelige Brier-Scores, die als „degraded performance" interpretiert werden. Außerdem sind die meisten echten Failures **während** Regime-Wechseln, was die existierende „im Regime"-Stratifikation versteckt.

**Scope-Vertrag:**
- Erweiterung: `RegimeStratificationConfig.min_n_per_regime: int = 30` mit `degraded`-Flag statt silent-pass.
- Neu: Bucket `transition` für die `k` Bars um einen Regime-Wechsel.
- Out of Scope: Regime-Definitions-Änderungen (das bleibt im jeweiligen Detector).

**PR-Skelett:**
- Branch: `sprint/c5.1-regime-floor-transition`
- Dateien: `scripts/regime_stratification.py` (Erweiterung), `smc_core/regime.py`, `tests/test_regime_min_sample_floor.py`, `tests/test_regime_transition_bucket.py`
- Tests: Klein-N-Bucket emittiert `degraded`; Transition-Bucket fängt synthetisch erzeugten Wechsel.
- Gate-Kopplung: X2 PromotionGate degradiert auf `yellow`, wenn ≥ 1 Regime in `degraded`.

**Trigger:** X1 + X2 gemerged.

---

### C6.1 — PSR / MinIS-Adjustment + robuste Momente

**Motivation:** PSR auf Brutto-Returns überschätzt nutzbare Edge nach Slippage. Sobald C12 Phase A live ist, kann MinTRL → MinIS (Implementation-Shortfall) gedreht werden. Zusätzlich verursachen Outlier-Bars (Earnings-Gaps) extreme Skewness/Kurtosis-Werte → PSR-Flackern.

**Scope-Vertrag:**
- Erweiterung: `compute_psr(returns, *, slippage_bps_series: np.ndarray | None = None)`.
- Erweiterung: `moments_estimator: Literal["sample", "winsorized"] = "sample"`. Der ursprünglich geplante `"hodges_lehmann"`-Estimator ist **deferred**: ohne harten Outlier-Befund im Live-Streaming-Set überwiegt die zusätzliche Implementations- und Test-Last den marginalen Stabilitätsgewinn gegenüber `"winsorized"`. Wieder aufnehmen, sobald PSR-Flackern in Produktion ≥ Bar-Outlier-Threshold dokumentiert wird.
- Out of Scope: Backfill alter PSR-Werte.

**PR-Skelett:**
- Branch: `sprint/c6.1-psr-minIS-robust`
- Dateien: `smc_core/psr.py` (Erweiterung), `tests/test_psr_minIS_adjustment.py`, `tests/test_psr_robust_moments.py`
- Tests: Slippage-adjustierter PSR ≤ Brutto-PSR; winsorized estimator stabil bei injizierten Outliern.
- Gate-Kopplung: X2 PromotionGate verwendet MinIS, sobald C12-Slippage-Modell verfügbar (Feature-Flag `use_minIS_gate`).

**Trigger:** C12 Phase A live (existiert bereits in PR #312).

---

### C7.1 — Decision-First-Dashboard

**Motivation:** Heutige Tabs zeigen Metriken nebeneinander; ein Reviewer muss across tabs scrollen, um „warum ist Familie X nicht promoted" zu beantworten.

**Scope-Vertrag:**
- Neu: `streamlit_terminal/decision_first_panel.py` — Karte je Familie mit Ampel, Top-Blocker, Sparkline der letzten N Walk-Forward-Folds.
- Verwendet X2 `PromotionGate.evaluate()` als einzige Datenquelle.
- Out of Scope: Migration der bestehenden Tabs (additiv).

**PR-Skelett:**
- Branch: `sprint/c7.1-decision-first-dashboard`
- Dateien: `streamlit_terminal/decision_first_panel.py`, `tests/test_decision_first_panel_render.py`
- Tests: Snapshot-Render gegen alle vier Posturen.
- Gate-Kopplung: liest X2.

**Trigger:** X2 gemerged.

---

### C8.1 — Forward-Test-Tracking + Dynamische Inkubation

**Motivation:** Aktuelle 4-Wochen-Inkubation ist starr und ignoriert Sample-Größe. Außerdem fehlt ein expliziter `expected_vs_realized`-Watchdog: wenn Live-Brier 1.5× über WF-Brier liegt, sollte sofort demoted werden, nicht erst nach Drift-Alert.

**Scope-Vertrag:**
- Erweiterung: `LiveIncubationConfig.dynamic_stop = True`, mit Stop-Bedingung `n_live ≥ N* AND PSR_live ≥ PSR_wf - margin`.
- Neu: `expected_vs_realized_ratio()` als Posture-Demote-Auslöser.
- Out of Scope: Trigger-Bedingung für C12 (bleibt 4 Wochen).

**PR-Skelett:**
- Branch: `sprint/c8.1-forward-test-tracking`
- Dateien: `smc_core/live_incubation.py` (Erweiterung), `scripts/run_smc_live_incubation.py`, `tests/test_expected_vs_realized.py`, `tests/test_dynamic_incubation_stop.py`
- Tests: Synthetic Brier-Drift demoted innerhalb 1 Window.
- Gate-Kopplung: X2 PromotionGate.

**Trigger:** X2 gemerged.

---

### C9.1 — PSI Trend + Importance-Weighted

**Motivation:** Aktuelles PSI-Threshold-Alert (>0.25) feuert spät; creeping drift über 14 Tage wird nicht gefangen. Außerdem: PSI auf low-importance-Features ist Lärm.

**Scope-Vertrag:**
- Erweiterung: `psi_trend_alert(window=7d, slope_threshold)` parallel zum Level-Alert.
- Erweiterung: `psi_weighted(feature_importance: dict[str, float] | None = None)`.
- Out of Scope: Drift-Mitigation-Strategien.

**PR-Skelett:**
- Branch: `sprint/c9.1-psi-trend-weighted`
- Dateien: `ml/drift/__init__.py` (Erweiterung), `tests/test_psi_trend_alert.py`, `tests/test_psi_importance_weighted.py`
- Tests: Synthetic creep löst Trend-Alert vor Level-Alert aus; importance-gewichteter PSI ist robust gegen Noise auf irrelevanten Features.
- Gate-Kopplung: X2 PromotionGate.

**Trigger:** C10 #311 gemerged (für `feature_importance_`-Konsum).

---

### C10.1 — Stacking + Conformal + Closure-Free predict_proba

**Motivation:** Per-Familie disjunkt verliert Information bei gleichzeitig auftretenden Setup-Familien (BOS+OB). Zusätzlich liefert reines Brier-Calibration keine Coverage-Garantie — Conformal Prediction (Vovk) tut das. Letztens: das aktuelle `FittedModel.extra['predict_proba']` ist ein Lambda mit `self`-Closure (Copilot-Hint), nicht Pickle-fähig.

**Scope-Vertrag:**
- Neu: `ml/stacking/meta_learner.py` über die 4 Per-Familie-Outputs.
- Neu: `ml/calibration/conformal.py` mit Split-Conformal und Adaptive (Romano-Patterson).
- Refactor: `predict_proba` als reine Funktion mit `(coefficients, calibrator_state)` als Closure-Inhalt.
- Out of Scope: Multi-Task-Learner.

**PR-Skelett:**
- Branch: `sprint/c10.1-stacking-conformal`
- Dateien: `ml/stacking/__init__.py`, `ml/stacking/meta_learner.py`, `ml/calibration/conformal.py`, `ml/training/base.py` (predict_proba refactor), `tests/test_meta_learner_smoke.py`, `tests/test_conformal_coverage.py`
- Tests: Meta-Learner verbessert Brier vs. Mean-of-Family auf Synthetik um ≥ 5 %; Conformal-Coverage liegt im Toleranzband.
- Gate-Kopplung: X2 PromotionGate konsumiert Stacked-Output, sobald validiert.

**Trigger:** PR #311 gemerged.

---

### C12.1 — CVaR + Adversarial Slippage + Walk-Forward + Audit-Log

**Motivation:** Reine Varianz-Penalty bestraft Upside; CVaR_5 % ist die Standard-Risk-Adjustment-Wahl. Adversarial Slippage-Replay testet Worst-Case-Verhalten. Walk-Forward für RL fehlt analog C2. Hard-Constraint-Layer-Clamps werden nicht geloggt — systematische Constraint-Hits verraten Reward-Mis-Specification.

**Scope-Vertrag:**
- Erweiterung: `EnvConfig.risk_metric: Literal["variance", "cvar5", "cvar1"] = "variance"`.
- Neu: `rl/stress/adversarial_replay.py` mit Worst-Case-Bar-Replay.
- Neu: `rl/walk_forward.py` für RL-Episoden-Folds.
- Erweiterung: `HardConstraintLayer` schreibt Clamp-Log nach `artifacts/rl/constraint_hits.parquet`.
- Out of Scope: Multi-Agent.

**PR-Skelett:**
- Branch: `sprint/c12.1-cvar-stress-walkforward`
- Dateien: `rl/simulator/execution_env.py` (Erweiterung), `rl/stress/`, `rl/walk_forward.py`, `rl/safety/__init__.py` (Audit), `tests/test_cvar_reward.py`, `tests/test_adversarial_replay.py`, `tests/test_rl_walk_forward.py`, `tests/test_constraint_hit_log.py`
- Tests: CVaR-Reward sanktioniert Tail-Loss härter als Variance; adversarial Bars erhöhen IS messbar; WF-Folds sind purged; Audit-Log monoton.
- Gate-Kopplung: eigenes RL-Promotions-Gate (Action-Distribution-Stabilität, IS-Verbesserung).

**Trigger:** PR #312 gemerged.

---

## Roll-Out-Reihenfolge

```
Block 1 (sofort):  X1 → X2 → X3
Block 2 (parallel): C3.1, C4.1, C9.1, C10.1, C12.1
Block 3 (parallel): C2.1, C5.1, C6.1, C7.1, C8.1
```

X1–X3 sind Voraussetzung für die Promotions-Gate-Kopplung der Per-Sprint-Improvements. Block 2 läuft gegen die jeweils zuletzt gemergten C-Sprints; Block 3 wartet auf X2 + X3 + Block 2 zur Vermeidung von Konflikten.

## Top-3 für sofortige Umsetzung

1. **X2 PromotionGate-Konsolidator** — größter Audit-Hebel, < 1 Tag.
2. **C3.1 Bootstrap BCa** — entfernt eine stille statistische Verzerrung, < 1 Tag.
3. **C4.1 Block-Permutation** — entfernt die zweite stille Verzerrung, < 1 Tag.

Diese drei werden direkt nach diesem Roadmap-PR als separate PRs eröffnet.

## Out-of-Scope für die gesamte Roadmap

- Setup-Detection-Architektur-Änderungen.
- Neue Datenquellen oder Provider.
- UI-Re-Design über die `decision_first_panel`-Karte hinaus.
- Multi-Agent-RL, RL-basierte Setup-Detection.

Alle drei letztgenannten Punkte wandern in `docs/research/` als Spike-Kandidaten, sobald ein Bedarf entsteht.
