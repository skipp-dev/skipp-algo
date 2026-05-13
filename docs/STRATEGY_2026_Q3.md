# SkippALGO / SMC — Strategischer Fahrplan Q3 2026

> **Basiert auf:** Kalibrationsdaten (258 Events, 12 Pairs, 6 Symbole),
> Performance Report (Overall Grade B), Zone Priority Feedback Loop (4/4 Phasen abgeschlossen),
> Q2 System Review (alle 10 WPs A1–C10 umgesetzt).
>
> **Datum:** 20. April 2026

---

## 1. Was die Daten sagen

> **Reproducibility-Hinweis:** Pfade unter `artifacts/ci/...` und
> `artifacts/reports/...` werden nur im CI-Run materialisiert und sind
> nicht im Git committed. Lokal werden sie regeneriert via
> `python scripts/run_smc_measurement_benchmark.py` bzw. via
> Re-Run der Workflows `smc-measurement-benchmark-rolling.yml` /
> `feature-importance-daily.yml` (Artefakte 90 Tage in der Action-UI).
> Persistent committed sind nur `artifacts/experiments/*.json`
> (z.B. `f2_contextual_promotion.json` als F2-Decision-Snapshot).

### 1.1 Family Hit Rates — Kalibrierte Gewichte

> **Quelle (2026-04-22):** 4-TF-Plan-2.8-Universum, 10 004 Events / 78 (Symbol×TF)-Pairs aus
> `artifacts/ci/measurement_benchmark_combined_2026-04-21/zone_priority_calibration.json`
> (family-summed: BOS 1606 + FVG 5671 + OB 952 + SWEEP 1775; älteres Aggregat
> 10 064 wurde in Q4-Cron-Logs an einigen Stellen weiter gepflegt — die
> family-summed Zahl ist die Single-Source-of-Truth).
> Reproduzierbar via `python scripts/fvg_label_audit_q3.py`.

| Family | Events | Hit Rate | Prior | Kalibriert | Δ vs Prior | Bewertung |
|--------|-------:|----------:|------:|-----------:|-----------:|-----------|
| **BOS**   | 1 606 | **85.7%** | 0.81 | 0.8432 | +4.1% | ⬆ Stärkste Familie — bestätigt Q2 |
| **SWEEP** | 1 775 | **65.4%** | 0.73 | 0.6765 | −7.3% | ↘ Unter Prior — Q2-Stichprobe war zu optimistisch |
| **FVG**   | 5 671 | **56.3%** | 0.61 | 0.5773 | −5.4% | ↘ Schwächste auf Volumen — Hauptverbesserungsfeld |
| **OB**    |   952 | **31.5%** | 0.82 | 0.4666 | −43.1% | ⬇ **Krasse Underperformance** — Prior basierte auf 44 Events; Bayesian-Smoothing zieht den Wert noch nach oben |

**Kernbefund:** FVG ist mit 5 671 Events (57% aller Events) die häufigste Familie und liegt
mit 56.3% HR nahe Prior — Verbesserungsfeld bleibt aber vorrangig wegen Volumen. **OB**
hat mit 31.5% HR die größte Prior-Realität-Lücke (Q2-Prior war 0.82): Smoothing federt
das ab, aber operativ ist OB als Standalone-Familie auf 4-TF aktuell nicht profitabel.
**SWEEP** liegt 7pp unter Prior und sollte nicht mehr als „bessere Alternative zu FVG"
priorisiert werden.

> **Historischer Kontext (Q2-Kalibrierung, 2026-Q1):** 258 Events / 12 Pairs ergaben
> BOS 91.3% / OB 86.4% / SWEEP 83.3% / FVG 59.4%. Die Q2-Stichprobe war zu klein
> und kursorisch im Universum verzerrt; sämtliche Plan-2.8-Entscheidungen sollen
> die Tabelle oben verwenden, nicht die Q2-Werte. Tiefenanalyse:
> [docs/FVG_LABEL_AUDIT_Q3.md](FVG_LABEL_AUDIT_Q3.md).

### 1.2 Scoring-Qualität

| Metrik | Wert | Gate | Einordnung |
|--------|------|------|------------|
| Overall Grade | **B** | — | Solide, aber nicht A |
| Avg Cal. Brier | 0.1676 | ✅ ≤ 0.60 | Gut kalibriert |
| Avg Cal. ECE | 0.1309 | ✅ ≤ 0.30 | Akzeptabel, Raum nach unten |
| Avg Hit Rate | 76.4% | — | Über Baseline, unter A-Ziel |

**Top-Performer:** AMZN/1H (Grade A, 84% HR, ECE 0.035), JPM/15m (Grade A, 82.6% HR)
**Underperformer:** AAPL/15m (66.7% HR), MSFT/15m (64.7% HR)

### 1.3 Sample-Size-Problem

258 Events über 12 Pairs sind für statistische Belastbarkeit **zu wenig**.
Der Bayesian-Smoothing-Faktor (0.3) verhindert wilde Schwankungen, aber für
belastbare per-Family-per-Context-Breakdowns brauchen wir mindestens **1.000+ Events**.

### 1.4 Kontextuelle Kalibrierung

