# Sprint-Plan C4 — Permutations-Test für Strategie-Signifikanz

Datum: 2026-04-26 · Sprint-Reihe: Track-Record-Machbarkeitsplan · Aktueller Sprint: C4 von C1–C9

Evidenz-Marker: ✅ im Code belegt · 🧪 getestet · ⚙️ operativ · ⚠ nur plausibel

## Ziel-Framework (aus Machbarkeitsplan)

C4 liefert genau zwei der neun Mindestkennzahlen:

- **Permutations-Test p-Value < 0.05** — der entscheidende Beleg, dass die Strategie nicht durch Zufall profitabel wirkt
- **FDR-Rate < 10%** — Familienfehlerrate über mehrere getestete Setup-Typen

| Metrik | Mindestwert | Sprint, der sie liefert |
|---|---|---|
| Out-of-Sample Trades (n) | ≥ 100, idealer ≥ 200 | C1 + C2 |
| Trade-Win-Rate | ≥ 55% (R/R = 1) oder ≥ 45% (R/R ≥ 1.5) | C1 |
| Sharpe Ratio (annualisiert) | ≥ 1.0 | C2 |
| Bootstrap-95%-CI für Sharpe (untere Grenze) | > 0.3 | C3 |
| Max Drawdown | < 15% | C2 |
| **FDR-Rate** | **< 10%** | **C4** |
| Walk-Forward-Efficiency | > 50% | C2 |
| Track-Record-Länge live | ≥ 3 Monate, idealer 6 | C8 |
| **Permutation-Test p-Value** | **< 0.05** | **C4** |

## Sprint-Übersicht

- **Sprint-Dauer:** 3–5 Werktage (Basis), 2–4 mit Speed-Stack ⚠
- **Sprint-Typ:** Erweiterung der bestehenden ✅ `_permutation_p_delta_metric` (Calibration-FDR) auf Strategie-Performance-Permutation; reuse der BH-FDR-Pipeline
- **Trigger:** C2 in main gemerged, OOS-Trade-Liste pro Setup-Typ verfügbar. C3 nicht zwingend Voraussetzung — kann parallel laufen
- **Definition of Done:** Pro Setup-Typ ist ein Permutations-p-Value für "Sharpe ≠ 0" (oder Profit-Factor > 1) in `docs/calibration/calibration_report_public.json` plus BH-adjustiertem p

## Inventur — was bereits existiert

⚠ Inventur-Tag-1-Disziplin:

| Komponente | Status | Pfad |
|---|---|---|
| Fisher-Permutation auf Calibration-Metriken (Brier/ECE) | ✅ existiert | `scripts/run_ab_comparison.py:409-462` |
| Phipson-Smyth `(r+1)/(B+1)`-Korrektur | ✅ existiert | `scripts/run_ab_comparison.py:461` |
| Benjamini-Hochberg FDR | ✅ existiert | `scripts/run_ab_comparison.py:182-235` |
| `_calibration_fdr_layer` Orchestrator (zwei-Arm-Vergleich) | ✅ existiert | `scripts/run_ab_comparison.py:476-600` |
| `BOOTSTRAP_B`, `BOOTSTRAP_SEED`, `MIN_EVENTS_PER_ARM_FOR_BOOTSTRAP` | ✅ existiert | `scripts/run_ab_comparison.py:358-369` |
| White's Reality-Check / SPA-Test | ❌ fehlt | — |
| Permutation auf Strategie-vs-Random-Benchmark | ❌ fehlt | — |
| Time-Series-Permutation (Block-Permutation) | ❌ fehlt | — |
| Per-Trade Entry/Exit Reshuffle gegen Hold-Periode | ❌ fehlt | — |

Konsequenz: ~60% Reuse der FDR-Primitive. Der konzeptionell wichtigste neue Schritt: die richtige **Null-Hypothese** und das richtige **Permutationsschema** wählen.

## Speed-Stack für diesen Sprint

1. **Reuse** der ✅ Phipson-Smyth-Korrektur und ✅ BH-FDR aus `scripts/run_ab_comparison.py`
2. **NumPy-vektorisierte Permutationen** (B = 5.000–10.000) statt Python-Loop
3. **joblib.Parallel** für Permutations-Loop, falls IO-bound
4. **pytest-xdist** für Test-Suite
5. **Stretch-Goal**: White's Reality-Check als zusätzliche Defense gegen Selection-Bias

## Tasks

### T1 — Inventur und Permutationsschema-Wahl (0.5–1 Werktag)

