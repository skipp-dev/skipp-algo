# Sprint-Plan C2 — Walk-Forward-Pipeline

Datum: 2026-04-26 · Sprint-Reihe: Track-Record-Machbarkeitsplan · Aktueller Sprint: C2 von C1–C9

Evidenz-Marker: ✅ im Code belegt · 🧪 getestet · ⚙️ operativ · ⚠ nur plausibel

## Ziel-Framework (aus Machbarkeitsplan)

Wie für C1: alle Sprints C1–C9 zielen auf den Track-Record-Gate. C2 liefert genau eine der neun Mindestkennzahlen direkt — die Walk-Forward-Efficiency (WFE) > 50%. Indirekt liefert C2 die Datenstruktur, auf der C3 (Bootstrap), C4 (Permutation), C6 (PSR), C7 (Dashboard) und C9 (Drift-Alert) aufsetzen.

Quantitative Mindestanforderungen am Gate (gilt für mindestens 1, idealer 2–3 Setup-Typen):

| Metrik | Mindestwert | Sprint, der sie liefert |
|---|---|---|
| Out-of-Sample Trades (n) | ≥ 100, idealer ≥ 200 | C1 + C2 |
| Trade-Win-Rate | ≥ 55% (R/R = 1) oder ≥ 45% (R/R ≥ 1.5) | C1 |
| Sharpe Ratio (annualisiert) | ≥ 1.0 | C2 |
| Bootstrap-95%-CI für Sharpe (untere Grenze) | > 0.3 | C3 |
| Max Drawdown | < 15% | C2 |
| FDR-Rate | < 10% | C4 |
| **Walk-Forward-Efficiency** | **> 50%** | **C2** |
| Track-Record-Länge live | ≥ 3 Monate, idealer 6 | C8 |
| Permutation-Test p-Value | < 0.05 | C4 |

C2 ist deshalb der Sprint, der den **methodischen Anti-Overfit-Schutz** für die gesamte Sprint-Reihe etabliert. Wer hier schludert, hat Zahlen, die in C8 (Live-Incubation) auseinanderbrechen.

## Sprint-Übersicht

- **Sprint-Dauer:** 10–15 Werktage (Basis), 7–10 mit konsequentem Speed-Stack ⚠
- **Sprint-Typ:** Erweiterung von ✅ `compute_walk_forward_cv_hr()` in `scripts/smc_zone_priority_calibration.py` von Hit-Rate-CV zu vollständiger Walk-Forward-Pipeline mit Trade-PnL, Sharpe, Drawdown, WFE, Purging und Embargo
- **Trigger:** C1 in main gemerged, mindestens 30 Tage Outcome-Daten in `artifacts/open_prep/outcomes/` vorhanden
- **Definition of Done:** WFE-Wert für mindestens 1 Setup-Typ ist als Feld in `docs/calibration/calibration_report_public.json` veröffentlicht und in CI-Tests abgesichert

## Inventur — was bereits existiert

⚠ Inventur ist Tag 1 jedes Sprints (Speed-Hebel-Disziplin aus C1-Erfahrung). Hier vorab das, was schon vor Sprint-Start gegrept ist:

| Komponente | Status | Pfad |
|---|---|---|
| Walk-Forward-Splitter (naive K-Fold auf Hit-Rate) | ✅ existiert | `scripts/smc_zone_priority_calibration.py:167-252` |
| Outcome-Storage mit Bucket-PnL | ✅ existiert (aus C1) | `open_prep/outcomes.py` |
| Per-Trade PnL-Feld (`pnl_30m_pct`) | ✅ existiert | `streamlit_terminal.py:4930` |
| Databento-Backfill für historische OHLCV | ✅ existiert | `open_prep/outcome_backfill.py` |
| Purging / Embargoing | ❌ fehlt | — |
| Sharpe / MaxDD / WFE-Berechnung | ❌ fehlt | — |
| Combinatorial Purged Splits (CPCV) | ❌ fehlt | — |
| In-Sample-Optimization-Schritt | ❌ fehlt (C1 hat nur Bucketing, keine Param-Suche) | — |
| Vectorbt / Numba / Joblib | ❌ nicht in `requirements.txt` ([requirements.txt:1-N](https://github.com/skippALGO/skipp-algo/blob/main/requirements.txt) ✅) | — |
| pytest-xdist | ✅ in `requirements.txt` |  |

Konsequenz: C2 ist nicht Greenfield. Etwa 30–40% der Funktionalität existiert in Form der Hit-Rate-CV. Aber der Schritt von "OOS-Hit-Rate per Family" zu "OOS-Sharpe per Setup mit Purging und WFE" ist mehr als nur Erweiterung — die **Outcome-Datenstruktur muss als Trade-Liste mit Timestamps** lesbar sein, nicht als Aggregat.

## Speed-Stack für diesen Sprint

Konsequente Anwendung der Hebel aus der Speed-Diskussion:

1. **AI-Repo-Tool (Claude Code o. ä.)**: T2, T3, T5 sind gut spezifiziert, hoher KI-Hebel.
2. **vectorbt-Wrapper auf Outcome-Arrays**: T4 nutzt `vectorbt.Portfolio.from_signals` für Sharpe / MaxDD pro Fold — keine Migration der Setup-Detection nötig.
3. **joblib.Parallel** in T3 für Fold-Loop.
4. **pytest-xdist** mit `--dist=loadfile` für T6 Test-Suite.
5. **Inventur Tag 1** — siehe Tabelle oben.
6. **2-Iterations-Limit pro Task** — wenn Task nach 2 Anläufen nicht passiert, dokumentieren und nächsten Task ziehen.

⚠ Wichtig: vectorbt nur für **Aggregat-Metriken pro Fold** verwenden. Die Setup-Detection (FVG, Zone-Priority) bleibt event-driven in der Live-Pipeline. Migration der Detection ist explizit out-of-scope.

## Tasks

### T1 — Inventur und Datenkontrakt-Audit (1 Werktag)

**Ziel:** Bestätigen, was die genaue Outcome-Datenstruktur aus C1 liefert, und festlegen, welche Felder C2 zwingend braucht.

**Akzeptanzkriterien:**
- ✅ Datei `docs/sprints/C2_DATA_CONTRACT.md` listet alle Felder pro Trade-Outcome auf, die C2 erwartet
- ✅ Mindestfelder: `setup_type`, `entry_timestamp_utc`, `exit_timestamp_utc`, `pnl_pct`, `r_multiple`, `regime_at_entry`, `symbol`, `setup_features` (für IS-Optimization)
- ✅ Diff zwischen C1-Output und C2-Requirements explizit dokumentiert. Wenn C1 ein Feld nicht liefert: Backlog-Item für C1-Patch oder Workaround in C2

**Stop-Kriterium:** Wenn `r_multiple` und `entry_timestamp_utc` aus C1 nicht eindeutig ableitbar — Sprint stoppt, C1-Patch wird priorisiert.

### T2 — Walk-Forward-Splitter mit Purging und Embargo (2 Werktage)

**Ziel:** Neues Modul `scripts/walk_forward.py` mit drei Splitter-Varianten.

**Akzeptanzkriterien:**
- ✅ Klasse `WalkForwardSplitter(window_type: Literal["rolling", "anchored"], n_splits: int, train_size: int, test_size: int, purge_size: int, embargo_size: int)`
- ✅ Methode `split(timestamps: np.ndarray) -> Iterator[tuple[np.ndarray, np.ndarray]]` liefert (train_idx, test_idx) chronologisch geordnet
- ✅ Purging entfernt aus dem Trainingsset alle Trades, deren `exit_timestamp_utc` in den Test-Zeitraum hineinragt — verhindert Label-Leakage ([Wikipedia Purged CV](https://en.wikipedia.org/wiki/Purged_cross-validation))
- ✅ Embargo entfernt nach Testperiode `embargo_size` Beobachtungen aus den nachfolgenden Trainingssets — verhindert Auto-Korrelations-Leakage
- 🧪 Unit-Test: 3 Folds, geprüfte Train-Test-Indizes haben keine zeitliche Überlappung mit Test-Set ± purge/embargo

**Default-Parameter** (Empfehlung [Surmount.ai](https://surmount.ai/blogs/walk-forward-analysis-vs-backtesting-pros-cons-best-practices)):
- Rolling Window, train 2–4 Jahre × Test 3–6 Monate, IS:OOS = 70:30 oder 80:20
- Da wir realistisch nur 30–90 Tage Live-Outcome haben und Backfill-OHLCV von Databento bis 2018 zurückreicht: Stretch-Modus mit kürzeren Fenstern (train 60 Tage, test 15 Tage) für initiale C2-Iterationen

⚠ Bei n < 100 Trades pro Setup macht WFO statistisch wenig Sinn — siehe Stop-Kriterium am Sprint-Ende.

### T3 — Walk-Forward-Runner auf Outcome-Trade-Liste (3–4 Werktage)

**Ziel:** Neues Modul `scripts/walk_forward_runner.py` orchestriert die Folds.

**Akzeptanzkriterien:**
- ✅ Funktion `run_walk_forward(trades: pd.DataFrame, *, splitter: WalkForwardSplitter, optimize_fn: Callable, evaluate_fn: Callable, n_jobs: int = -1) -> WalkForwardResult`
- ✅ Pro Fold:
  - In-Sample-Schritt: `optimize_fn(train_trades)` liefert beste Parameter (z. B. Score-Threshold, Regime-Filter-Set, RVOL-Cutoff)
  - Out-of-Sample-Schritt: `evaluate_fn(test_trades, params)` liefert Trade-Subset und Aggregat-Metriken
- ✅ `n_jobs=-1` parallelisiert Folds via `joblib.Parallel` ([joblib-Doku, vgl. Stack Exchange](https://exante.eu/press/blog/2925-how-we-made-python-pytest-suites-85-faster/))
- ✅ Ergebnis: pro Fold ein `FoldResult(train_metrics, test_metrics, optimal_params, n_train_trades, n_test_trades, fold_period)`, gesamt eine zusammengeklebte OOS-Equity-Kurve
- 🧪 Unit-Test: synthetischer Trade-Datensatz mit bekanntem Optimum → Runner findet es im IS und verliert dezent OOS

⚠ Optimization-Schritt nicht überdimensionieren. Mindestens 1 Setup-Parameter (z. B. minimaler Score-Threshold) reicht für die Validierungsphase. Mehr-Parameter-Optimization ist Bait für Overfitting bei kleinen n.

### T4 — Performance-Metriken pro Fold und Aggregat (2 Werktage)

**Ziel:** Neues Modul `scripts/performance_metrics.py` berechnet Sharpe, MaxDD, WFE, Hit-Rate, Profit-Factor.

**Akzeptanzkriterien:**
- ✅ `compute_sharpe(returns: np.ndarray, freq: int = 252) -> float`
- ✅ `compute_max_drawdown(equity: np.ndarray) -> float`
- ✅ `compute_walk_forward_efficiency(is_returns_per_fold, oos_returns_per_fold) -> float` als Verhältnis annualisierter OOS-Return zu IS-Return ([TradeStation-Definition](https://help.tradestation.com/09_01/tswfo/topics/walk-forward_summary_out-of-sample.htm))
- ✅ `compute_profit_factor`, `compute_hit_rate`, `compute_avg_r_multiple`
- ✅ Optional: ✅ `vectorbt`-Wrapper als Stretch-Implementation für Cross-Check der eigenen Berechnung. ⚠ Nicht als Hauptpfad, weil `vectorbt` als Dependency Numba und Rust-Toolchain mitbringt — Risiko für CI
- 🧪 Unit-Test: Sharpe gegen `numpy.std`-Hand-Rechnung; MaxDD gegen bekannte Referenz-Equity ([Quantpedia](https://quantpedia.com/in-sample-vs-out-of-sample-analysis-of-trading-strategies/) liefert Sharpe-Verhalten-Benchmarks)

**Speed-Hinweis:** Wenn vectorbt aufgenommen wird, dann nur für T4 Metric-Cross-Check, nicht als Default. Default bleibt NumPy/Pandas, weil reproduzierbar und zero-Cost im CI.

### T5 — Combinatorial Purged Cross-Validation als Stretch-Goal (3–5 Werktage, optional)

**Ziel:** Wenn Zeit-Budget nach T1–T4 noch reicht, CPCV-Variante implementieren.

**Akzeptanzkriterien:**
- ✅ Klasse `CombinatorialPurgedSplitter(n_groups: int, k_test_groups: int, purge_size: int, embargo_size: int)` nach [Lopez de Prado / quantbeckman.com](https://www.quantbeckman.com/p/with-code-combinatorial-purged-cross)
- ✅ Output: Verteilung von OOS-Sharpe-Werten über alle Combinations (z. B. 6 Gruppen × 2 Test-Gruppen = 15 Pfade)
- ✅ Aggregat-Metrik: 10. Perzentil von Sharpe als robuster Worst-Case-Indikator
- 🧪 Unit-Test: synthetischer Datensatz, alle generierten Test-Indizes sind disjunkt zu ihren Train-Indizes nach Purging

**Wann skippen:** Wenn nach T4 weniger als 3 Werktage übrig sind oder wenn n < 200 Trades pro Setup. CPCV bei kleinem n liefert Pseudo-Sicherheit. Stand bestätigen mit Inventur-Daten.

### T6 — Test-Suite und Reproduzierbarkeit (1–2 Werktage)

**Ziel:** Tests für T2–T5, läuft mit `pytest -n auto --dist=loadfile`.

**Akzeptanzkriterien:**
- 🧪 Smoke-Test: synthetischer Trade-Datensatz mit bekannter Mean-Reversion-Setup → WF erkennt Overfit (IS-Sharpe deutlich höher als OOS-Sharpe)
- 🧪 Property-Test: für 100 zufällige `(n_splits, purge_size, embargo_size)`-Kombinationen → keine Index-Überlappung
- 🧪 Determinismus-Test: gleicher Seed → identische Folds und Metriken
- 🧪 pytest-xdist-Kompatibilität: Tests laufen mit `pytest -n auto` durch, keine Race Conditions auf Filesystem
- ⚙️ CI-Job `walk-forward-validation.yml` mit Cron `0 6 * * 1` (wöchentlich Montag früh UTC) emittiert WFE-Wert in `artifacts/wfo/`

### T7 — Integration in Calibration-Report und Dashboard-Stub (1–2 Werktage)

**Ziel:** WFE und OOS-Sharpe sind als Top-Level-Felder in `docs/calibration/calibration_report_public.json` sichtbar.

**Akzeptanzkriterien:**
- ✅ Schema-Erweiterung in ✅ `scripts/emit_public_calibration_report.py` (existiert) mit neuen Feldern: `walk_forward.wfe`, `walk_forward.oos_sharpe`, `walk_forward.oos_max_drawdown`, `walk_forward.n_oos_trades`, `walk_forward.fold_count`, `walk_forward.method` (Wert: `"rolling"`, `"anchored"` oder `"cpcv"`)
- ✅ Pro Setup-Typ ein eigener Block, damit C5 (Regime-Stratifikation) später aufsetzen kann
- ⚙️ `public-calibration-dashboard.yml` zeigt WFE neben Hit-Rate (für 1 Sprint reicht ein Stub im JSON; das visuelle Dashboard kommt in C7)
- 🧪 Schema-Test: Report ist JSON-validierbar gegen aktualisiertes Schema

## Stop-Kriterien innerhalb des Sprints

⚠ Walk-Forward bei zu kleinem n produziert irreführende Werte. Folgende Stops:

- **Stop nach T1:** Wenn nach C1-Merge weniger als 30 Trades pro Setup-Typ in `artifacts/open_prep/outcomes/` vorhanden sind, C2 wird auf später verschoben. Stattdessen: warten oder Backfill via `outcome_backfill.py` weiter zurückführen.
- **Stop nach T3:** Wenn IS-Sharpe und OOS-Sharpe für jeden Fold negativ sind, kein Setup-Typ ist statistisch profitabel — Sprint endet, Konsequenz ist Pivot in der Setup-Auswahl, nicht weiteres Polishing der Pipeline.
- **Stop nach T4:** Wenn WFE über alle Folds < 30% liegt, Setup ist überangepasst. Pipeline ist trotzdem fertig — Erkenntnis ist der Wert, nicht die Zahl.
- **2-Iterations-Limit pro Task:** wie in C1.

## Risiken

| Risiko | Wahrscheinlichkeit | Impact | Mitigation |
|---|---|---|---|
| Zu wenige OOS-Trades bei Sprint-Start | hoch | hoch | Stop nach T1, Backfill-Schritt verlängern |
| vectorbt-Dependency bricht CI | mittel | mittel | als optionalen Extra `[wfo-fast]` aufnehmen, nicht in Default-`requirements.txt` |
| In-Sample-Optimization erzeugt Overfit, der WFE verschleiert | mittel | hoch | nur 1–2 Parameter optimieren, alles andere fix; T6 Property-Test prüft Verhalten an synthetischen Overfit-Setups |
| Purging zu aggressiv → Train-Set zu klein | mittel | mittel | `purge_size` als Parameter, Default = mediane Trade-Dauer × 1.5 |
| CPCV (T5) frisst Zeitbudget | mittel | niedrig | T5 ist Stretch, ohne Ergebnis trotzdem Sprint-Done |

## Speed-Erwartung

| Setup | Realistische Dauer |
|---|---|
| Ohne KI-Tool, ohne Speed-Stack | 12–15 Werktage |
| Mit KI-Repo-Tool und pytest-xdist | 8–10 Werktage |
| Plus joblib-Parallel und Inventur-Tag-1-Disziplin | 7–9 Werktage |
| Plus vectorbt-Cross-Check als Stretch | unverändert (vectorbt als optional) |

⚠ Realistisch ist 8–10 Werktage. 7 wären die untere Grenze nur, wenn T5 (CPCV) komplett wegfällt und T1-Inventur keine Datenlücke aus C1 zutage fördert.

## Definition of Done — Sprint C2

- ✅ `scripts/walk_forward.py` und `scripts/walk_forward_runner.py` und `scripts/performance_metrics.py` existieren
- ✅ Mindestens 1 Setup-Typ liefert WFE-Wert in `docs/calibration/calibration_report_public.json`
- ✅ Wöchentlicher Cron `walk-forward-validation.yml` läuft 1× erfolgreich durch
- 🧪 Test-Suite läuft mit `pytest -n auto`, alle T6-Tests grün
- ⚙️ PR ist gemerged
- ⚠ CPCV (T5) ist Stretch — DoD passt auch ohne

## Übergabe an Folge-Sprints

- C3 (Bootstrap-CI) konsumiert die OOS-Trade-Liste pro Fold aus C2 — keine eigene Trade-Liste nötig
- C4 (Permutation-Test) konsumiert dasselbe wie C3
- C5 (Regime-Stratifikation) erweitert WFE pro Regime
- C6 (Probabilistic-Sharpe) konsumiert die OOS-Sharpe-Verteilung über Folds
- C7 (Dashboard-Frontend) liest `walk_forward.*`-Felder aus dem JSON-Report
- C9 (Drift-Alert) prüft, ob aktuelle Live-Trade-WFE unter den Backtest-WFE driftet

## Quellen

- [Surmount.ai — Walk-Forward Analysis vs. Backtesting](https://surmount.ai/blogs/walk-forward-analysis-vs-backtesting-pros-cons-best-practices)
- [TradeStation — Walk-Forward Efficiency Definition](https://help.tradestation.com/09_01/tswfo/topics/walk-forward_summary_out-of-sample.htm)
- [Wikipedia — Purged cross-validation](https://en.wikipedia.org/wiki/Purged_cross-validation)
- [Quantbeckman — Combinatorial Purged CV mit Code](https://www.quantbeckman.com/p/with-code-combinatorial-purged-cross)
- [Quantpedia — IS vs OOS Sharpe-Decay (33–44%)](https://quantpedia.com/in-sample-vs-out-of-sample-analysis-of-trading-strategies/)
- [QuantInsti — Walk-Forward-Optimization Intro](https://blog.quantinsti.com/walk-forward-optimization-introduction/)
- [PyQuant News — vectorbt Walk-Forward in Sekunden](https://www.pyquantnews.com/the-pyquant-newsletter/1000000-backtest-simulations-20-seconds-vectorbt)
- [Exante — pytest-xdist 8.5× Speed-Up](https://exante.eu/press/blog/2925-how-we-made-python-pytest-suites-85-faster/)
- [arXiv 2512.12924 — Walk-Forward Realismus](https://arxiv.org/html/2512.12924v1)