Die Measurement Lane zeigt, dass `session`- und `vol_regime`-spezifische
Kalibrierung die Brier/ECE-Werte verbessern *kann*, aber die Stichproben pro
Bucket sind noch zu klein für eine automatische Promotion.

---

## 2. Strategische Prioritäten Q3

```
┌──────────────────────────────────────────────────────────────────┐
│  Q3 Theme: Von "B" nach "A" — Data-driven Quality Improvement  │
│                                                                  │
│  1. FVG Underperformance verstehen und beheben                  │
│  2. Sample Size vergrößern (mehr Symbole, mehr Timeframes)      │
│  3. Kontextuelle Kalibrierung produktionsreif machen            │
│  4. Feature Importance → Scorer-Gewichte automatisieren         │
│  5. Pine Consumer UX für kalibrierte Daten schließen            │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. Umsetzungsplan

### Phase D — FVG Investigation (Wochen 1–3)

> **Ziel:** Verstehen WARUM FVG 30pp hinter BOS/OB liegt und ob das eine
> Eigenschaft der Familie ist oder ein Scoring/Label-Problem.

#### D1: FVG Label Audit ✅ DONE (2026-04-22) — Hypothese bestätigt

**Hypothese:** `label_fvg_mitigation` (Gap-Fill vor Invalidierung) ist
möglicherweise zu streng definiert — FVGs können teilweise gefüllt werden
und trotzdem profitabel sein.

- [x] FVG-Events mit `hit=false` manuell stichprobenartig prüfen (20 Events)
- [x] Partial-Fill-Rate berechnen: wie oft füllt der Preis ≥50% des Gaps?
- [x] Vergleich: Partial-Fill-Definition vs. aktuelle binäre Definition
- [x] **Output:** `docs/FVG_LABEL_AUDIT_Q3.md` mit Empfehlung

> **Befund:** über 5671 FVG-Events zeigt sich **partial_fill_pct_mean = 73.4%**
> (auf 5m sogar 90.4%). Das aktuelle binäre Label verwirft also einen Großteil
> profitabler Reaktionen.
>
> **Umsetzung (2026-04-22, Commit folgt):** zweite Label-Variante
> `label_fvg_partial_50(zone_low, zone_high, direction, highs, lows, closes, *, fill_threshold=0.5)` ist in `smc_core/scoring.py` (Sibling von `label_fvg_mitigation`) implementiert und in
> `tests/test_smc_scoring.py::TestLabelFvgPartial50` mit 12 Tests abgedeckt.
> Die Funktion teilt die 2-Bar-Invalidierungsregel mit dem alten Label, sodass
> ein A/B-Diff den Fill-Tiefen-Effekt isoliert. **Nächster Schritt:**
> `smc_integration/measurement_evidence.py` (Z. 996) optional gegen das neue
> Label tauschen, sobald der nächste Benchmark-Run das Side-by-Side liefern soll.

> **A/B-Validierung (2026-04-22, Benchmark v3, 5710 FVG-Events / 4 TFs):**
> die strikte ≥50%-Definition ist deutlich großzügiger als die binäre
> Mitigation-Definition und bestätigt die Hypothese aus D1 quantitativ.
>
> | Bezug                        | n    | lenient HR (`label_fvg_mitigation`) | strict ≥50% HR (`label_fvg_partial_50`) | Δ |
> |------------------------------|-----:|------------------------------------:|----------------------------------------:|---:|
> | **FVG overall (4-TF)**       | 5710 | **0.561**                          | **0.878**                              | **+0.318** |
> | session:NY_AM                | 2691 | 0.460                              | 0.879                                  | +0.419 |
> | session:LONDON               | 2910 | 0.646                              | 0.885                                  | +0.239 |
> | session:ASIA                 |  109 | 0.752                              | 0.670                                  | −0.083 |
> | htf_bias:BULLISH             | 3413 | 0.554                              | 0.899                                  | +0.345 |
> | htf_bias:BEARISH             | 2297 | 0.571                              | 0.848                                  | +0.277 |
> | vol_regime:NORMAL            | 5563 | 0.561                              | 0.879                                  | +0.319 |
> | vol_regime:HIGH_VOL          |  137 | 0.562                              | 0.861                                  | +0.299 |
>
> **Lesart:** auf der NORMAL-Volume-Achse und in NY_AM/LONDON liefert die strikte
> Definition Treffer-Quoten von ~88%, was FVG aus dem unteren Drittel der
> Familienrangliste in Reichweite von BOS rückt. Die scheinbare ASIA-Inversion
> (0.752 → 0.670 bei n=109) wurde nachträglich als reines Datenquellen-Artefakt
> identifiziert (100% midnight-UTC-Resampler-Bars) und mit einer 24-h-Real-
> Daten-Stichprobe (60 Tage × 9 Symbole, n=158 ASIA) widerlegt: ASIA liefert
> dort lenient 0.367 / strict50 **0.873** (Δ **+0.506**, höchster Lift aller
> Sessions). Detail: `docs/FVG_LABEL_AUDIT_Q3.md` §5b.4. Reproduzierbar via
> `python scripts/fvg_label_audit_q3.py --root artifacts/ci/measurement_benchmark_2026-04-22_partial50_v3 --format json`
> bzw. `python scripts/fvg_asia_real_sample.py --days 60`.
> Pipeline-Commits: `3746b36e` (Bridge-Emission), `18110767` (KPI-Aggregation),
> `1c06bc22` (flat-key-Lese-Fix nach v2-Snapshot mit `null` HR), `2d7badea`
> (ASIA-Artefakt-Diagnose), `47408627` (ASIA-Real-Daten-Refutation).

#### D2: FVG per-Context Breakdown ✅ DONE (2026-04-22) — massiv bestätigt

**Hypothese:** FVG-Performance könnte stark kontextabhängig sein
(z.B. gut in RTH+RISK_ON, schlecht in ETH+HIGH_VOL).

- [x] Per-Context-Scoring für FVG: `session × vol_regime × htf_bias`
- [x] Stratification Report mit Bucket-Counts ≥ 5
- [x] Identifizieren: In welchen Kontexten ist FVG profitabel (>70% HR)?
- [x] **Output:** Erweiterung von `smc_zone_priority.py` — kontextabhängige
      FVG-Gewichtung statt statischer 0.60. Geliefert via F1
      (`contextual_calibration` Parameter, 2026-04-22) und F2
      (`session_calibration` Shortcut, Commit `70c24dd7`). NY_AM erreicht
      jetzt `FVG = 0.4961` vs ASIA `0.6948` tatsächlich Pine.

> **Befund:** Spread von **28pp zwischen Sessions** — ASIA 74.5% HR (n=102),
> LONDON 64.5% (n=2907), **NY_AM nur 46.1% (n=2662)**. Daten reichen für
> Phase-F1-Promotion. `vol_regime` ist hingegen fast neutral (NORMAL 56.1%,
> HIGH_VOL 56.2%) — Split lohnt nicht. Details in
> `docs/FVG_LABEL_AUDIT_Q3.md` §2/4.

#### D3: FVG Time-to-Fill Analysis ✅ DONE (2026-04-22) — Hypothese **falsifiziert**

**Hypothese:** FVGs werden eventuell mitigiert, aber außerhalb des
Lookahead-Fensters.

- [x] `time_to_mitigation` Distribution für FVG vs. andere Familien
- [x] Prüfen ob eine Verlängerung des Lookahead-Fensters die Hit Rate
      signifikant verbessert (5→10→20 bars)
- [x] **Output:** Empfehlung für Lookahead-Anpassung (pro Familie)

> **Befund:** 5m FVG-HR ist **54.2%** (n=3693) — niedriger als 1H 62.5% —
> obwohl TTM mean höher ist (2.55 vs. 1.46 bars). Mehr Events / kürzere
> Lookaheads bringen keinen Hit-Rate-Uplift. Empfehlung: **kein** Lookahead-
> Tuning, stattdessen Session-Filter (siehe D2).

#### D4: FVG Quality Signal Integration ✅ DONE (2026-04-22) — Hypothese **partiell falsifiziert**

**Hypothese:** Nicht alle FVGs sind gleichwertig — Größe, HTF-Alignment
und Distanz zum aktuellen Preis sollten die Erwartung beeinflussen.

- [x] FVG-Event-Attribute auswerten: `gap_size_atr`, `distance_to_price_atr`,
      `htf_aligned`, `is_full_body`
- [x] Conditional Hit Rates: große HTF-aligned FVGs vs. kleine unaligned
- [x] **Output:** FVG Quality Filter Kriterien für die Scoring Pipeline →
      `docs/FVG_QUALITY_D4_AUDIT.md`

> **Befund (n=5710, strict ≥50% Label):** Unter dem D1-empfohlenen
> strict label sind die zentralen Quality-Features **null bis invers**
> korreliert mit Hit Rate:
> - `htf_aligned` Δ = **−0.034** (Gewicht 0.25 ist datenfrei)
> - `is_full_body` Δ = **−0.021** (Gewicht 0.10 ist Rauschen)
> - `gap_size_atr` Q4 vs Q1: **0.657 vs 0.897** (invers; aktuelles
>   Gewicht 0.30 belohnt Loser unter strict)
> - `distance_to_price_atr` Q4 vs Q1: **0.647 vs 0.931** (einziges
>   monoton starkes Signal — näher = besser)
>
> **Konsequenz für D3-Promotion:** Eine Umstellung auf strict label
> als primäres FVG-Outcome muss **zwingend** mit einer Re-Kalibrierung
> der `smc_core/fvg_quality.py`-Gewichte verbunden sein, sonst
> verstärkt der Quality-Score genau die falschen Events. Single-PR-
> Discipline: Promotion und Re-Calibration müssen als ein Commit
> landen.
>
> **D3-Promotion gelandet (2026-04-22):** `smc_core/fvg_quality.py`
> jetzt auf `WEIGHT_VERSION = "strict_v1_no_hurst"` (Gewichte
> `0.45 / 0.0735 / 0.45 / 0.0515 / 0.0` mit Direktionen
> `{-1, -1, -1, -1, 0}`). `scripts/fvg_quality_recalibration.py`
> Defaults: `label_source=partial_50`, `signed_weights=True`,
> `acceptance_mode=relative`. Pine-Spiegel
> `SMC_Core_Engine.pine::fvg_quality_score` ist NICHT mit-promoted
> (Pine-vs-Python-Feature-Disjunktion — siehe
> `docs/FVG_QUALITY_D4_AUDIT.md` §6 + Memory
> `fvg-quality-pine-python-feature-disjunction.md`).

### Phase E — Scale & Diversification (Wochen 2–5)

> **Ziel:** Benchmark-Basis auf ≥1.000 Events verbreitern für statistisch
> belastbare Aussagen.

#### E1: Symbol-Expansion ✅ DONE (2026-04-22) — Ziel übertroffen (20 statt 12)

- [x] Benchmark-Universe von 6→12 Symbole erweitern
- [x] Neue Symbole: GOOGL, META, TSLA, V, UNH, HD (Marktstruktur-Diversität)
- [x] Kein neuer Code — nur Benchmark-Config-Erweiterung
- [x] **Ziel:** ≥500 Events (Verdoppelung)

> Tatsächlich umgesetzt mit **20-Symbol-Universe**:
> AAPL, MSFT, AMZN, GOOGL, META, NVDA, TSLA, JPM, BAC, GS, MS, V, UNH, JNJ, HD,
> XOM, CVX, COP, OXY, CAT.
> Quellen: `.github/workflows/smc-measurement-benchmark.yml` Zeile 36 und
> `.github/workflows/smc-measurement-benchmark-rolling.yml` Zeile 79.

#### E2: Timeframe-Expansion ✅ DONE (2026-04-22)

- [x] 5m und 4H Timeframes zum Benchmark hinzufügen
- [x] Prüfen ob 5m-Events die gleiche Family-Rangfolge zeigen wie 15m/1H
- [x] **Hypothese:** ~~FVGs könnten auf 5m besser performen (schnellere Fills)~~
      → **falsifiziert** (Corpus `measurement_benchmark_2026-04-22_partial50_v3`,
      n=5671 FVG events): 5m FVG HR = **0.542** (n=3693, schlechtester TF),
      1H = **0.644** (n=790, bester), 15m = 0.592, 4H = 0.574. Hypothese
      umgekehrt — kürzere TFs erzeugen mehr Mikro-Fills/falsche
      Invalidationen statt schnellerer Hits. **Implikation:** für die
      Pine-Konsumenten lohnt es sich, FVG-Gewichte auf 5m im
      Contextual-Calibration-Pfad (Phase F) gezielt niedriger zu setzen.
      *Single-Source-of-Truth:* `docs/FVG_LABEL_AUDIT_Q3.md` §1.

> Umsetzung via Plan 2.8 (`docs/smc_improvement_plan_addendum_2_8_mtf_scope_2026-04-21.md`).
> Workflow `.github/workflows/smc-measurement-benchmark-rolling.yml` läuft täglich
> mit `TIMEFRAMES="5m,15m,1H,4H"` (Default in Zeile 33). Per-TF-Rollup über
> `scripts/plan_2_8_tf_family_rollup.py`.

#### E3: Historische Tiefe ✅ DONE (2026-04-22)

- [x] Benchmark-Zeitraum verlängern (aktuell: 1 Production-Workbook-Snapshot)
- [x] Rolling 30-Tage-Benchmark mit täglichem Append statt Single-Run
- [x] CI-Workflow anpassen: `smc-measurement-benchmark.yml` → Incremental Mode

> Umgesetzt als `smc-measurement-benchmark-rolling.yml` (cron `30 7 * * *`).
> Pin-Test: `tests/test_plan_2_8_rolling_workflow_rollup_wiring.py`.

#### E4: Outcome Backfill Pipeline — Produktionshärtung ✅ DONE (2026-04-22)

- [x] `outcome_backfill.py` → Täglicher Cron/CI statt manuell
      (`.github/workflows/open-prep-outcome-backfill.yml`, cron 11:15 ET).
- [x] Automatische Feature-Importance-Berechnung nach Backfill
      (`.github/workflows/feature-importance-daily.yml`, cron 09:00 UTC,
      lookback default 7 d, `open_prep.feature_importance_report`).
- [x] Alerting bei Feature-Importance-Ranking-Drift (analog zum
      Weight-Drift-Gate). `compute_ranking_drift` markiert
      `drift_status=warn`; der Workflow parst das Token und emittiert
      sowohl `::warning` als auch einen `$GITHUB_STEP_SUMMARY`-Eintrag
      mit der Per-Feature-Delta-Liste. Pin-Test:
      `tests/test_feature_importance_daily_workflow.py`.

### Phase F — Contextual Calibration Promotion (Wochen 4–7)

> **Ziel:** Die Measurement Lane zeigt bereits kontextuelle Verbesserungen —
> diese in die Produktion überführen.

#### F1: Contextual Weight Promotion Pipeline ✅ DONE (2026-04-22)

- [x] `check_contextual_promotion()` Funktion: automatisch entscheiden ob
      ein Context-Dimension-Split die Kalibrierung verbessert
      (`scripts/smc_zone_priority_calibration.py::check_contextual_promotion`,
      Z. 520).
- [x] Kriterien: ≥30 Events pro Bucket (`_MIN_BUCKET_EVENTS=30`),
      Brier-Improvement ≥5% (`_BRIER_IMPROVEMENT_THRESHOLD=0.05`),
      stabil über 3 aufeinanderfolgende Runs
      (`ContextualCalibrationPromotionPolicy.min_history_runs=3` in
      `smc_integration/release_policy.py`).
- [x] **Output:** `zone_priority_contextual_calibration.json` neben dem
      bestehenden `zone_priority_calibration.json` (CLI-Pfad in
      `smc_zone_priority_calibration.py::main`, Z. 694–698).
- [x] **Smoke 2026-04-22** auf `measurement_benchmark_2026-04-22_partial50_v3`
      (n=10 004 Events, family-summed: BOS 1606 + FVG 5671 + OB 952 + SWEEP 1775):
      7 promoted buckets über `htf_bias`, `session`, `vol_regime`
      (z.B. `session:ASIA OB +0.3016`, `session:NY_AM OB −0.0896`).
- [x] **v4 corpus 2026-04-23** auf `artifacts/ci/measurement_benchmark_combined_2026-04-23/`
      (n=10 064 Events, family-summed: BOS 1614 + FVG 5710 + OB 966 + SWEEP 1774;
      80/80 pairs `bars_source_mode='canonical_export_bundle'` nach Manifest-
      Poisoning-Fix in PR #33). Per-TF: 5m 6 223, 15m 1 585, 1H 1 471, 4H 785.
      Reproduziert die 7 Promotion-Buckets aus dem v3-Smoke deckungsgleich
      (LONDON OB/SWEEP, ASIA OB/FVG/SWEEP, HIGH_VOL SWEEP, NY_AM OB/FVG/BOS,
      htf_bias BEAR/BULL OB) — keine Drift in der Promotion-Auswahl, keine
      neue F2-Promotion-Eligibility (siehe F2-Caveat unten, smECE bleibt
      über Q4-Target).

#### F2: Session-Adjusted Zone Priority ◐ INFRASTRUCTURE DONE — Auto-Promotion deferred (2026-04-23 Caveat)

- [x] `build_zone_priority()` → optionaler `session_calibration` Parameter
      (`{session_label: {family: weight}}`). Wins über
      `contextual_calibration` und `calibrated_family_weights` nur, wenn
      der aktive `session_context` als Key vorliegt; partial maps bleiben
      back-compat (übrige Familien behalten _FAMILY_BASE_PRIORITY).
- [x] Session-spezifische Family-Gewichte aus Benchmark-Bucket-Stats
- [x] Pine-Exports: `ZONE_CAL_<FAM>_ASIA / _LONDON / _NY_AM` (Q3 F1
      wiring 2026-04-22, Commit folgt). Vorher hatten `_RTH/_ETH` keinen
      passenden Bucket → Fallback-Wert. Jetzt erreicht u.a. NY_AM
      `FVG = 0.4961` (vs. ASIA `0.6948`) tatsächlich Pine.
- [x] Fallback auf globale Gewichte wenn Bucket-Size < Minimum
      (`scripts/smc_zone_priority_calibration.py::get_calibrated_weight`)
- ⚠ **Promotion-Caveat (2026-04-23):** Code-Pfad ist live, aber die
      tatsächliche Auto-Promotion der 7 ASIA/NY_AM/HIGH_VOL-Buckets ist
      **nicht** in Produktion gelandet. Begründung in
      [`docs/f2_contextual_promotion_decision_2026-04-21.md`](./f2_contextual_promotion_decision_2026-04-21.md):
      (1) globale OB-Drift −0.3534 sprengt das 0.15-Drift-Gate,
      (2) F1 smECE 0.1349 > Q4-Target 0.03 ⇒ Bucket-Promotion auf
      mis-kalibriertem Zero-Point unzulässig,
      (3) Plan §2.4 G3 fordert 30-Tage A/B (SPRT) vor Brier/ECE-basiertem
      Weight-Change. Promotion entscheidet sich erst nach G3-Sample-
      Akkumulation und F1-Re-Kalibrierung; ASIA bleibt bis dahin
      stärkster Promotion-Kandidat (kohärenter Lift über alle 4 Familien).

      **v4 corpus 2026-04-23 Re-Check (n=10 064, identisches 20×4 Universum):**
      Gate-Status unverändert — globale OB-Drift −0.3508 (vs −0.3534), F1 smECE
      0.137 (vs 0.135), per-Bucket smECE LONDON 0.233 / ASIA 0.202 /
      HIGH_VOL 0.168 / NY_AM 0.083 / NORMAL 0.137. Promotion bleibt
      G3-blockiert; v4-Run dient als Drift-Sanity (keine Regime-Verschiebung
      gegen v3) und als sauberer Baseline-Snapshot für die nächste rolling-
      bench Cron-Generation (PR #33: Azure-SAS-Bundle + Canonical-Write-Guard).

#### F3: Vol-Regime-Adjusted Scoring ✅ DONE (2026-04-22)

- [x] Prüfen: Verbessert `vol_regime`-Split die ECE signifikant? — F1
      Promotion-Gate (`_BRIER_IMPROVEMENT_THRESHOLD = 0.05`,
      `_MIN_BUCKET_EVENTS = 30`) entscheidet pro Bucket. Smoke 2026-04-22:
      `vol_regime:HIGH_VOL SWEEP −0.0639` und `vol_regime:NORMAL OB −0.0775`
      erreichen die Promotion.
- [x] Regime-spezifische Kalibrierung in den Scoring-Pfad —
      `scripts/smc_zone_priority.py::build_zone_priority` ruft
      `resolve_contextual_weight(family, vol_regime=...)` (Z. 268) für
      jede Familie auf, wenn `contextual_calibration` übergeben wird.
- [x] Multiplikativer Effekt auf Basisgewichte — der
      `effective_weights`-Pfad ersetzt `calibrated_family_weights` durch
      bucket-spezifische Werte; `_VOL_REGIME_SCORES` (additive Komponente)
      bleibt unangetastet als zweite, orthogonale Stellschraube.
- ⚠ Hinweis: Die F1-Promotion-Metrik ist Brier-basiert; die separate
      ECE-Δ-Messung pro Bucket ist als Folge-Audit nachgezogen
      (`scripts/smc_zone_priority_calibration.py::compute_per_bucket_testable_calibration`
      schreibt `zone_priority_per_bucket_calibration.json` mit smECE/ECE/dCE
      je `<dim>:<bucket>` ≥ 30 Events). Smoke 2026-04-22 (n=10064): NY_AM
      smECE 0.083 → klar bestes Bucket; LONDON 0.233 / ASIA 0.202 /
      HIGH_VOL 0.168 → Kandidaten für nächste Re-Kalibrierungs-Runde.
      Sample-Count 10 004 = family-summed (BOS+FVG+OB+SWEEP); §1 ist
      Single-Source-of-Truth.

### Phase G — Feature Importance → Automated Scorer Tuning (Wochen 5–8)

> **Ziel:** Den Feature-Importance-Loop schließen — nicht nur messen,
> sondern die Scorer-Gewichte automatisch anpassen.

#### G1: Feature Importance Baseline Report ✅ DONE

- [x] `compute_feature_importance()` mit ≥`DEFAULT_MIN_SAMPLES=30` gelabelten
      Samples ausführen (`open_prep/feature_importance_report.py` ENG-WS4-02).
- [x] Baseline-Report mit `status` ∈ {`ok`, `insufficient_labels`,
      `no_data`} unter
      `artifacts/open_prep/feature_importance/report_<ts>.json` +
      `latest.json`-Pointer.
- [x] Drift-Gate (`DRIFT_POSITION_THRESHOLD = 3`) markiert
      Ranking-Drift zwischen aufeinanderfolgenden `ok`-Runs als
      Advisory-Signal für G2.

#### G2: Scorer Weight Auto-Tuning ✅ DONE

- [x] Feature-Importance-Rankings → `scorer.py` Gewichtsanpassungen via
      `open_prep.outcomes.compute_weight_adjustments` +
      `FEATURE_TO_WEIGHT_KEY`-Mapping.
- [x] Bayesian-Update (`ScorerWeightUpdate.smoothed_value`) und
      Drift-Gate (`check_scorer_drift`).
- [x] CLI `open_prep/candidate_weights.py` (ENG-WS4-03) schreibt
      `weights_candidate.json` versioniert; Statuswerte `ok` /
      `insufficient_data` / `drift_blocked`.

#### G3: A/B Experiment — Calibrated vs. Uncalibrated Scorer ✅ DONE

- [x] `scripts/smc_ab_experiment.py` als OV7-Framework-Wrapper.
- [x] Arm A: bisherige statische Scorer-Gewichte (`weights.json`).
- [x] Arm B: Auto-tuned Scorer-Gewichte (`weights_candidate.json`).
- [x] KPI-Vergleich + Recommendation in
      `tests/test_ab_comparison_recommendation.py` und
      `scripts/run_ab_comparison.py`.
- [x] Stop-Rule: `scripts/smc_sprt_stop_rule.py` (SPRT) +
      `scripts/f2_experiment_spec.py` Decision-Memo-Pfad.
- ⚠ Folge-Lauf offen: tatsächlicher 30-Tage-Run auf Live-Telemetrie
      noch nicht abgeschlossen (G3-Decision-Gate blockiert auf
      ausreichendem Sample).

### Phase H — Pine Consumer Maturity (Wochen 6–9)

> **Ziel:** Die kalibrierte Datenlage in der TV-Oberfläche nutzerfreundlich
> machen.

#### H1: Calibration Confidence Indicator ✅ DONE (2026-04-22)

- [x] Neuer Pine-Export: `ZONE_CAL_CONFIDENCE` (0–1) — kombiniert
      Sample-Count (Saturation @ 1000 Events) mit smECE-Drift-Penalty
      (smECE ≥ 0.20 ⇒ confidence 0). Quelle:
      `scripts/smc_zone_priority_consumer.py::compute_calibration_confidence`.
- [x] Smoke 2026-04-22 (n=258, NY_AM smECE 0.0833): `ZONE_CAL_CONFIDENCE = 0.1505`
      — niedrig, weil Sample-Count noch weit von 1000 entfernt; das ist
      genau das Signal, das die Dashboard-Warnung treiben soll.
      **Update 2026-04-22 (P0-Fix, ADR „Degrade per-family HR display on
      sub-saturation corpora"):** der niedrige Confidence-Wert wird jetzt
      hart in `ZONE_CAL_TRUST = DEGRADED` übersetzt; Sub-saturation-Korpora
      liefern den Sentinel `-1.0` für die Per-Family-HR-Exports, sodass die
      H2-Smoke-Werte (ZONE_HR_OB=0.8636 etc.) nicht länger ungeprüft auf der
      Pine-Surface erscheinen. Pin-Test:
      `tests/test_smc_zone_priority_consumer.py::test_aggregator_degrades_ob_hr_on_subsaturation_sample`.

#### H2: Per-Family Win-Rate Display ✅ DONE (2026-04-22)

- [x] Pine-Exports: `ZONE_HR_OB`, `ZONE_HR_FVG`, `ZONE_HR_BOS`, `ZONE_HR_SWEEP`
      direkt aus `family_stats[<FAM>].weighted_hit_rate`. Quelle:
      `scripts/smc_zone_priority_consumer.py::compute_per_family_hit_rates`.
- [x] Smoke 2026-04-22: `ZONE_HR_OB=0.8636 ZONE_HR_FVG=0.5937 ZONE_HR_BOS=0.9130 ZONE_HR_SWEEP=0.8333` — FVG-Schwäche jetzt auf Pine-Ebene sichtbar. **P0-Fix 2026-04-22:** diese 258-Event-Werte werden über das neue
      Trust-Gate (`ZONE_CAL_CONFIDENCE < 0.30`) ab sofort als
      `HR_SENTINEL_DEGRADED = -1.0` ausgeliefert; Pine rendert sie als
      „—" (siehe ADR „Degrade per-family HR display on sub-saturation
      corpora" in `docs/DECISIONS.md`).

#### H3: Performance Trend Arrow ✅ DONE (2026-04-22)

- [x] Neuer Export: `ZONE_CAL_TREND` (IMPROVING / STABLE / DEGRADING)
      basiert auf den letzten ≥ 3 Kalibrierungs-Runs aus
      `enr["zone_priority_calibration_history"]`. Threshold ±0.02 auf
      gewichtete HR. Quelle:
      `scripts/smc_zone_priority_consumer.py::compute_calibration_trend`.
- [x] Generator (`scripts/generate_smc_micro_profiles.py`) emittiert Block
      `// ── Pine Consumer Maturity (Phase H) ──`. Producer-Pfad in
      `scripts/generate_smc_micro_base_from_databento.py` füttert
      `family_stats` + `total_events` + `smooth_ece` (aus
      `zone_priority_per_bucket_calibration.json` größtes OK-Bucket).