**Ziel:** Festlegen, was genau permutiert wird und gegen welche Null-Hypothese.

Permutations-Tests für Strategien haben drei klassische Schemata:

**Schema A — Trade-Outcome-Permutation (klassisch / einfach)**
- Null-Hypothese H0: Trade-Renditen sind austauschbar gegen zufällige Zuordnung der Vorzeichen
- Permutation: shufflen der Trade-Renditen mit randomisierten Vorzeichen, Sharpe neu berechnen
- Begründung: Tests "ist die Sharpe-Verteilung dieser Trades vom Zufall unterscheidbar?"
- ⚠ Schwäche: berücksichtigt keine Markt-Drift / kein Zeitreihen-Verhalten

**Schema B — Entry-Time-Permutation (rigoros / empfohlen)**
- Null-Hypothese H0: Setup-Detection ist zufällig — gleicher Bias-Pfad würde mit zufälligen Entry-Zeitpunkten dasselbe Ergebnis liefern
- Permutation: gleiche Anzahl Entries, aber zufällig im Markt verteilt, gleicher Hold-Zeitraum, gleicher Symbol-Universum
- Begründung: Tests "schlägt das Setup einen zufälligen Random-Entry-Benchmark?" — die wirklich relevante Frage
- Quelle: [White's Reality Check / Aronson](https://financial-hacker.com/whites-reality-check/), [USU SPA-Thesis](https://digitalcommons.usu.edu/cgi/viewcontent.cgi?article=2535&context=gradreports)

**Schema C — Block-Permutation für AR-Returns**
- Null-Hypothese H0: Returns sind blockweise austauschbar (Auto-Korrelation berücksichtigt)
- Permutation: Block-Permutation mit Block-Mean-Length 5
- ⚠ Komplexer, nur wenn Auto-Korrelation in Trade-Returns nachgewiesen ist (aus C3-Inventur)

**Akzeptanzkriterien T1:**
- ✅ Datei `docs/sprints/C4_PERMUTATION_SCHEMA_CHOICE.md` listet pro Setup-Typ das gewählte Schema
- ✅ Default: **Schema B** für die Hauptmetrik (Setup-Signifikanz), **Schema A** als günstige Sanity-Check-Alternative
- ✅ Schema C nur bei nachgewiesener Auto-Korrelation > 0.2
- ✅ Begründung dokumentiert, welche Daten Schema B braucht (Bar-Daten, Symbol-Liste, Hold-Period-Länge)
- ⚠ Stop-Kriterium: wenn C1/C2 keine Symbol-Liste und Hold-Period-Länge pro Trade liefern → C2-Patch priorisieren

### T2 — Strategie-Permutations-Modul (1–2 Werktage)

**Ziel:** Neues Modul `scripts/strategy_permutation.py`.

**Akzeptanzkriterien:**
- ✅ Funktion `permutation_test_sharpe(trades: pd.DataFrame, *, schema: Literal["outcome_sign", "entry_time", "block"], B: int = 5000, seed: int = 42, ohlcv_provider: Callable | None = None) -> dict`
- ✅ Output: `{"observed_sharpe": float, "perm_sharpes": np.ndarray, "p_value_two_sided": float, "p_value_one_sided": float, "B": int, "schema": str}`
- ✅ Schema A: NumPy-vektorisiert via `np.random.choice(returns, size=(B, n))` mit zufälligen Vorzeichen
- ✅ Schema B: für jede Permutation B zufällige Entry-Zeitpunkte aus dem Universum ziehen, Hold-Period-Returns aus OHLCV-Provider holen, Sharpe berechnen
- ✅ Phipson-Smyth-Korrektur ✅ wiederverwenden: `(at_least_as_extreme + 1) / (B + 1)`
- ✅ Optional `permutation_test_profit_factor` und `permutation_test_max_dd` analog
- 🧪 Determinismus-Test: gleicher Seed → identische Permutationen
- 🧪 Power-Test: synthetische Mean-Reversion-Strategie mit echtem Edge → p-Value < 0.05 in ≥80% der Replikationen
- 🧪 False-Positive-Test: synthetische Random-Strategie → p-Value < 0.05 in ≤6% der Replikationen (≈ Type-I-Error α=0.05)

⚠ Schema B braucht OHLCV-Daten. Reuse von ✅ `open_prep/outcome_backfill.py` (Databento 1m OHLCV-Backfill, 529 Zeilen) als `ohlcv_provider`. Wenn nicht möglich: Schema A als Fallback dokumentieren.

### T3 — White's Reality-Check als Stretch-Goal (1–2 Werktage, optional)

**Ziel:** Defense gegen Selection-Bias bei mehreren getesteten Strategie-Varianten.

**Akzeptanzkriterien:**
- ✅ Funktion `whites_reality_check(strategy_returns: dict[str, np.ndarray], benchmark_returns: np.ndarray, *, B: int = 5000) -> dict` nach [Aronson / Financial Hacker](https://financial-hacker.com/whites-reality-check/)
- ✅ Output: `{"best_strategy": str, "data_mining_bias_estimate": float, "p_value": float, "expected_real_performance": float}`
- ✅ Bootstrap mit Replacement aus detrended Strategy-Curves; Maximum über alle Strategien pro Bootstrap; Vergleich gegen tatsächliche Best-Strategie
- 🧪 Test: für 100 zufällige Strategien (alle ohne echten Edge) ist `p_value > 0.05` in ≥85% der Replikationen
- ⚠ Stretch-Goal: nur wenn nach T2 noch ≥2 Werktage übrig sind. Bei nur 1–3 Setup-Typen ist Reality-Check Overkill — BH-FDR aus T4 reicht.

**Begründung:** Wenn wir später mehrere SMC-Varianten gegeneinander vergleichen (z. B. FVG-Strict vs FVG-Quality vs Zone-Priority-Set-A vs Set-B), produziert Selection-Bias inflated Sharpe-Werte. Reality-Check schätzt diese Inflation. [USU-Thesis](https://digitalcommons.usu.edu/cgi/viewcontent.cgi?article=2535&context=gradreports) und [Bailey & Lopez de Prado / Deflated Sharpe](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) liefern komplementäre Lösungen.

### T4 — Multiple-Testing-Korrektur über Setup-Typen (0.5 Werktag)

**Ziel:** BH-FDR über alle getesteten Setups, reuse der bestehenden Pipeline.

**Akzeptanzkriterien:**
- ✅ Funktion `aggregate_permutation_results(setup_results: dict[str, dict], q: float = 0.10) -> dict` ruft ✅ `benjamini_hochberg` aus `scripts/run_ab_comparison.py` auf
- ✅ Output pro Setup: `{"p_value_raw": ..., "p_value_bh_adjusted": ..., "rejects_h0": ..., "fdr_q": q}`
- ✅ Aggregat-Output: `{"fdr_rate_estimate": ..., "n_setups_tested": ..., "n_significant_after_bh": ...}`
- ⚠ FDR-Rate-Schätzung: Anteil der erwarteten False-Discoveries unter den Rejected-H0; mit q=0.10 ist FDR-Bound exakt 10% (BH-Eigenschaft)

### T5 — Test-Suite (0.5–1 Werktag)

**Akzeptanzkriterien:**
- 🧪 Power-Test: synthetisches Mean-Reversion mit echtem Edge → p < 0.05 in ≥80% von 100 Replikationen
- 🧪 Type-I-Error-Test: zufällige Strategie → p < 0.05 in ≤6% von 100 Replikationen
- 🧪 Determinismus: gleicher Seed → identische p-Werte
- 🧪 Edge-Case: n=10 Trades → `skipped_reason: "insufficient_trades"`, MIN_EVENTS_PER_ARM_FOR_BOOTSTRAP ✅ reusen
- 🧪 Property-Test: für 100 zufällige (B, schema)-Kombinationen ist `0.0 < p_value < 1.0` (Phipson-Smyth verhindert exakt 0)
- 🧪 pytest-xdist mit `pytest -n auto --dist=loadfile`
- ⚙️ Wöchentlicher CI-Job `permutation-validation.yml` mit Cron `0 8 * * 1` UTC

### T6 — Integration in Calibration-Report (0.5 Werktag)

**Akzeptanzkriterien:**
- ✅ Schema-Erweiterung in ✅ `scripts/emit_public_calibration_report.py` mit Feldern pro Setup:
  - `permutation.p_value_sharpe_one_sided`, `permutation.p_value_sharpe_two_sided`
  - `permutation.p_value_profit_factor`
  - `permutation.schema`, `permutation.B`
  - `permutation.bh_adjusted_p`, `permutation.bh_rejects_h0`, `permutation.fdr_q`
  - `permutation.reality_check_p_value` (optional, T3)
- 🧪 Schema-Test: Report ist JSON-Schema-validierbar

## Stop-Kriterien innerhalb des Sprints

- **Stop nach T1:** Wenn C2-Output nicht genug Felder für Schema B liefert (Symbol, Entry-Time, Hold-Period) → Schema A als Fallback verwenden, Schema-B-Patch in C2 als Backlog
- **Stop nach T2:** Wenn Power-Test < 60% — Permutationsschema überprüfen, ggf. Schema wechseln
- **Stop nach T2:** Wenn Type-I-Error > 10% — Phipson-Smyth-Korrektur prüfen, ggf. seed-Determinismus-Bug suchen
- **Stop nach T4:** Wenn nach BH-Korrektur 0 Setups signifikant — Sprint ist trotzdem fertig, Erkenntnis ist Wert (Track-Record-Gate verfehlt, anderer Setup-Pool nötig)
- **2-Iterations-Limit pro Task**

## Risiken

| Risiko | Wahrscheinlichkeit | Impact | Mitigation |
|---|---|---|---|
| Schema B braucht OHLCV das nicht verfügbar ist | mittel | mittel | Fallback Schema A; Backfill-Schritt erweitern |
| Permutations-Loop zu langsam | niedrig | niedrig | NumPy-Vektorisierung in T2, joblib falls nötig |
| Power zu niedrig bei n < 100 | hoch | hoch | Stop-Kriterium nach T2; n als Voraussetzung dokumentiert |
| Schema-Wahl produziert falsche Null-Verteilung | mittel | hoch | False-Positive-Test in T5 fängt das auf |
| White's Reality-Check (T3) frisst Zeit | niedrig | niedrig | T3 als Stretch — ohne DoD erfüllt |
| Multiple-Testing erhöht False-Negatives | mittel | mittel | q=0.10 statt 0.05; BH ist weniger konservativ als Bonferroni |

## Speed-Erwartung

| Setup | Realistische Dauer |
|---|---|
| Ohne Reuse, ohne Speed-Stack | 6–8 Werktage |
| Mit Reuse + KI-Tool | 3–5 Werktage |
| Plus NumPy-Vektorisierung + Inventur-Tag-1 | 2–4 Werktage |
| Plus White's Reality-Check (T3) | +1–2 Werktage |

## Definition of Done — Sprint C4

- ✅ `scripts/strategy_permutation.py` existiert
- ✅ Pro Setup-Typ liefert Permutations-p-Value (Sharpe + Profit-Factor) plus BH-adjustiertes p in `docs/calibration/calibration_report_public.json`
- 🧪 Power-Test ≥ 80%, Type-I-Error ≤ 6% in Monte-Carlo-Replikationen
- ⚙️ Wöchentlicher Cron `permutation-validation.yml` läuft 1× erfolgreich
- ⚙️ PR ist gemerged
- ⚠ T3 (Reality-Check) ist Stretch — DoD passt auch ohne

## Übergabe an Folge-Sprints

- C5 (Regime-Stratifikation): ruft Permutations-Test pro Regime separat auf, reused alles aus C4
- C6 (Probabilistic-Sharpe): ergänzt PSR und Deflated-Sharpe, die das Selection-Bias-Problem aus einer anderen Richtung lösen
- C7 (Dashboard-Frontend): liest `permutation.*`-Felder aus dem JSON
- C9 (Drift-Alert): vergleicht aktuelle Live-Sharpe mit Permutations-Null-Verteilung als Drift-Indikator

## Quellen

- [White's Reality Check / Aronson via Financial Hacker](https://financial-hacker.com/whites-reality-check/)
- [USU SPA-Thesis — Testing Investment Strategies for Superior Predictive Ability (PDF)](https://digitalcommons.usu.edu/cgi/viewcontent.cgi?article=2535&context=gradreports)
- [Bailey & Lopez de Prado — Deflated Sharpe Ratio (PDF)](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)
- [QuantDare — Deflated Sharpe in Python](https://quantdare.com/deflated-sharpe-ratio-how-to-avoid-been-fooled-by-randomness/)
- [Quantbeckman — Combinatorial Purged CV mit Permutationen](https://www.quantbeckman.com/p/with-code-combinatorial-purged-cross)
- [Two Sigma — Sharpe Hypothesis-Testing (PDF)](https://www.twosigma.com/wp-content/uploads/sharpe-tr-1.pdf)
- Repo-Inventur: ✅ `scripts/run_ab_comparison.py:409` `_permutation_p_delta_metric`, `:182` `benjamini_hochberg`, `:358-369` Bootstrap-Konstanten
