# Methodik des SMC-Calibration-Track-Records

Datum: 2026-04-26 · Autor: Steffen Preuss · Repo: [skippALGO/skipp-algo](https://github.com/skippALGO/skipp-algo) · Dashboard: [docs/calibration/](https://github.com/skippALGO/skipp-algo/tree/main/docs/calibration)

Evidenz-Marker: ✅ im Code · 🧪 getestet · ⚙️ operativ · ⚠ nur plausibel

## Inhalt

- [Zusammenfassung in einem Absatz](#zusammenfassung-in-einem-absatz)
- [Was wir messen — die vier Setup-Familien](#was-wir-messen-die-vier-setup-familien)
- [Wie ein Trade in den Track-Record kommt](#wie-ein-trade-in-den-track-record-kommt)
- [Statistische Härtung Schritt für Schritt](#statistische-haertung-schritt-fuer-schritt)
- [Die akademischen Quellen — was wir nicht erfunden haben](#die-akademischen-quellen-was-wir-nicht-erfunden-haben)
- [Das Promotions-Gate — wann ein Setup verkaufbar ist](#das-promotions-gate-wann-ein-setup-verkaufbar-ist)
- [Bekannte Grenzen und bewusst akzeptierte Restrisiken](#bekannte-grenzen-und-bewusst-akzeptierte-restrisiken)
- [Reproduzierbarkeit](#reproduzierbarkeit)

## Zusammenfassung in einem Absatz

Der SkippALGO-SMC-Track-Record bewertet vier strukturell unabhängige Setup-Familien — Break-of-Structure (BOS), Order-Block (OB), Fair-Value-Gap (FVG) und Liquidity-Sweep (SWEEP) — auf Basis eines Event-für-Event-Ledgers. Jeder erkannte Setup wird mit seiner kalibrierten Wahrscheinlichkeit emittiert, das tatsächliche Outcome (Win/Loss, R-Multiple, FVG-Fill) wird automatisch nachgetragen, und das resultierende `(predicted_prob, outcome)`-Paar fließt in eine Pipeline aus Walk-Forward-Validation, Bootstrap-Konfidenz-Intervallen, Permutations-Tests, Benjamini-Hochberg-FDR-Korrektur, Probabilistic-Sharpe-Ratio und mindestens drei Monaten Live-Inkubation. Erst wenn eine Familie alle 17 Mindestanforderungen gleichzeitig erfüllt, wird sie als „active" markiert. Alle Methoden sind peer-reviewed; die spezifische Kombination + die öffentliche, automatische Cron-Veröffentlichung der vollständigen History sind unsere eigentliche Differenzierung gegenüber kommerziellen Signal-Anbietern.

## Was wir messen — die vier Setup-Familien

Im Code ist der Setup-Typ eine harte Liste von genau vier Werten ([smc_core/scoring.py:33](https://github.com/skippALGO/skipp-algo/blob/main/smc_core/scoring.py)):

```python
EventFamily = Literal["BOS", "OB", "FVG", "SWEEP"]
```

| Familie | Smart-Money-Konzept | Outcome-Definition |
|---|---|---|
| **BOS** | Break of Structure — höheres Hoch / tieferes Tief | Folgekerze hält den Bruch über Holding-Period |
| **OB** | Order Block — letzte Zone mit hohem Volumen vor Bruch | Preis re-tested und respektiert die Zone |
| **FVG** | Fair Value Gap — unausgefüllte Preislücke | Lücke füllt sich innerhalb Holding-Period (FVG-Fill) |
| **SWEEP** | Liquidity Sweep — Stop-Hunt über/unter Schlüssel-Level | Preis kehrt nach Sweep um, schließt jenseits Sweep-Level |

Jeder einzelne Setup landet in **genau einer** Familie. Aggregation erfolgt strikt **pro Familie** — Mischung würde die Wahrscheinlichkeits-Verteilungen überlagern und die Statistik invalidieren.

## Wie ein Trade in den Track-Record kommt

### Schritt 1 — Event-Ledger-Eintrag bei Setup-Erkennung

Sobald ein SMC-Setup im Markt erkannt wird, schreibt der Kern eine Zeile in das Event-Ledger ([smc_core/event_ledger.py:37–54](https://github.com/skippALGO/skipp-algo/blob/main/smc_core/event_ledger.py)):

```jsonl
{"family": "FVG", "predicted_prob": 0.65, "outcome": null, "features": {...}, "outcome_extras": {...}, "timestamp": "..."}
```

Wichtig: `predicted_prob` ist die **post-Calibration-Wahrscheinlichkeit** — sie hat den Platt-Scaling-Layer bereits durchlaufen ([smc_core/scoring._resolve_calibration_input](https://github.com/skippALGO/skipp-algo/blob/main/smc_core/scoring.py)).

### Schritt 2 — Outcome-Backfill (Sprint C1)

Nach 1d / 3d / 5d Forward-Holding-Period wird `outcome` automatisch nachgetragen. R-Multiple und Win/Loss-Klassifikation werden in `outcome_extras` ergänzt. Pipeline: [open-prep-outcome-backfill.yml](https://github.com/skippALGO/skipp-algo/blob/main/.github/workflows/open-prep-outcome-backfill.yml) ✅.

### Schritt 3 — Aggregation pro Tag pro Familie

`scripts/emit_public_calibration_report.py` ✅ aggregiert zu einer Tageszeile in `docs/calibration/calibration_report_public.json` und appended zur History `*_history.jsonl`.

### Schritt 4 — Veröffentlichung über Cron

[public-calibration-dashboard.yml](https://github.com/skippALGO/skipp-algo/blob/main/.github/workflows/public-calibration-dashboard.yml) läuft werktags 04:30 UTC, committet Aktualisierungen ins Repo. Output ist ohne Zugang einsehbar — jeder Prospect kann SHA-verifiziert prüfen, dass keine nachträglichen Manipulationen erfolgten.

## Statistische Härtung Schritt für Schritt

### Brier-Score und ECE als Calibration-Mess-Werte

| Mess-Wert | Was er misst | Niedriger ist besser |
|---|---|---|
| **Brier-Score** | Mittlerer quadratischer Fehler `(p − outcome)²` über alle Events | Ja |
| **ECE** (Expected Calibration Error) | Mittlere Abweichung „bei p=70%-Vorhersage tatsächlich 70% Wins" pro Bin | Ja |
| **smECE** (smooth ECE) | Bin-frei, robust gegen Bin-Cutoff-Sensitivität ([Błasiok-Nakkiran 2023](https://arxiv.org/abs/2309.12236)) | Ja |
| **Hit-Rate** | Anteil korrekter Vorhersagen | Höher = besser |

### Walk-Forward-Validation (Sprint C2)

Strikt rollende Fenster: trainiere Calibrator auf Monate 1–6, teste auf Monat 7, schiebe um einen Monat weiter, wiederhole. **Keine Re-Optimization auf OOS-Resultaten** — diese Disziplin ist kompromisslos. Walk-Forward-Efficiency (WFE) muss > 50% sein ([Pardo-Methodik via Surmount](https://surmount.ai/blogs/walk-forward-analysis-vs-backtesting-pros-cons-best-practices)).

### Bootstrap-Konfidenz-Intervalle (Sprint C3)

Per-Trade-Resampling mit 2000 Wiederholungen für Sharpe, Profit-Faktor, Win-Rate, Max-Drawdown. BCa-Intervalle bevorzugt vor naivem Percentile ([PyBroker](https://www.pybroker.com/en/latest/notebooks/3.%20Evaluating%20with%20Bootstrap%20Metrics.html)). Untere 95%-CI-Schranke des Sharpe-Werts muss > 0.3 sein.

### Permutations-Test mit Phipson-Smyth-Korrektur (Sprint C4)

Für Brier und ECE existiert keine geschlossene Null-Verteilung — wir nutzen Permutation:

1. Pool aller Events aus Treatment- und Control-Arm
2. Zufällige Aufteilung in dieselben Größen wie ursprünglich
3. Brier-Differenz unter dieser Schein-Welt berechnen
4. **2000-mal wiederholen** (`BOOTSTRAP_B = 2000`, `BOOTSTRAP_SEED = 42`)
5. p-Wert berechnen mit **Phipson-Smyth-Formel**:

\[ p = \frac{r + 1}{B + 1} \]

Diese `+1`-Korrektur verhindert `p = 0` und ist mathematisch nötig, weil sonst log-Transformationen in Folgeanalysen explodieren ([Phipson & Smyth 2010](https://www.degruyter.com/document/doi/10.2202/1544-6115.1585/html)).

### Benjamini-Hochberg-FDR-Korrektur

Bei 4 Familien × 3 Metriken = **12 simultane Tests** beträgt die naive Falsch-Positiv-Wahrscheinlichkeit unter H₀ ohne Korrektur:

\[ 1 - (1 - 0{,}05)^{12} \approx 0{,}46 \]

Heißt: Bei einer wirkungslosen Änderung würde fast jeder zweite Run fälschlich „signifikant" zeigen. **BH-FDR** sortiert alle 12 p-Werte aufsteigend und kontrolliert die erwartete False-Discovery-Rate auf das gewählte Niveau q = 0,05 ([Benjamini & Hochberg 1995](https://www.jstor.org/stable/2346101)). Wir korrigieren **gemeinsam** über alle 12 Zellen, nicht pro Metrik separat — getrennte Runs würden die effektive FDR auf ~0,15 aufblähen (Simes-Bonferroni-Argument).

### Regime-Stratifikation (Sprint C5)

Markt-Regime-Tagger (Bull / Bear / Range / Vola-Hoch / Vola-Niedrig) basierend auf SPY-Returns. Pro Setup × Regime: separate Win-Rate, Sharpe, n. Mindest-n pro Regime-Cell für Aussagekraft. Edges müssen in **mehr als einem Regime** halten — sonst wird die Familie auf „incubation" zurückgestuft.

### Probabilistic-Sharpe-Ratio + MinTRL (Sprint C6)

\[ \text{PSR}(SR^*) = \Phi\left( \frac{(\hat{SR} - SR^*) \sqrt{T - 1}}{\sqrt{1 - \hat{\gamma}_3 \hat{SR} + \frac{\hat{\gamma}_4 - 1}{4} \hat{SR}^2}} \right) \]

Bewertet Skewness und Kurtosis der Returns ([Bailey & López de Prado 2012, „The Sharpe Ratio Efficient Frontier"](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1821643)). PSR(SR*=0) muss ≥ 0,95 sein. **MinTRL** sagt explizit, wieviele weitere Trades nötig sind, um SR > Schwellwert zu beweisen — verhindert verfrühtes Promote.

### Live-Inkubation (Sprint C8)

Auch bei perfektem Backtest ist eine Strategie erst nach **3–6 Monaten echtem Live-Lauf ohne Re-Optimization** verkaufbar ([Quantified Strategies](https://www.quantifiedstrategies.com/out-of-sample-backtesting/)). Phase A (4 Wochen Paper-Trading bei 100% Size), Phase B (3–6 Monate Live bei 10–25% Size). Live-Sharpe ÷ Backtest-Sharpe ≥ 0,50 ist Pflicht.

### Drift-Alarm mit 4-Detektoren-Konsens (Sprint C9)

| Detektor | Drift-Typ | Schwelle |
|---|---|---|
| **Page-Hinkley** | Gradueller Drift, Streaming | PH(t) > 3σ·√w |
| **CUSUM** | Abrupter Drift | C⁺(t) > 5σ mit k=0,5σ |
| **KS-Test (windowed)** | Verteilungs-Shift | p < 0,05 + Effect-Size |
| **PSI** (Population Stability Index) | Feature-Stability | <0,10 stabil, 0,10–0,25 minor, >0,25 major |

Konsens: ≥2-of-4 = „concerning", ≥3-of-4 = „critical" + Auto-Halt-Hook. Täglicher Cron via [smc-drift-monitor.yml](https://github.com/skippALGO/skipp-algo/blob/main/.github/workflows/smc-drift-monitor.yml) (Sprint C9).

## Die akademischen Quellen — was wir nicht erfunden haben

Wir nutzen ausschließlich peer-reviewed, etablierte Methoden. Die Liste mit Originalquellen:

### Calibration-Methodik

- [Brier (1950), „Verification of Forecasts Expressed in Terms of Probability"](https://journals.ametsoc.org/view/journals/mwre/78/1/1520-0493_1950_078_0001_vofeit_2_0_co_2.xml) — *Monthly Weather Review* — Originaldefinition Brier-Score
- [Guo, Pleiss, Sun, Weinberger (2017), „On Calibration of Modern Neural Networks"](https://arxiv.org/abs/1706.04599) — *ICML* — moderne ECE-Definition
- [Kumar, Liang, Ma (2019), „Verified Uncertainty Calibration"](https://arxiv.org/abs/1909.10155) — *NeurIPS* — Bootstrap-CIs für ECE, [verified_calibration auf GitHub](https://github.com/p-lambda/verified_calibration)
- [Błasiok, Nakkiran (2023), „Smooth ECE"](https://arxiv.org/abs/2309.12236) — bin-freie smECE-Variante, die wir parallel zur klassischen ECE reporten
- [Collins, Riley (2022), „Calibration Instability via Bootstrap"](https://pmc.ncbi.nlm.nih.gov/articles/PMC10952221/) — *Statistics in Medicine*

### Permutations-Test und FDR

- [Fisher (1935), „The Design of Experiments"](https://psycnet.apa.org/record/1939-04964-000) — Original-Permutations-Test
- [Benjamini & Hochberg (1995), „Controlling the False Discovery Rate"](https://www.jstor.org/stable/2346101) — *Journal of the Royal Statistical Society B* — BH-Originalpaper
- [Phipson & Smyth (2010), „Permutation P-values should never be zero"](https://www.degruyter.com/document/doi/10.2202/1544-6115.1585/html) — *Statistical Applications in Genetics and Molecular Biology* — `(B+1)/(M+1)`-Korrektur
- [Noma, Shinozaki, Iba, Teramukai, Furukawa (2021), „Confidence intervals of prediction accuracy measures for multivariable prediction models based on the bootstrap-based optimism correction methods"](https://arxiv.org/abs/2005.01457) — *Statistics in Medicine* — Location-shifted Bootstrap

### Trading-spezifisches Multiple-Testing

- [Bailey & López de Prado (2012), „The Sharpe Ratio Efficient Frontier"](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1821643) — *Journal of Risk* — PSR und MinTRL
- [Bailey & López de Prado (2014), „The Deflated Sharpe Ratio"](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) — *Journal of Portfolio Management* — Multiple-Testing-Korrektur für Sharpe
- [Harvey, Liu, Zhu (2015), „Backtesting"](https://people.duke.edu/~charvey/Research/Published_Papers/P120_Backtesting.PDF) — Duke-Paper, vergleicht Bonferroni / Holm / BH-Yekutieli für Trading-Strategien

### Walk-Forward und Drift-Detection

- Pardo (2008), „The Evaluation and Optimization of Trading Strategies", 2nd ed., Wiley — Walk-Forward-Klassiker, [TradeStation-Implementation](https://help.tradestation.com/09_01/tswfo/topics/perform_cluster_analysis.htm)
- [Page (1954), „Continuous Inspection Schemes"](https://www.jstor.org/stable/2333009) — *Biometrika* — CUSUM und Page-Hinkley
- Kolmogorov-Smirnov Test — Standardstatistik
- [Wu et al. (2018), „PSI für Credit-Score-Drift"](https://www.federalreserve.gov/econres/notes/feds-notes/credit-scoring-drift-and-population-stability-index-20180511.html) — Federal Reserve Notes

## Das Promotions-Gate — wann ein Setup verkaufbar ist

Ein Setup wird erst dann als „active" auf dem öffentlichen Dashboard markiert, wenn **alle 17 Mindestanforderungen gleichzeitig** erfüllt sind:

| # | Anforderung | Sprint |
|---|---|---|
| 1 | n ≥ 100 OOS-Trades | C1 + C2 |
| 2 | Win-Rate ≥ 55% bei R/R = 1, oder ≥ 45% bei R/R ≥ 1,5 | C1 |
| 3 | Sharpe-Ratio ≥ 1,0 | C2 |
| 4 | Bootstrap-95%-CI-low > 0,3 | C3 |
| 5 | Max-Drawdown < 15% | C2 |
| 6 | FDR-Rate < 10% | C4 |
| 7 | Walk-Forward-Efficiency > 50% | C2 |
| 8 | Permutation-p < 0,05 | C4 |
| 9 | Per-Regime-Streuung < 20% | C5 |
| 10 | PSR(SR\*=0) ≥ 0,95 | C6 |
| 11 | MinTRL ≤ verfügbare n | C6 |
| 12 | 3-Sek-Lesbarkeit auf Dashboard | C7 |
| 13 | ≥ 3 Monate Live-Inkubation | C8 |
| 14 | ≥ 30 Live-Trades | C8 |
| 15 | Live-Sharpe ÷ Backtest-Sharpe ≥ 0,50 | C8 |
| 16 | Drift-Cron grün, ≥30 Tage stabil | C9 |
| 17 | Auto-Halt-Hook nicht ausgelöst | C9 |

Erfüllt eine Familie nur einige davon, erscheint sie als „incubation" — ehrlich, nicht versteckt. Erfüllt sie keine, als „inactive". Diese Transparenz, inklusive der scheiternden Familien, ist der eigentliche Vertrauens-Moat.

## Bekannte Grenzen und bewusst akzeptierte Restrisiken

| Grenze | Was bedeutet das | Wie wir damit umgehen |
|---|---|---|
| **Serielle Korrelation der Events** | FVG-Bursts an Trend-Tagen verletzen i.i.d.-Annahme der Vanilla-Permutation → kann zu falsch-positiven Befunden führen | Geplant: Block-Permutation mit Block-Länge √n als Follow-up ([Pilavakis et al. 2018](https://arxiv.org/abs/1711.01070)) |
| **Calibrator-Fit-Unsicherheit** | Permutations-Test bewertet Modell + Platt-Calibrator gemeinsam, nicht das Modell allein unter Calibrator-Refit pro Permutation | Operativ vertretbar — Operator interessiert sich für End-to-End-Output. Ist im JSON-Output dokumentiert |
| **Asymmetrische Sample-Größen** | Wenn Treatment 10× mehr Events hat als Control (n<30), wird p-Wert-Auflösung grob | Mindest-n pro Familie pro Arm gefordert; sonst „degenerate" und kein Test |
| **Regime-Wechsel während Live-Inkubation** | Ein Bull-zu-Bear-Wechsel kann eine Setup-Familie mitten in der Inkubation kippen | Per-Regime-Streuung (Anforderung #9) prüft das ex-ante; Drift-Cron (C9) erkennt es ex-post |
| **Survivorship-Bias bei Symbol-Universum** | Heute delistede Symbole fehlen im Backtest | Adressed durch breite Symbol-Universum + transparente Universum-Definition im Repo |
| **Lookahead-Bias durch Daten-Pipeline** | Future-Bars könnten unbeabsichtigt in Setup-Erkennung einfließen | [TEMPORAL_NUMERICAL_AUDIT 2026-04-24](https://github.com/skippALGO/skipp-algo) ⚙️ schließt das aus, kontinuierlicher Audit-Cron |

## Reproduzierbarkeit

- **Determinismus:** `BOOTSTRAP_SEED = 42` fest verankert. Re-Run mit gleichem Seed → identisches Ergebnis bit-genau
- **Pure-Python-stdlib:** keine NumPy/SciPy-Hardabhängigkeit für Statistik-Layer, gleiche Disziplin wie [PR #102](https://github.com/skippALGO/skipp-algo/pull/102)
- **SHA-Verifikation:** jeder Dashboard-Commit enthält `commit_sha` im Report, jeder Outcome-Eintrag ist Git-getaggt
- **Open-Source:** der gesamte Statistik-Layer ist im Repo lesbar — kein Black-Box-Modell, kein proprietärer Algorithmus
- **Audit-Trail:** History-File `*_history.jsonl` wird append-only geführt, kein Rewrite

## Schlussfolgerung

Wir haben methodisch **nichts Neues erfunden**. Jeder Baustein ist akademisch etabliert und in mindestens einer Open-Source-Bibliothek implementiert. Was neu ist, ist die spezifische Kombination — Calibration-FDR + Setup-Familie + öffentlicher Live-Track-Record + Live-Inkubations-Gate — und der Aufbau auf einem strukturell sauber typisierten Event-Ledger, der den vollen Audit-Pfad vom Setup-Trigger bis zur Tagesaggregation transparent hält. Genau diese Sichtbarkeit, in Kombination mit der akademischen Standard-Methodik, ist der Grund, warum ein „active"-Stempel auf dem Dashboard belastbarer ist als die meisten Track-Records, die kommerzielle Signal-Anbieter veröffentlichen.

## Verwandte Dokumente im Repo

- [SPRINT_ROADMAP_C2_C9_CONSOLIDATED](docs/SPRINT_ROADMAP_C2_C9_CONSOLIDATED_2026-04-26.md) — Master-Roadmap mit Aufwand und Zeitachse
- [TRACK_RECORD_FEASIBILITY_PLAN](docs/TRACK_RECORD_FEASIBILITY_PLAN_2026-04-25.md) — Machbarkeitsanalyse
- [BOOTSTRAP_CALIBRATION_FDR_DESIGN](docs/BOOTSTRAP_CALIBRATION_FDR_DESIGN_2026-04-24.md) — Detail-Design des Permutation-Layers
- [SMC_SYSTEM_REVIEW](docs/SMC_SYSTEM_REVIEW_2026-04-24.md) — Architektur-Review

## Disclaimer

Backtest-Ergebnisse und Live-Inkubation sind keine Garantie für zukünftige Erträge. Märkte können in Regimes wechseln, in denen historische Edges nicht halten. Der Track-Record ist als methodisch belastbarer **Vergleichsmaßstab** gedacht, nicht als Versprechen — gerade die ehrliche Markierung von „inactive"-Familien ist Teil dieser Disziplin.
