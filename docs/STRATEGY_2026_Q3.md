# SkippALGO / SMC — Strategischer Fahrplan Q3 2026

> **Basiert auf:** Kalibrationsdaten (258 Events, 12 Pairs, 6 Symbole),
> Performance Report (Overall Grade B), Zone Priority Feedback Loop (4/4 Phasen abgeschlossen),
> Q2 System Review (alle 10 WPs A1–C10 umgesetzt).
>
> **Datum:** 20. April 2026

---

## 1. Was die Daten sagen

### 1.1 Family Hit Rates — Kalibrierte Gewichte

| Family | Events | Hit Rate | Prior | Kalibriert | Δ | Bewertung |
|--------|-------:|----------:|------:|-----------:|---:|-----------|
| **BOS** | 46 | **91.3%** | 0.81 | 0.8821 | +7.2% | ⬆ Stärkste Familie — überperformt deutlich |
| **OB** | 44 | **86.4%** | 0.82 | 0.8505 | +3.1% | ⬆ Solide, leicht über Prior |
| **SWEEP** | 72 | **83.3%** | 0.73 | 0.8023 | +7.2% | ⬆ Stärker als erwartet |
| **FVG** | 96 | **59.4%** | 0.61 | 0.5986 | −1.1% | ⬇ **Schwächste Familie** — braucht Untersuchung |

**Kernbefund:** FVG hat die meisten Events (96, 37% aller Events), aber die schlechteste Hit Rate (59.4%). Das ist das größte Verbesserungspotenzial im gesamten System.

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

#### D1: FVG Label Audit

**Hypothese:** `label_fvg_mitigation` (Gap-Fill vor Invalidierung) ist
möglicherweise zu streng definiert — FVGs können teilweise gefüllt werden
und trotzdem profitabel sein.

- [ ] FVG-Events mit `hit=false` manuell stichprobenartig prüfen (20 Events)
- [ ] Partial-Fill-Rate berechnen: wie oft füllt der Preis ≥50% des Gaps?
- [ ] Vergleich: Partial-Fill-Definition vs. aktuelle binäre Definition
- [ ] **Output:** `docs/FVG_LABEL_AUDIT_Q3.md` mit Empfehlung

#### D2: FVG per-Context Breakdown

**Hypothese:** FVG-Performance könnte stark kontextabhängig sein
(z.B. gut in RTH+RISK_ON, schlecht in ETH+HIGH_VOL).

- [ ] Per-Context-Scoring für FVG: `session × vol_regime × htf_bias`
- [ ] Stratification Report mit Bucket-Counts ≥ 5
- [ ] Identifizieren: In welchen Kontexten ist FVG profitabel (>70% HR)?
- [ ] **Output:** Erweiterung von `smc_zone_priority.py` — kontextabhängige
      FVG-Gewichtung statt statischer 0.60

#### D3: FVG Time-to-Fill Analysis

**Hypothese:** FVGs werden eventuell mitigiert, aber außerhalb des
Lookahead-Fensters.

- [ ] `time_to_mitigation` Distribution für FVG vs. andere Familien
- [ ] Prüfen ob eine Verlängerung des Lookahead-Fensters die Hit Rate
      signifikant verbessert (5→10→20 bars)
- [ ] **Output:** Empfehlung für Lookahead-Anpassung (pro Familie)

#### D4: FVG Quality Signal Integration

**Hypothese:** Nicht alle FVGs sind gleichwertig — Größe, HTF-Alignment
und Distanz zum aktuellen Preis sollten die Erwartung beeinflussen.

- [ ] FVG-Event-Attribute auswerten: `gap_size_atr`, `distance_to_price`,
      `htf_aligned`, `is_full_body`
- [ ] Conditional Hit Rates: große HTF-aligned FVGs vs. kleine unaligned
- [ ] **Output:** FVG Quality Filter Kriterien für die Scoring Pipeline

### Phase E — Scale & Diversification (Wochen 2–5)

> **Ziel:** Benchmark-Basis auf ≥1.000 Events verbreitern für statistisch
> belastbare Aussagen.

#### E1: Symbol-Expansion

- [ ] Benchmark-Universe von 6→12 Symbole erweitern
- [ ] Neue Symbole: GOOGL, META, TSLA, V, UNH, HD (Marktstruktur-Diversität)
- [ ] Kein neuer Code — nur Benchmark-Config-Erweiterung
- [ ] **Ziel:** ≥500 Events (Verdoppelung)

#### E2: Timeframe-Expansion

- [ ] 5m und 4H Timeframes zum Benchmark hinzufügen
- [ ] Prüfen ob 5m-Events die gleiche Family-Rangfolge zeigen wie 15m/1H
- [ ] **Hypothese:** FVGs könnten auf 5m besser performen (schnellere Fills)

#### E3: Historische Tiefe

- [ ] Benchmark-Zeitraum verlängern (aktuell: 1 Production-Workbook-Snapshot)
- [ ] Rolling 30-Tage-Benchmark mit täglichem Append statt Single-Run
- [ ] CI-Workflow anpassen: `smc-measurement-benchmark.yml` → Incremental Mode

#### E4: Outcome Backfill Pipeline — Produktionshärtung

- [ ] `outcome_backfill.py` → Täglicher Cron/CI statt manuell
- [ ] Automatische Feature-Importance-Berechnung nach Backfill
- [ ] Alerting bei Feature-Importance-Ranking-Drift (analog zum Weight-Drift-Gate)

### Phase F — Contextual Calibration Promotion (Wochen 4–7)