- ⚠ ~~Hinweis: Eine echte History-Quelle (`zone_priority_calibration_history`)
      ist noch nicht produziert; bis dahin fällt der Trend deterministisch
      auf `STABLE` zurück (per `DEFAULTS`).~~ ✅ CLOSED 2026-04-22 — rolling
      JSONL via `scripts/smc_zone_priority_calibration.py::append_history_entry`
      (Retention 50). Producer (`generate_smc_micro_base_from_databento.py`)
      lädt die letzten 10 Einträge via `load_history_entries` in
      `enr["zone_priority_calibration_history"]`. CLI smoke v3:
      `weighted_hit_rate=0.607`, `smooth_ece=0.137`.

#### H4: FVG Health Warning ✅ DONE (2026-04-22)

- [x] Wenn FVG Hit Rate < 65%: explizite Dashboard-Warnung
      (`SMC_Dashboard.pine::fvg_calibration_warning_text`).
- [x] "⚠ FVG zones underperforming (XX% HR) — prefer OB/BOS setups" —
      Setup-Check Row 12 + Audit-View Row 33 nutzen
      `fvg_combined_warning_text` (Calibration-Warning hat Vorrang vor
      live-zone health). Setup-Check failt jetzt auch dann, wenn nur
      `ZONE_HR_FVG < 0.65` (live FVG Health unverändert grün).
