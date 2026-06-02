# mlfinlab — Build-vs-Buy-Evaluation für SkippALGO

**Datum:** 2026-06-02
**Autor:** Principal Quant (autonomer Review)
**Status:** Entschieden — mlfinlab wird *nicht* als Dependency adoptiert.
**Verwandt:** ADR-0019 (Multi-Feature-Family-Score v2), `ml/README.md`,
`docs/SPRINT_PLAN_C10_ML_LAYER_2026-04-26.md`, ADR-0014, ADR-0015.

---

## TL;DR (Verdikt)

mlfinlab **nicht** als Dependency aufnehmen. Zwei harte Gründe, ein
nachgelagerter Befund:

1. **Lizenz/Maintenance:** mlfinlab ist seit ~5 Jahren nicht mehr Open
   Source. Das Public-Repo ist nur noch Issue-Tracker; die Bibliothek ist
   "all rights reserved" und nur über kostenpflichtige Business-/
   Enterprise-Lizenzen von Hudson & Thames verfügbar. Die PyPI-Version ist
   eingefroren und gegen alte numpy/pandas/sklearn gepinnt.
2. **Redundanz:** Die Kern-Bausteine sind bei uns bereits pure-numpy,
   getestet und an unseren Bar-Contract angepasst implementiert.
3. **Re-Priorisierung gegen den bindenden Blocker (siehe unten):** Der
   höchste-Hebel-Vorschlag der Erst-Analyse (Sample-Uniqueness-Gewichte)
   ist *kein* Resolution-Adder. Für unseren tatsächlichen Engpass
   (Discrimination) rangiert Fractional Differentiation davor.

Für ein Repo mit unserer Governance-Disziplin (Pin-Registry, Coverage-
Gates, Branch-Protection, upload-artifact-Allowlist) wäre eine
closed-source, ungepflegte, gegen alte Deps gepinnte Lib ein Fremdkörper
und ein Supply-Chain-Risiko.

---

## 1. Verifizierter Feature-Overlap (gegen Code geprüft, nicht behauptet)

Jede Zeile unten ist gegen den realen Code verifiziert:

| mlfinlab-Modul | Bei uns vorhanden | Verifiziert in |
| --- | --- | --- |
| Purged/Embargoed CV | ja | `ml/walkforward.py` (Embargo + per-sample `outcome_horizon`-Purging, LdP-Docstring) |
| Microstructure (VPIN, Imbalance) | ja | `ml/features/microstructure.py` (`vpin`, `bid_ask_imbalance`, `volume_imbalance`) |
| Volatility (Garman-Klass, Parkinson, Realized) | ja | `ml/features/volatility.py` |
| Triple-Barrier-Returns | ja | `governance/family_returns.py` (`realized_return`, Variante B) |
| Meta-Labeling / Kalibrierung | ja | `governance/family_calibration.py` (purged walk-forward) |
| Ensembling/Stacking | ja | `ml/stacking/meta_learner.py` |
| Deflated Sharpe / PSR | ja | `stats_helpers.py`, `open_prep/psr_robust.py` |
| Probability-Calibration / Conformal | ja | `ml/calibration/` |
| Drift (PSI) | ja | `ml/drift/`, `ml/metrics.py` |
| Hyperparam-Tuning | ja | `scripts/run_ml_optuna_tuning.py` |
| Feature-Importance | ja | SHAP gepinnt in `requirements-ml.txt` |

## 2. Verifizierte echte Lücken (existieren tatsächlich *nicht*)

Eine Repo-weite Suche bestätigt: kein `frac_diff`, keine
`sequential_bootstrap`/Sample-Uniqueness, keine `time_decay`-Sample-
Weights, keine Trend-Scanning-Labels, kein CUSUM/SADF als ML-Modul.
(CUSUM taucht nur im Regime-Drift-Kontext der Doku auf, nicht als
Labeling.) Die Lücken sind real — aber jede ist in <1 Datei pure-numpy
selbst baubar.

---

## 3. Ehrlicher Review — Re-Priorisierung gegen den bindenden Blocker

**Der bindende Promotion-Blocker ist Resolution (Discrimination), nicht
Kalibrierung und nicht Overfitting.** Murphy-Zerlegung:
Brier = Reliability − Resolution + Uncertainty. Die Erst-Analyse hat die
Lücken korrekt benannt, sie aber *nicht* gegen diesen Engpass sortiert.
Korrektur:

### (A) Fractional Differentiation — der einzige echte Resolution-Kandidat

