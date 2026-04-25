# Sprint-Plan C3 — Bootstrap-Konfidenzintervalle für Sharpe und MaxDD

Datum: 2026-04-26 · Sprint-Reihe: Track-Record-Machbarkeitsplan · Aktueller Sprint: C3 von C1–C9

Evidenz-Marker: ✅ im Code belegt · 🧪 getestet · ⚙️ operativ · ⚠ nur plausibel

## Ziel-Framework (aus Machbarkeitsplan)

C3 liefert genau eine der neun Mindestkennzahlen direkt — die untere Grenze des **Bootstrap-95%-Konfidenzintervalls für Sharpe > 0.3**. Diese Zahl ist das eigentliche Risiko-Gate des gesamten Track-Record-Machbarkeitsplans. Eine Sharpe-Punktschätzung ohne CI ist statistisch wertlos, weil sie nicht zwischen "echt profitabel" und "Glück bei kleinem n" unterscheidet.

| Metrik | Mindestwert | Sprint, der sie liefert |
|---|---|---|
| Out-of-Sample Trades (n) | ≥ 100, idealer ≥ 200 | C1 + C2 |
| Trade-Win-Rate | ≥ 55% (R/R = 1) oder ≥ 45% (R/R ≥ 1.5) | C1 |
| Sharpe Ratio (annualisiert) | ≥ 1.0 | C2 |
| **Bootstrap-95%-CI für Sharpe (untere Grenze)** | **> 0.3** | **C3** |
| Max Drawdown | < 15% | C2 |
| FDR-Rate | < 10% | C4 |
| Walk-Forward-Efficiency | > 50% | C2 |
| Track-Record-Länge live | ≥ 3 Monate, idealer 6 | C8 |
| Permutation-Test p-Value | < 0.05 | C4 |

## Sprint-Übersicht

- **Sprint-Dauer:** 4–6 Werktage (Basis), 3–4 mit Speed-Stack ⚠
- **Sprint-Typ:** Erweiterung des FDR-Bootstrap-Designs auf Sharpe + MaxDD; reuse der bestehenden FDR-Primitive
- **Trigger:** C2 in main gemerged, OOS-Trade-Liste pro Setup-Typ verfügbar
- **Definition of Done:** Pro Setup-Typ sind `sharpe_ci_low`, `sharpe_ci_high`, `max_dd_ci_low`, `max_dd_ci_high` als Felder in `docs/calibration/calibration_report_public.json` veröffentlicht und im CI getestet

## Inventur — was bereits existiert

⚠ Inventur-Tag-1-Disziplin (Speed-Hebel):

| Komponente | Status | Pfad |
|---|---|---|
| Benjamini-Hochberg FDR | ✅ existiert | `scripts/run_ab_comparison.py:182-235` |
| Fisher-Permutation mit Phipson-Smyth | ✅ existiert | `scripts/run_ab_comparison.py:409-462` |
| `_calibration_fdr_layer` Orchestrator | ✅ existiert | `scripts/run_ab_comparison.py:476-600` |
| Bootstrap-Design-Skizze | ✅ existiert | [BOOTSTRAP_CALIBRATION_FDR_DESIGN_2026-04-24.md](sandbox:/home/user/workspace/BOOTSTRAP_CALIBRATION_FDR_DESIGN_2026-04-24.md) |
| `BOOTSTRAP_B`, `BOOTSTRAP_SEED`, `MIN_EVENTS_PER_ARM_FOR_BOOTSTRAP` Konstanten | ✅ existiert | `scripts/run_ab_comparison.py:358-369` |
| Stationary / Block-Bootstrap (Politis-Romano) | ❌ fehlt | — |
| BCa-CI (bias-corrected and accelerated) | ❌ fehlt | — |
| Sharpe-CI mit Skew/Kurtosis-Korrektur | ❌ fehlt | — |
| Per-Setup-Trade-Returns-Pipeline | ❌ fehlt (kommt aus C2) | — |
| `scipy` als Dependency | ⚠ tbd | grep in `requirements.txt` |

