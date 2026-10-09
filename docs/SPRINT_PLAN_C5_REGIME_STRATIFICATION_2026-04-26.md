# Sprint-Plan C5 — Regime-Stratifikation der Strategie-Performance

Datum: 2026-04-26 · Sprint-Reihe: Track-Record-Machbarkeitsplan · Aktueller Sprint: C5 von C1–C9

Evidenz-Marker: ✅ im Code belegt · 🧪 getestet · ⚙️ operativ · ⚠ nur plausibel

## Ziel-Framework (aus Machbarkeitsplan)

C5 liefert keine eigene Mindestkennzahl direkt — sondern eine **kondiitonale Lesart aller Kennzahlen aus C2–C4**. Konkret: dass eine Strategie mit aggregiertem Sharpe = 1.0 in einem Regime Sharpe = 1.8 hat und in einem anderen Sharpe = -0.4, ist [eines der unterschätztesten Risiken im systematischen Trading](https://regimeforecast.com/blog/regime-dependent-strategy-performance). Wenn der Backtest-Zeitraum zufällig durch ein bestimmtes Regime dominiert ist, bricht die Live-Performance ein, sobald sich das Regime verschiebt — ohne dass sich am Setup etwas geändert hat.

C5 macht diesen Effekt sichtbar und macht das Track-Record-Gate **regime-bewusst statt regime-naiv**.

| Metrik aus Track-Record-Gate | Wirkung von C5 |
|---|---|
| Sharpe ≥ 1.0 (C2) | Regime-konditional: pro Regime Sharpe-Wert |
| Bootstrap-CI (C3) | Pro Regime separat berechnet |
| Permutation-p (C4) | Pro Regime separat geprüft |
| Walk-Forward-Efficiency (C2) | Pro Regime separat |
| Max DD (C2) | Pro Regime — typisch deutlich höher in adversen Regimen |
| Win-Rate (C1) | Pro Regime |
| FDR-Rate (C4) | Über Setup × Regime statt nur Setup |

⚠ Wichtige Konsequenz: C5 kann den scheinbaren Pass von C2/C3/C4 **invalidieren**, wenn sich zeigt, dass die positive Aggregat-Sharpe in nur 1 Regime konzentriert ist und in den anderen negativ. Das ist ein Feature, kein Bug.

## Sprint-Übersicht

- **Sprint-Dauer:** 5–10 Werktage (Basis), 4–7 mit Speed-Stack ⚠
- **Sprint-Typ:** Erweiterung des bestehenden ✅ Regime-Klassifikators in `open_prep/regime.py` um Per-Trade-Regime-Labels und Stratifikation der C2/C3/C4-Pipelines
- **Trigger:** C2 in main gemerged, C3 oder C4 mindestens parallel begonnen
- **Definition of Done:** Pro Setup-Typ × pro Regime liefert das Calibration-Report `sharpe`, `sharpe_ci`, `permutation_p`, `n_trades`, `regime_frequency`, `regime_transition_drawdown` als Felder

## Inventur — was bereits existiert

⚠ Inventur-Tag-1-Disziplin:

| Komponente | Status | Pfad |
|---|---|---|
| RISK_ON / RISK_OFF / ROTATION / NEUTRAL Klassifikator (VIX + macro_bias + breadth) | ✅ existiert | `open_prep/regime.py:26-228` |
| TRENDING / RANGING per-Symbol-Klassifikator (ADX + BB-Width) | ✅ existiert | `open_prep/regime.py:263-298` und `open_prep/technical_analysis.py:184` |
| `RegimeSnapshot` Datacontainer | ✅ existiert | `open_prep/regime.py:42` |
| VIX-Hysterese gegen Flicker-Flips | ✅ existiert | `open_prep/regime.py:38, 200-208` |
| Vol-Regime-Labels (`NORMAL`, `EXTREME`, `LOW_VOL`) | ✅ in Tests sichtbar | `tests/test_smc_regime_classifier.py:152-180` |
| `regime` Feld in Outcome-Records | ✅ existiert | `open_prep/outcomes.py:262` |
| Per-Trade-Regime-Snapshot zum Entry-Zeitpunkt | ⚠ teilweise — abhängig von Outcome-Snapshot-Vollständigkeit | tbd-Audit in T1 |
| Regime-Transition-Detection (Day-over-Day Wahrscheinlichkeitsdelta) | ❌ fehlt | — |
| HMM- oder Markov-Switching-Modell | ❌ fehlt | — |
| Regime-Conditional-Sharpe-Aggregation | ❌ fehlt | — |
| Regime-frequency-Ausgleich für aggregierte Metrik | ❌ fehlt | — |

Konsequenz: Die **Regime-Detection** ist solide etabliert, was fehlt ist die **Stratifikation**. C5 ist also primär ein Pipeline-Sprint, nicht ein Modeling-Sprint. Das ist gut — Modeling-Risiko ist niedrig.

## Speed-Stack für diesen Sprint

1. **Reuse** des kompletten Regime-Klassifikators und der TRENDING/RANGING-Logik
2. **Joblib-Parallel** für die Regime-stratifizierte Bootstrap- und Permutations-Berechnung — pro Regime ein eigenständiger C3/C4-Aufruf
3. **NumPy-basierte Filter-Operationen** auf der Trade-Liste statt Python-Loops über Trades
4. **pytest-xdist** mit `--dist=loadfile`
5. **Inventur-Tag-1** — die Frage "ist `regime_at_entry` bereits in jedem Outcome-Record sauber gepflegt?" entscheidet über Sprint-Verlauf

## Tasks

### T1 — Inventur Per-Trade-Regime-Datenkontrakt (1 Werktag)

**Ziel:** Für jeden Trade in `artifacts/open_prep/outcomes/` ist eindeutig dokumentiert: welches Regime war zum Entry-Zeitpunkt aktiv?

**Akzeptanzkriterien:**
- ✅ Datei `docs/sprints/C5_REGIME_DATA_CONTRACT.md` listet pro Outcome-Record:
  - `regime_at_entry` — RISK_ON / RISK_OFF / ROTATION / NEUTRAL
  - `vol_regime_at_entry` — NORMAL / EXTREME / LOW_VOL / HIGH_VOL
  - `symbol_regime_at_entry` — TRENDING / RANGING
  - `vix_at_entry`, `macro_bias_at_entry`, `breadth_at_entry` — Rohwerte für Audit
- ✅ Diff zwischen tatsächlichen Outcome-Felder und C5-Requirements explizit
- ⚠ Wenn `regime_at_entry` nicht vorhanden: Backfill via Reconstruction aus historischen VIX/Macro-Daten — Datenquelle und Methode dokumentieren
- ⚠ Stop-Kriterium: wenn historische VIX-Daten nicht verfügbar oder Regime-Reconstruction nicht möglich → Sprint endet, Erkenntnis fließt in C2-Patch zurück

**Hinweis:** ✅ `open_prep/outcomes.py:262` hat schon ein `regime` Feld. Audit klärt, ob das durchgängig ausgefüllt ist und welche Regime-Dimension es speichert.

### T2 — Regime-Backfill (falls T1 Lücken zeigt) (2–3 Werktage, optional)

**Ziel:** Historische `regime_at_entry`-Labels für alle bestehenden Outcome-Records nachtragen.

**Akzeptanzkriterien:**
- ✅ Skript `scripts/backfill_regime_labels.py` lädt historische VIX (CBOE FRED-Datenquelle) und SPX-Breadth, ruft ✅ `classify_regime()` aus `open_prep/regime.py` auf, schreibt Labels in jedes Outcome-File zurück
- ✅ Idempotent: zweimaliges Ausführen ändert keine Daten
- ✅ Fail-Safe: bei fehlenden Eingangsdaten wird das Trade-Label auf `UNKNOWN` gesetzt, nicht auf Default-Regime — sonst Bias
- 🧪 Test: Backfill-Skript für 3 bekannte Tage (z. B. 2020-03-12 RISK_OFF, 2021-06-15 RISK_ON, 2022-09-20 RISK_OFF) erzeugt korrekte Labels

⚠ T2 ist nur nötig wenn T1 Lücken zeigt. Wenn `regime_at_entry` schon konsistent gepflegt ist, T2 überspringen.

### T3 — Regime-Stratifikations-Modul (2 Werktage)

**Ziel:** Neues Modul `scripts/regime_stratification.py`.

**Akzeptanzkriterien:**
- ✅ Funktion `stratify_trades_by_regime(trades: pd.DataFrame, *, regime_col: str = "regime_at_entry") -> dict[str, pd.DataFrame]` zerlegt Trade-Liste pro Regime
- ✅ Funktion `compute_regime_conditional_metrics(trades_per_regime: dict[str, pd.DataFrame], *, metric_fns: dict[str, Callable], min_n_per_regime: int = 30) -> dict`
  - Pro Regime: `sharpe`, `max_dd`, `win_rate`, `profit_factor`, `n_trades`, `regime_frequency_pct`
  - Falls n < `min_n_per_regime`: `{"skipped_reason": "insufficient_n", "n": ...}` — Konstante reusen aus `MIN_EVENTS_PER_ARM_FOR_BOOTSTRAP` ✅
- ✅ Funktion `compute_regime_aware_aggregate(per_regime: dict, *, freq_weighting: bool = True) -> dict` — gewichteter Aggregat-Sharpe nach Regime-Häufigkeit, für Vergleich gegen naive Aggregation
- ✅ Funktion `detect_regime_concentration(per_regime: dict, *, threshold: float = 0.8) -> dict` — flagt Setups, deren ≥80% Profit aus 1 Regime kommt → "Regime-Concentration-Warning"
- 🧪 Property-Test: gewichteter Aggregat-Sharpe bei gleichmäßiger Regime-Frequenz = Mittel der per-Regime-Sharpes

### T4 — Regime-stratifizierte C3/C4-Aufrufe (1–2 Werktage)

**Ziel:** Die Bootstrap-CI und Permutations-Pipelines aus C3 und C4 pro Regime separat aufrufen.

**Akzeptanzkriterien:**
- ✅ Funktion `regime_stratified_bootstrap(trades: pd.DataFrame, *, regime_col: str, **bootstrap_kwargs) -> dict[str, dict]` ruft pro Regime ✅ `sharpe_ci()` aus C3 auf
- ✅ Funktion `regime_stratified_permutation(trades: pd.DataFrame, *, regime_col: str, **perm_kwargs) -> dict[str, dict]` analog
- ✅ Aggregat über Regime: BH-FDR-Korrektur über alle Setup × Regime-Zellen via ✅ `benjamini_hochberg` aus `scripts/run_ab_comparison.py:182`
- 🧪 Power-Test: synthetisches Setup mit Edge nur in RISK_ON, kein Edge in RISK_OFF → C5 detektiert das Konzentrations-Pattern

### T5 — Regime-Transition-Frühwarnung als Stretch-Goal (2 Werktage, optional)

**Ziel:** Day-over-Day-Regime-Wechsel werden als Marker in den Outcome-Records gepflegt; Trades in Transition-Phasen werden separat ausgewertet.

**Akzeptanzkriterien:**
- ✅ Feld `is_in_regime_transition: bool` pro Trade — true wenn Regime-Label sich in den ±2 Tagen um Entry-Zeitpunkt geändert hat
- ✅ Performance-Vergleich: Sharpe pro Regime-state vs Sharpe in Transition-Phasen
- ⚠ Begründung: Quelle [RegimeForecast.com](https://regimeforecast.com/blog/regime-dependent-strategy-performance) zeigt, dass Transitions die Phase mit höchstem Tail-Risk sind. Wenn das Setup besonders in Transitions Verluste produziert, muss das gewusst werden, bevor Live-Trading geht.
- ⚠ Skippen wenn nach T1-T4 weniger als 3 Werktage übrig sind

### T6 — Test-Suite (1 Werktag)

**Akzeptanzkriterien:**
- 🧪 Synthetik-Test: bekannte Sharpe pro Regime → C5 produziert exakt diese Werte
- 🧪 Edge-Case: 1 Regime hat n=10 → wird mit `skipped_reason` markiert, kein Crash
- 🧪 Determinismus: gleiche Seeds → identische CIs/p-Werte
- 🧪 Property-Test: aggregierter Sharpe via `compute_regime_aware_aggregate(freq_weighting=True)` ≠ naive Aggregat-Sharpe wenn Regimes signifikant unterschiedlich performen
- 🧪 pytest-xdist mit `pytest -n auto --dist=loadfile`
- ⚙️ Wöchentlicher CI-Job `regime-stratification-validation.yml` mit Cron `0 9 * * 1` UTC

### T7 — Integration in Calibration-Report (0.5–1 Werktag)

**Akzeptanzkriterien:**
- ✅ Schema-Erweiterung in ✅ `scripts/emit_public_calibration_report.py` mit Feldern pro Setup × Regime:
  - `regime_stratified.<regime_label>.sharpe`
  - `regime_stratified.<regime_label>.sharpe_ci_low/high`
  - `regime_stratified.<regime_label>.permutation_p_value`
  - `regime_stratified.<regime_label>.n_trades`
  - `regime_stratified.<regime_label>.regime_frequency_pct`
  - `regime_stratified.aggregate_freq_weighted_sharpe`
  - `regime_stratified.regime_concentration_warning` (bool + reason)
  - `regime_stratified.fdr_q`, `regime_stratified.bh_rejected_cells`
- ✅ Pro `regime_label` ein eigener Block — sowohl für RISK_ON/OFF/ROTATION/NEUTRAL als auch für TRENDING/RANGING
- 🧪 Schema-Test

## Stop-Kriterien innerhalb des Sprints

- **Stop nach T1:** wenn `regime_at_entry` weder vorhanden noch backfillbar (z. B. weil historische VIX-Daten nicht zugänglich) → Sprint endet; C2-Patch nimmt das Feld ab dato auf, C5 wird in 3 Monaten retrospektiv durchgeführt
- **Stop nach T3:** wenn pro Regime n < 30 Trades vorhanden → Sprint stoppt, Erkenntnis ist Wert ("Track-Record für Regime-Conditional-Pass aktuell zu klein")
- **Stop nach T4:** wenn nach Stratifikation kein einziges Setup × Regime-Zelle den Track-Record-Gate passt → Sprint ist trotzdem fertig, das ist eine wichtige Strategie-Entscheidungs-Information
- **2-Iterations-Limit pro Task**

## Risiken

| Risiko | Wahrscheinlichkeit | Impact | Mitigation |
|---|---|---|---|
| `regime_at_entry` historisch nicht eindeutig | hoch | mittel | T2 Backfill mit FRED-VIX-Daten und dokumentierter Reconstruction-Methode |
| n pro Regime zu klein | hoch | hoch | min_n_per_regime=30 als Konstante; Stop-Kriterium T3 |
| Regime-Klassifikator selbst ist überangepasst | niedrig | mittel | ✅ existiert seit langem produktiv, VIX-Hysterese ✅ implementiert |
| Multiple-Testing-Inflation durch Setup × Regime-Zellen | mittel | hoch | BH-FDR über alle Zellen, q=0.10; Doku in T7 |
| Regime-Transition-Stretch (T5) frisst Zeit | niedrig | niedrig | T5 ist optional |
| Backfill-Datenquelle fehlt (FRED-API down) | niedrig | mittel | Mock-Cache, idempotenter Backfill |

## Speed-Erwartung

| Setup | Realistische Dauer |
|---|---|
| Ohne Reuse, ohne Speed-Stack | 8–12 Werktage |
| Mit Reuse + KI-Tool | 5–8 Werktage |
| Plus joblib + NumPy + Inventur-Tag-1 | 4–7 Werktage |
| Plus T2 Backfill nötig | +2–3 Werktage |

## Definition of Done — Sprint C5

- ✅ `scripts/regime_stratification.py` existiert
- ✅ Pro Setup-Typ × pro Regime liefert das Calibration-Report die Felder aus T7
- 🧪 Synthetik-Tests grün (bekannte Sharpe pro Regime exakt rekonstruiert)
- ⚙️ Wöchentlicher Cron `regime-stratification-validation.yml` läuft 1× erfolgreich
- ⚙️ PR ist gemerged
- ⚠ T5 (Regime-Transition) ist Stretch — DoD passt auch ohne

## Übergabe an Folge-Sprints

- C6 (Probabilistic-Sharpe + MinTRL): erhält pro-Regime-Sharpe als Input und kann MinTRL pro Regime statt nur aggregat berechnen
- C7 (Dashboard-Frontend): liest `regime_stratified.*`-Felder; Multi-Heatmap pro Setup × Regime
- C8 (Live-Incubation): Position-Sizing pro Regime-Wahrscheinlichkeit ([Guidolin & Timmermann 2007](https://regimeforecast.com/blog/regime-dependent-strategy-performance))
- C9 (Drift-Alert): vergleicht aktuelle Live-Performance pro Regime gegen Backtest-CI pro Regime — viel sensitiver als Aggregat-Vergleich

## Quellen

- [RegimeForecast — Why Your Strategy Has 1.8 Sharpe in Trending and -0.4 Else](https://regimeforecast.com/blog/regime-dependent-strategy-performance)
- [CXO Advisory — Regime-Optimal Trend Following (Zakamulin 2026)](https://www.cxoadvisory.com/technical-trading/regime-optimal-trend-following/)
- [Macro Ops — Six Market Regimes Framework (Bull/Bear/Neutral × Quiet/Volatile)](https://macro-ops.com/the-sunday-setup/)
- [OpenReview — Dynamic Regime Shifts in Factor Models (2025)](https://openreview.net/forum?id=Wu0W5BJ7UR)
- [Sciencedirect — Robust Rule-based Bull/Bear Regime Detection](https://www.sciencedirect.com/science/article/abs/pii/S0275531921002245)
- Repo-Inventur: ✅ `open_prep/regime.py:26-298` Klassifikator, `open_prep/technical_analysis.py:184` Symbol-Regime, `open_prep/outcomes.py:262` regime-Feld