Ein stationäres-aber-memory-erhaltendes Feature kann prädiktives Signal
tragen, das vollständig differenzierte Returns zerstören. Das ist genau
das richtige Werkzeug gegen einen *Discrimination*-Defizit. ~40 Zeilen
numpy. **Direkt durch den ADR-0019-A/B-Harness testbar** — es ist nur ein
weiterer `feature_key` für `extract_family_ab_samples` / `family_feature_ab`.
Niedriger Aufwand, höchster Erwartungswert *für den Blocker*.

### (B) Sample-Uniqueness / Time-Decay-Weights — Mess-Integrität, KEIN Signal

**Ehrliche Korrektur der Erst-Analyse:** Sie rankt dies als "höchster
Hebel". Das stimmt *nicht* für unseren Blocker. Overlap-Gewichtung fügt
**kein** diskriminatives Signal hinzu und hebt Resolution nicht. Was sie
tut: sie schützt die OOS-Schätzung gegen optimistische Verzerrung bei
**überlappenden** Triple-Barrier-Labels — exakt unser Fall, weil
`extract_family_ab_samples` `forward_timestamps`/`guard_end_ts`-Fenster
emittiert, die sich überlappen. Damit ist sie ein **Guardrail für die
Ehrlichkeit von `walk_forward_ab` (Slice 3)**, kein Signal-Spiel. Wertvoll
— aber als Mess-Härtung einzuordnen, nicht als Resolution-Hebel. Diese
Unterscheidung ist der Unterschied zwischen ehrlichem Fortschritt und
Goalpost-Verschiebung.

### (C) Trend-Scanning-Labels / Information-driven Bars — spekulativ, später

Alternative Label-/Bar-Definition. Ändert das Ziel bzw. die Sampling-
Achse; kann helfen oder schaden. Nur relevant, falls wir Zeit-Bars
wirklich ablösen. Nicht jetzt.

---

## 4. Action Plan

Priorisiert nach Hebel *auf den Resolution-Blocker*, angedockt an den
bereits gelieferten ADR-0019-A/B-Harness (PR #2528).

1. **Fractional Differentiation als optionaler Feature-Transform.**
   - Neues Modul `ml/features/frac_diff.py` (pure-numpy, FFD nach LdP
     ch. 5: feste Fenster-Gewichte, Threshold-Cutoff).
   - Property-Tests: Gewichte konvergieren, Output-Länge alignt, `d=0`
     ist Identität, `d=1` ≈ erste Differenz.
   - Anbindung: als `feature_key`-Kandidat durch
     `governance/family_feature_ab.family_feature_ab` laufen lassen —
     Verdikt `candidate_lifts_resolution` oder ehrliches `no_lift`.
   - Gate-Disziplin: `SCORE_SOURCE` bleibt v1-Default bis der A/B auf
     echten Daten besteht. Kein erfundenes Feature-Gewicht.

2. **Overlap-/Uniqueness-Gewichte als Mess-Härtung von `walk_forward_ab`.**
   - Average-Uniqueness aus den überlappenden `guard_end_ts`-Fenstern
     (LdP ch. 4), als optionales Sample-Gewicht in den OOS-Metriken.
   - Eingeordnet als *Integritäts-Guardrail* der A/B-Schätzung, nicht als
     Resolution-Lift. Erst nach (1), damit der A/B-Vergleich selbst
     unverzerrt wird.

3. **Nicht tun:** mlfinlab einbinden; nachbauen, was wir schon haben;
   Trend-Scanning/Information-Bars vor einem echten Bedarf.

4. **Referenzen statt Lib:** Quelle bleibt López de Prado 2018 (das Buch,
   nicht die Lib). Für lizenzfreien Vergleichscode: MIT-Fork `mlfinpy`
   bzw. `RiskLabAI` — nur als Referenz, nicht als Dependency.

---

## 5. Konsequenzen

**Positiv:** kein Supply-Chain-/Lizenz-Risiko; kein Dep-Konflikt mit
unserem gepinnten Stack; der nächste Feature-Kandidat (frac-diff) hat
bereits eine messende Heimat (ADR-0019-Harness) und ein ehrliches
Stop-Kriterium (`no_lift`).

**Negativ:** Wir tragen die Wartung der selbst gebauten Bausteine. Das ist
akzeptiert — jeder ist <1 Datei, pure-numpy und an unseren Bar-Contract
angepasst, mit eigener Test-Abdeckung.