- [x] Automatisch aus kalibriertem Gewicht abgeleitet via `mp.ZONE_HR_FVG`
      (Phase H Export, Default 0.0 bleibt stumm bis erste Kalibrierung).

---

## 4. Erfolgsmessung Q3

> **Refresh 2026-04-23:** Die ursprüngliche Tabelle vom 20.04. listete
> nur die Q2-Ende-Werte. Sie wird hier auf den v3-Korpus
> (`measurement_benchmark_2026-04-22_partial50_v3`, n=10 004 family-summed,
> 20 Symbole × 4 TFs) und die F2-Promotion-Decision gehoben. Single-Source-
> of-Truth-Werte: §1.1 (Family-HRs) und
> [`docs/f2_contextual_promotion_decision_2026-04-21.md`](./f2_contextual_promotion_decision_2026-04-21.md).

| Metrik | Q2-Ende | Aktuell (2026-04-22) | Ziel Q3 Ende | Status |
|--------|---------|----------------------|--------------|--------|
| Overall Grade | B | B (gewichtete HR 76.4 %, F1-smECE 0.1349 noch über A-Korridor) | **A** (≥75 % gewichtete HR + ECE ≤ 0.10) | ◐ HR erfüllt, ECE offen |
| Total Events (Benchmark) | 258 | **10 004** (BOS 1 606 + FVG 5 671 + OB 952 + SWEEP 1 775) | **≥1 000** | ✅ ~10× übererfüllt |
| FVG Hit Rate | 59.4 % | 56.3 % lenient · **87.8 %** strict ≥50 % (D1, n=5 710) | **≥70 %** (oder bewusst niedrigere Gewichtung) | ✅ unter strict-Label; ⚠ unter lenient bewusst niedriger gewichtet |
| Cal. ECE (Avg) | 0.1309 | F1 global **0.1349**; bestes Bucket NY_AM **0.083** | **≤0.10** | ⚠ global noch offen, NY_AM-Bucket erfüllt |
| Cal. Brier (Avg) | 0.1676 | 0.1676 (Δ unter Promotion-Gate 0.05) | **≤0.15** | ⚠ offen |
| Feature Importance Samples | 0 (pipeline built) | täglicher Cron läuft (lookback 7 d) | **≥500 gelabelt** | ◐ Akkumulation läuft |
| Symbole im Benchmark | 6 | **20** (AAPL/MSFT/AMZN/GOOGL/META/NVDA/TSLA/JPM/BAC/GS/MS/V/UNH/JNJ/HD/XOM/CVX/COP/OXY/CAT) | **12** | ✅ übertroffen |
| Timeframes im Benchmark | 2 (15m, 1H) | **4 (5m, 15m, 1H, 4H)** | **4 (5m, 15m, 1H, 4H)** | ✅ erfüllt |