Konsequenz: ~50% Reuse, neue Module nur für **stationary block bootstrap** und **BCa-Korrektur** und **Sharpe-Studentized-CI** nach [Ledoit & Wolf (2008)](http://www.ledoit.net/jef_2008pdf.pdf).

## Speed-Stack für diesen Sprint

1. **Reuse-Disziplin Tag 1**: bestehende Permutation/BH-Helfer als Basis, kein zweiter Implementierungspfad.
2. **joblib.Parallel** für Bootstrap-Loop (B = 5.000–10.000 Resamples).
3. **NumPy-vektorisierte Resampling** statt Python-Loops — der einzige Hebel, der hier wirklich zählt.
4. **pytest-xdist** mit `--dist=loadfile` für Test-Suite.
5. **2-Iterations-Limit pro Task**.

## Tasks

### T1 — Inventur und Bootstrap-Methoden-Wahl (1 Werktag)

**Ziel:** Festlegen, welche Bootstrap-Variante pro Metrik verwendet wird.

**Akzeptanzkriterien:**
- ✅ Datei `docs/sprints/C3_BOOTSTRAP_METHOD_CHOICE.md` listet pro Metrik die gewählte Methode mit Begründung:
  - **Sharpe**: Studentized stationary bootstrap nach [Ledoit & Wolf](http://www.ledoit.net/jef_2008pdf.pdf), Block-Length-Mean = 5 (Empfehlung Politis & Romano 1994). Begründung: Auto-Korrelation in Trade-Renditen ist real, IID-Bootstrap unterschätzt Varianz.
  - **MaxDD**: Stationary block bootstrap auf Equity-Path; CI über Resampling der Trade-Sequenz, nicht Trade-Renditen einzeln. Begründung: MaxDD ist Pfad-abhängig.
  - **Win-Rate / Profit-Factor**: Klassischer IID-Bootstrap (BCa). Begründung: Win-Rate ist Mean einer Bernoulli-Reihe, kaum auto-korreliert.
- ✅ Alternative-Path-Diskussion: warum nicht parametrisch (Normal-Approx) und nicht Delta-Method
- ⚠ Falls C2-Output keine Trade-Timestamps liefert (siehe C2/T1): Stop und Patch in C2 priorisieren

**Methodische Begründung:** [Quantpedia](https://quantpedia.com/in-sample-vs-out-of-sample-analysis-of-trading-strategies/) zeigt Sharpe-Decay 33–44% IS→OOS. Bei OOS-n=100 und Sharpe=1.0 ist die naive 95%-Normal-CI bei `[0.20, 1.80]` — also schon der naive CI gefährdet das Gate. Heavy-Tail-Returns und Auto-Korrelation drücken die untere Grenze typisch um weitere 10–30%.

### T2 — Stationary Block Bootstrap Modul (1–2 Werktage)

**Ziel:** Neues Modul `scripts/bootstrap_methods.py`.

**Akzeptanzkriterien:**
- ✅ `stationary_block_bootstrap(returns: np.ndarray, *, mean_block_length: int = 5, B: int = 5000, seed: int = 42) -> np.ndarray`
- ✅ Algorithmus nach [Politis & Romano (1994)](http://www.ledoit.net/jef_2008pdf.pdf): jeder Block hat geometrisch verteilte Länge mit Mean = `mean_block_length`. Block-Start uniform zufällig im Sample.
- ✅ NumPy-vektorisiert: `np.random.geometric` für Block-Längen, `np.random.randint` für Block-Starts, einmaliges Index-Array statt Python-Loop
- ✅ Output: Matrix `(B, n)` von Resamples
- ✅ Optional: `circular_block_bootstrap` als Variante (für Vergleichbarkeit mit Ledoit-Wolf-Paper)
- 🧪 Determinismus-Test: gleicher Seed → identische Resamples
- 🧪 Statistik-Test: für AR(1)-Prozess mit ρ=0.3 produziert Bootstrap-CI breitere Streuung als IID-Bootstrap

### T3 — Sharpe-CI mit Studentized Bootstrap (1–2 Werktage)

**Ziel:** Neues Modul `scripts/performance_inference.py` mit Sharpe-CI + MaxDD-CI + Win-Rate-CI.

**Akzeptanzkriterien:**
- ✅ `sharpe_ci(returns: np.ndarray, *, alpha: float = 0.05, freq: int = 252, B: int = 5000, mean_block_length: int = 5, method: Literal["studentized", "bca", "percentile"] = "studentized") -> dict[str, float]`
  - Output: `{"sharpe": float, "ci_low": float, "ci_high": float, "ci_method": str, "B": int, "block_length": int}`
- ✅ Studentized-Variante: für jedes Resample wird `(SR* - SR) / SE(SR*)` berechnet; CI ist `[SR - q_{1-α/2} * SE(SR), SR - q_{α/2} * SE(SR)]`
- ✅ BCa-Variante als Fallback bei sehr kleinem n
- ✅ `max_dd_ci(equity_curve: np.ndarray, *, trades: np.ndarray, ...) -> dict` analog
- ✅ `win_rate_ci(outcomes: np.ndarray, ...) -> dict` mit klassischem IID-Bootstrap + BCa
- ✅ `profit_factor_ci(pnl: np.ndarray, ...) -> dict` analog
- 🧪 Sharpe-CI gegen [Ledoit-Wolf-Beispiel](http://www.ledoit.net/jef_2008pdf.pdf) (Block-Length 5) — Toleranz 5%
- 🧪 Coverage-Test: für simulierte Normal-Returns mit bekanntem Sharpe deckt 95%-CI in 100 Replikationen ≥90% der Fälle ab

⚠ Wenn n < 30 Trades pro Setup: CI-Berechnung wird übersprungen, Output `{"skipped_reason": "insufficient_trades"}`. Konstante in `scripts/run_ab_comparison.py:MIN_EVENTS_PER_ARM_FOR_BOOTSTRAP` ✅ existiert — wiederverwenden.

### T4 — Multiple-Testing-Korrektur über Setup-Typen (1 Werktag)

**Ziel:** Wenn mehrere Setup-Typen gleichzeitig getestet werden (z. B. 5 SMC-Familien), CI-Aggregation mit BH-FDR.

**Akzeptanzkriterien:**
- ✅ Funktion `aggregate_setup_cis(setup_results: dict[str, dict]) -> dict` ruft ✅ `benjamini_hochberg` aus `scripts/run_ab_comparison.py` auf
- ✅ Pro Setup-Typ wird der einseitige p-Wert "Sharpe > 0" mittels Studentized-Bootstrap berechnet, dann BH-FDR über alle Setups
- ✅ Output: `{setup: {"sharpe_ci": ..., "p_value_one_sided": ..., "bh_adjusted": ..., "rejects_h0": ...}}`
- ⚠ Begründung: Wenn 5 Setups getestet werden und nur 1 zeigt Sharpe > 0 mit naivem p < 0.05, ist die Familienfehlerrate ohne Korrektur deutlich erhöht. BH-FDR auf q=0.10 ist der Standard ([Bailey & Lopez de Prado / Deflated Sharpe](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) machen das Gleiche, etwas konservativer)

### T5 — Test-Suite (1 Werktag)

**Akzeptanzkriterien:**
- 🧪 Coverage-Test: 95%-CI deckt true Sharpe in 100 Monte-Carlo-Replikationen ≥90% ab
- 🧪 Determinismus: gleicher Seed → identische CIs
- 🧪 Edge-Case: n=10 Trades → `skipped_reason: "insufficient_trades"`
- 🧪 Edge-Case: alle Returns identisch → CI degeneriert nicht (Test prüft kein NaN/inf)
- 🧪 Property-Test: für 100 zufällige (B, mean_block_length, alpha)-Kombinationen ist `ci_low ≤ sharpe ≤ ci_high`
- 🧪 pytest-xdist mit `pytest -n auto --dist=loadfile`
- ⚙️ Wöchentlicher CI-Job `bootstrap-ci-validation.yml` mit Cron `0 7 * * 1` emittiert CIs

### T6 — Integration in Calibration-Report (0.5–1 Werktag)

**Akzeptanzkriterien:**
- ✅ Schema-Erweiterung in ✅ `scripts/emit_public_calibration_report.py` mit Feldern pro Setup:
  - `bootstrap.sharpe_ci_low`, `bootstrap.sharpe_ci_high`
  - `bootstrap.max_dd_ci_low`, `bootstrap.max_dd_ci_high`
  - `bootstrap.win_rate_ci_low`, `bootstrap.win_rate_ci_high`
  - `bootstrap.profit_factor_ci_low`, `bootstrap.profit_factor_ci_high`
  - `bootstrap.method`, `bootstrap.B`, `bootstrap.alpha`, `bootstrap.bh_adjusted_p`, `bootstrap.bh_rejects_h0`
- 🧪 Schema-Test: Report ist JSON-Schema-validierbar

## Stop-Kriterien innerhalb des Sprints

- **Stop nach T1:** Wenn C2-Output keine sauberen Trade-Returns mit Timestamps liefert — C2-Patch wird priorisiert, C3 verschoben
- **Stop nach T3:** Wenn Coverage-Test < 80% trotz Methodenwahl — methodische Annahmen prüfen, ggf. Bootstrap-Variante wechseln
- **Stop nach T4:** Wenn nach BH-Korrektur kein Setup mehr signifikant ist — Sprint ist trotzdem fertig, Erkenntnis ist Wert
- **2-Iterations-Limit pro Task** wie in C1 / C2

## Risiken

| Risiko | Wahrscheinlichkeit | Impact | Mitigation |
|---|---|---|---|
| n zu klein für brauchbare CIs | hoch | hoch | Stop-Kriterium nach T1, MIN_EVENTS_PER_ARM_FOR_BOOTSTRAP-Konstante reusen |
| scipy nicht in `requirements.txt` | mittel | niedrig | bei Bedarf nur `scipy.stats.norm.ppf`, sonst eigene Implementation in NumPy |
| Bootstrap-Verzerrung bei Heavy-Tails | mittel | mittel | Studentized > Percentile, BCa als Fallback |
| Unklare Kovarianz-Struktur in Trade-Returns | mittel | mittel | Block-Length 5 als konservativer Default; Sensitivität in T5 testen |
| Multiple-Testing erhöht False-Negatives | niedrig | hoch | BH ist weniger konservativ als Bonferroni; q=0.10 statt 0.05 als Default |

## Speed-Erwartung

| Setup | Realistische Dauer |
|---|---|
| Ohne Reuse, ohne Speed-Stack | 7–9 Werktage |
| Mit Reuse + KI-Tool | 4–6 Werktage |
| Plus joblib + NumPy-Vektorisierung | 3–4 Werktage |

## Definition of Done — Sprint C3

- ✅ `scripts/bootstrap_methods.py` und `scripts/performance_inference.py` existieren
- ✅ Pro Setup-Typ liefern Bootstrap-CIs für Sharpe, MaxDD, Win-Rate, Profit-Factor in `docs/calibration/calibration_report_public.json`
- 🧪 Coverage-Test ≥90% in Monte-Carlo-Replikationen
- ⚙️ Wöchentlicher Cron läuft 1× erfolgreich
- ⚙️ PR ist gemerged

## Quellen

- [Ledoit & Wolf (2008) — Robust Performance Hypothesis Testing with the Sharpe Ratio (PDF)](http://www.ledoit.net/jef_2008pdf.pdf)
- [Bailey & Lopez de Prado — Deflated Sharpe Ratio (PDF)](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)
- [Two Sigma — Sharpe Ratio: Estimation, Confidence Intervals, Hypothesis Testing (PDF)](https://www.twosigma.com/wp-content/uploads/sharpe-tr-1.pdf)
- [QuantDare — Deflated Sharpe Ratio mit Python](https://quantdare.com/deflated-sharpe-ratio-how-to-avoid-been-fooled-by-randomness/)
- [Quantpedia — IS vs OOS Sharpe-Decay 33–44%](https://quantpedia.com/in-sample-vs-out-of-sample-analysis-of-trading-strategies/)
- [Noma et al. (2021) — Bootstrap-CI für Prediction-Accuracy (arXiv 2005.01457)](https://arxiv.org/abs/2005.01457)
- [PortfolioOptimizer.io — Probabilistic Sharpe Ratio](https://portfoliooptimizer.io/blog/the-probabilistic-sharpe-ratio-bias-adjustment-confidence-intervals-hypothesis-testing-and-minimum-track-record-length/)
- Repo-Inventur: ✅ `scripts/run_ab_comparison.py:182` `benjamini_hochberg`, `:409` `_permutation_p_delta_metric`, `:476` `_calibration_fdr_layer`, `:358-369` Konstanten