> **Ziel:** Die Measurement Lane zeigt bereits kontextuelle Verbesserungen —
> diese in die Produktion überführen.

#### F1: Contextual Weight Promotion Pipeline

- [ ] `check_contextual_promotion()` Funktion: automatisch entscheiden ob
      ein Context-Dimension-Split die Kalibrierung verbessert
- [ ] Kriterien: ≥30 Events pro Bucket, Brier-Improvement ≥5%, stabil
      über 3 aufeinanderfolgende Runs
- [ ] **Output:** `zone_priority_contextual_calibration.json` neben dem
      bestehenden `zone_priority_calibration.json`

#### F2: Session-Adjusted Zone Priority

- [ ] `build_zone_priority()` → optionaler `session_calibration` Parameter
- [ ] RTH-spezifische vs. ETH-spezifische Family-Gewichte
- [ ] Pine-Exports: `ZONE_CAL_OB_RTH`, `ZONE_CAL_OB_ETH` etc.
- [ ] Fallback auf globale Gewichte wenn Bucket-Size < Minimum

#### F3: Vol-Regime-Adjusted Scoring

- [ ] Prüfen: Verbessert `vol_regime`-Split die ECE signifikant?
- [ ] Falls ja: Regime-spezifische Kalibrierung in den Scoring-Pfad
- [ ] Aktuell: `vol_regime` beeinflusst nur `_select_top_family()` additiv —
      könnte multiplikativ auf die Basisgewichte wirken

### Phase G — Feature Importance → Automated Scorer Tuning (Wochen 5–8)

> **Ziel:** Den Feature-Importance-Loop schließen — nicht nur messen,
> sondern die Scorer-Gewichte automatisch anpassen.

#### G1: Feature Importance Baseline Report

- [ ] `compute_feature_importance()` mit ≥100 gelabelten Samples ausführen
- [ ] Baseline-Report: Welche der 15 Feature-Keys korrelieren am stärksten
      mit `profitable_30m`?
- [ ] **Erwartung:** `zone_priority_score`, `ensemble_quality`, `rvol`
      sollten starke Prädiktoren sein

#### G2: Scorer Weight Auto-Tuning

- [ ] Feature-Importance-Rankings → `scorer.py` Gewichtsanpassungen
- [ ] Bayesian-Update (wie bei Family Weights): smoothed Importance →
      Feature-Gewicht-Adjustment
- [ ] CI-Gate: Scorer-Weight-Drift-Check analog zu `check_drift()`

#### G3: A/B Experiment — Calibrated vs. Uncalibrated Scorer

- [ ] `smc_ab_experiment.py` nutzen (OV7 Framework, bereits umgesetzt)
- [ ] Arm A: Bisherige Scorer-Gewichte (static)
- [ ] Arm B: Auto-tuned Scorer-Gewichte (aus G2)
- [ ] 30-Tage-Lauf, KPI-Vergleich: Brier, ECE, Hit Rate, P&L
- [ ] **Decision Gate:** Arm B promoted nur bei signifikanter Verbesserung

### Phase H — Pine Consumer Maturity (Wochen 6–9)

> **Ziel:** Die kalibrierte Datenlage in der TV-Oberfläche nutzerfreundlich
> machen.

#### H1: Calibration Confidence Indicator

- [ ] Neuer Pine-Export: `ZONE_CAL_CONFIDENCE` (0–1, basierend auf
      Sample-Count und Drift-Stabilität)
- [ ] Dashboard zeigt: "Kalibrierung: ⬆ Stabil (258 Events)" vs.
      "⚠ Wenig Daten (< 100 Events)"
- [ ] Nutzer weiß, ob er den Zahlen vertrauen kann

#### H2: Per-Family Win-Rate Display

- [ ] Pine-Exports: `ZONE_HR_OB`, `ZONE_HR_FVG`, `ZONE_HR_BOS`, `ZONE_HR_SWEEP`
- [ ] Dashboard Audit View: "OB: 86% HR (44 events)" pro Familie
- [ ] Confluence: Family-spezifische Ampel statt nur Rank

#### H3: Performance Trend Arrow

- [ ] Neuer Export: `ZONE_CAL_TREND` (IMPROVING / STABLE / DEGRADING)
- [ ] Basiert auf letzten 3 Kalibrierungs-Runs: steigt der Score oder fällt er?
- [ ] Dashboard-Zeile: "System Quality: B ⬆" (improving)

#### H4: FVG Health Warning

- [ ] Wenn FVG Hit Rate < 65%: explizite Dashboard-Warnung
- [ ] "⚠ FVG zones underperforming (59% HR) — prefer OB/BOS setups"
- [ ] Automatisch aus kalibriertem Gewicht abgeleitet

---

## 4. Erfolgsmessung Q3

| Metrik | Aktuell (Q2 Ende) | Ziel Q3 Ende |
|--------|-------------------|--------------|
| Overall Grade | B | **A** (≥75% gewichtete HR) |
| Total Events (Benchmark) | 258 | **≥1.000** |
| FVG Hit Rate | 59.4% | **≥70%** (oder bewusst niedrigere Gewichtung) |
| Cal. ECE (Avg) | 0.1309 | **≤0.10** |
| Cal. Brier (Avg) | 0.1676 | **≤0.15** |
| Feature Importance Samples | 0 (pipeline built) | **≥500 gelabelt** |
| Symbole im Benchmark | 6 | **12** |
| Timeframes im Benchmark | 2 (15m, 1H) | **4 (5m, 15m, 1H, 4H)** |

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