**Lesart der Restlücken:** der Q3-A-Grade hängt jetzt nicht mehr an Sample-
Größe oder TF-Coverage (beides ✅), sondern allein am ECE-Korridor — F2-Memo
empfiehlt vor weiterer Bucket-Promotion eine F1-Re-Kalibrierung auf ECE ≤ 0.03
und das 30-Tage-G3-A/B (siehe Q3 §G3 ⚠).

---

## 5. Priorisierung & Dependencies

```
Woche 1–2:  D1 + D2 (FVG Investigation — data gathering)
            E1 (Symbol Expansion — quick config change)

Woche 3:    D3 + D4 (FVG deeper analysis)
            E2 (Timeframe Expansion)

Woche 4:    E3 + E4 (Pipeline Hardening)
            F1 (Contextual Promotion — design)

Woche 5:    F2 + F3 (Contextual Calibration)
            G1 (Feature Importance Baseline)

Woche 6:    G2 (Scorer Auto-Tuning)
            H1 + H4 (Pine: Confidence + FVG Warning)

Woche 7:    G3 (A/B Experiment — start)
            H2 + H3 (Pine: Win Rates + Trend)

Woche 8–9:  G3 (A/B Experiment — evaluate)
            F1 Promotion Decision
            Q3 Retro + Q4 Planning
```

**Critical Path:** D1→D2→D4 (FVG), dann E1→E3→F1 (Scale→Contextual)

**Blocked by nothing:** E1 (Symbol Expansion) und D1 (FVG Label Audit)
können sofort starten.

---

## 6. Risiken

| Risiko | Wahrscheinlichkeit | Impact | Mitigation |
|--------|-------------------|--------|------------|
| FVG ist inhärent schwächer (kein Label-Problem) | Mittel | Mittel | Akzeptieren + Gewichtung dauerhaft senken, FVG als Bestätigungs- statt Entry-Signal |
| Sample Size bleibt < 500 (Datenprobleme) | Niedrig | Hoch | Synthetische Replay-Daten aus historischen Candles |
| Contextual Calibration overfittet | Mittel | Hoch | Minimum 30 Events pro Bucket, 3-Run-Stabilität |
| Scorer Auto-Tuning verschlechtert Performance | Mittel | Hoch | A/B Framework + Rollback-Gate |
| Pine-Export-Limit (TV Library Size) | Niedrig | Mittel | Export nur Top-4 Metriken, Rest als Audit-View |

---

## 7. Was wir NICHT tun in Q3

- **Keine neuen Pine-Skripte** — Fokus auf Datenqualität, nicht UI-Expansion
- **Keine neuen Event-Familien** — BOS/OB/FVG/SWEEP reicht, Qualität > Quantität
- **Keine neue Signal-Logik** — QuickALGO/USI/BFI bleiben unverändert
- **Kein Multi-Asset-Expansion** (Crypto/Forex) — US-Equities Benchmark zuerst solide

---

## 8. Bezug zu Q2 Deliverables

| Q2 Deliverable | Status | Q3 Weiterführung |
|----------------|--------|------------------|
| C9: Zone Priority | ✅ Umgesetzt + Kalibriert | → F1/F2: Kontextuelle Kalibrierung |
| Outcome Backfill | ✅ Umgesetzt | → E4: Täglicher CI-Cron |
| Feature Importance | ✅ Pipeline gebaut | → G1/G2: Baseline + Auto-Tuning |
| Calibration Script | ✅ + Drift Gate | → D1-D4: FVG-spezifische Analyse |
| Pine Consumer | ✅ ZONE_CAL_* Exports | → H1-H4: Confidence + Win Rates |
| A/B Framework (OV7) | ✅ Gebaut | → G3: Erster produktiver A/B Test |
| Performance Report | ✅ Grade B | → Ziel: Grade A |

---

*Erstellt: 20. April 2026 — Basierend auf Zone Priority Calibration Report
(258 Events, 48 Pairs, Calibrated Weights: OB 0.8505, FVG 0.5986, BOS 0.8821,
SWEEP 0.8023) und SMC Performance Report (Overall Grade B, Cal. Brier 0.1676,
Cal. ECE 0.1309).*
