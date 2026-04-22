# Addendum 2.8 — MTF Scope: evaluiert, bewusst nicht erweitert

> **Parent-Dokument:** [smc_improvement_plan_q3_q4_2026-04-20.md](./smc_improvement_plan_q3_q4_2026-04-20.md)
> **Addendum-Typ:** Entscheidungs-Dokumentation (ADR-artig), nicht Umsetzungs-Plan
> **Autor:** Computer (für Steffen Preuss, `skippALGO/skipp-algo`)
> **Datum:** 21. April 2026 (15:38 CEST)
> **Status:** 🟢 Accepted — Teil der Q3-Scope-Definition
> **Evidenz-Markierung:** ✅ im Code · 🧪 getestet · ⚙️ operativ · ⚠ nur plausibel / zu validieren

---

## 0. TL;DR

Die aktuelle 3-Ebenen-HTF-Trendarchitektur (4H / 1D / 1W) plus 1m-LTF-Sampling plus chart-adaptiver IPDA-Selector bleibt in Q3 und Q4 **unverändert**. Erweitert wird ausschließlich die **Chart-TF-Benchmark-Abdeckung** auf zusätzlich 5m und 4H (Phase E2). Eine mögliche 4. Trend-Zwischenebene (Kandidat: 30m oder 2H) ist Q4-Backlog und wird nur umgesetzt, wenn das ≥1000-Event-Sample-Set einen quantifizierbaren HR-Uplift bei nicht-verschlechterter Kalibrierung nachweist. Eine Kopie des 7-TF-Bias-Dashboards von [Flux Market Structure Dashboard](https://www.tradingview.com/script/vXui7vrm-Market-Structure-Dashboard-Flux-Charts/) wird **explizit abgelehnt** — siehe §4.

---

## 1. Kontext & Ausgangsfrage

**Frage:** *„Macht es Sinn, unseren MTF auf weitere Timeframes zu erweitern? Und falls ja, auf welche?"*

**Warum die Frage jetzt kommt:** Wettbewerber werben mit höherer TF-Anzahl (Flux: 7 TFs, konfigurierbar in 1M/5M/15M/1H/4H/D/W/M Slots). Vom Marketing aus betrachtet entsteht ein Vergleichs-Druck. Aus Substanz-Sicht muss die Frage getrennt von Marketing beantwortet werden — sonst triftet die Architektur in Richtung [competitive-analysis Skill](./skills/marketing/competitive-analysis/SKILL.md) Anti-Pattern *„Feature-level comparison tables favor incumbents"*.

**Drei Dimensionen trennen:**

| Dimension | Was es bedeutet | Heutiger Stand |
|---|---|---|
| **Chart-TF-Coverage** | Auf welchen Chart-Zeitrahmen messen wir Events? | 15m + 1H (2 TFs × 12 Pairs = 258 Events) |
| **HTF-Trend-Stack** | Welche höheren TFs fließen in Bias & Gates ein? | 4H / 1D / 1W (3 feste Ebenen) |
| **LTF-Microstructure** | Welcher niedrigere TF wird für OB-Profile und LTF-Volumendelta genutzt? | 1m (fix) |

Die Frage *„mehr TFs?"* kann sich auf jede dieser drei Dimensionen beziehen. Die Antwort ist für jede Dimension unterschiedlich.

---

## 2. Ist-Zustand (✅ im Code verifiziert)

### 2.1 Chart-TF-Coverage

**Code-Referenz:** `scripts/run_smc_measurement_benchmark.py` · `smc-measurement-benchmark.yml`
**Sample:** 258 Events · 12 Pairs · 2 Chart-TFs (15m / 1H) · aus [Deep Review v7 Calibration Report](/home/user/workspace/smc_deep_review_v7_competitive_2026-04-20.md)
**Per-TF-Bucket:** ~129 Events (knapp über Minimum für Bucket-Kalibrierung, grenzwertig für per-Family × per-Context-Splits)

### 2.2 HTF-Trend-Stack

**Code-Referenz:** `SMC_Core_Engine.pine` Zeilen 2326–2329 / 2574–2577:

```pine
const string DEFAULT_LTF_TIMEFRAME = '1'          // Zeile 2326 — 1-Minute LTF
const string DEFAULT_TREND_TF_1    = '240'        // Zeile 2327 — 4H
const string DEFAULT_TREND_TF_2    = '1D'         // Zeile 2328 — Daily
const string DEFAULT_TREND_TF_3    = '1W'         // Zeile 2329 — Weekly

var g_mtf = '7. Advanced - Higher Timeframe Trend'
var string mtf_trend_tf1 = input.timeframe(DEFAULT_TREND_TF_1, 'Trend TF 1', group = g_mtf, ...)
var string mtf_trend_tf2 = input.timeframe(DEFAULT_TREND_TF_2, 'Trend TF 2', group = g_mtf, ...)
var string mtf_trend_tf3 = input.timeframe(DEFAULT_TREND_TF_3, 'Trend TF 3', group = g_mtf, ...)
```

Non-repainting-Sampling via `request.security(syminfo.tickerid, trend_tf, get_structure_display_trend_only(structure_len)[1], gaps = barmerge.gaps_off, lookahead = barmerge.lookahead_off)` (Zeile 2366). Das ist architektonisch korrekt und in 5608 Tests 🧪 abgesichert.

### 2.3 IPDA-Selector (chart-adaptiv)

**Code-Referenz:** `smc_core/htf_context.py` Funktion `select_ipda_htf`:

```python
intraday_short = {"1m", "5m", "15m", "30m", "1H", "2H"}  → IPDA = D
intraday_long  = {"3H", "4H", "6H", "8H", "12H"}          → IPDA = W
D → M   ·   W → 6M   ·   fallback → D
```

Das ist bereits ein **adaptiver** 4.-Ebenen-Mechanismus: Die IPDA-Range passt sich dynamisch dem Chart-TF an. Es ist *nicht* offensichtlich bei Code-Review, aber faktisch verdoppelt es den HTF-Stack auf 4 Ebenen für jede Chart-TF-Wahl.

### 2.4 LTF-Microstructure

1m fix für Profile-Generation (`SMC_Core_Engine.pine` Zeilen 54–58, 281–285) und LTF-Volume-Delta im Dynamic-Alert-Message (`ltf_bull_share`, `ltf_volume_delta`, `ltf_price_only_context` — Zeilen 2368–2396). Sub-Minute (5s / 15s) wäre technisch möglich, aber TradingView-Plan-abhängig und bricht die Reproduzierbarkeit für Free-Tier-Nutzer.

### 2.5 Effektive MTF-Tiefe heute

Zählt man alles zusammen — LTF + Chart-TF + 3 Trend-Ebenen + IPDA-adaptiv — ergibt das eine **5-Oktaven-Stack** ohne dass es explizit so genannt wird:

```
1m (LTF)  →  15m/1H (Chart)  →  4H  →  1D  →  1W  →  M/6M (IPDA adaptive)
                                              [Faktor ~4–6 zwischen Ebenen]
```

Das ist nicht „3 TFs". Das ist, korrekt gezählt, 5–6 TFs mit einem adaptiven Dach-TF.

---

## 3. Evaluation der drei möglichen Erweiterungen

Jeder Pfad wird gegen drei Kriterien geprüft: (a) Erwarteter Uplift, (b) Statistische Belastbarkeit, (c) Kosten (Code, Compute, Komplexität, Opportunity).

### 3.1 Chart-TF-Expansion (5m + 4H zusätzlich zu 15m + 1H) ✅ GO

**Rationale.** Phase-E2 des Parent-Plans beschreibt das bereits. Hier eine konsolidierte Begründung mit Daten:

- **Event-Density:** Auf 5m ergeben sich im selben Kalender-Fenster ca. 3× mehr Events als auf 15m. Für die aktuell schwache FVG-Familie (96 Events / 59.4% HR) bedeutet das bei 6-monatigem 5m-Lauf potentiell +200 FVG-Events → Bucket-Size ≥300, was Phase-D2/D4 (per-Context-Quality-Filter) statistisch erst *valide* macht.
- **FVG-Time-to-Fill-Hypothese:** Phase D3 vermutet, dass die 59.4% HR teilweise Lookahead-Window-Artefakt ist. 5m liefert finer-grained Fill-Messung — der TTF-Test lässt sich darauf viel sauberer durchführen.
- **Swing-Kontext auf 4H:** BOS-Familie (heute 91.3% HR auf 15m/1H) sollte auf 4H noch stabiler sein (längere Swings, weniger Noise). Falls bestätigt → 4H als Preset-Default für Swing-orientierte Nutzer (Financial-Services-Preset Kandidat).
- **Marketing-Anchor:** Claim *„kalibriert auf 5m/15m/1H/4H × 20 Symbolen × 1000+ Events"* ist ein konkreterer Trust-Anker als „kalibriert auf 15m/1H". Jede TF-Verdopplung im Benchmark ist ein *sichtbarer* Proof-Point.

**Statistische Belastbarkeit.** Bei 4 Chart-TFs und erwarteten 1200 Events (Phase-E-Ziel) → ~300 Events/TF. Mit 3 Kontext-Buckets (session × vol × htf_bias, ca. 6 effektive Buckets) ergibt das ~50 Events/Bucket/TF. Über dem Minimum für [Błasiok & Nakkiran 2023 smECE](https://arxiv.org/abs/2309.12236) Bucket-Ansprüche (RBF-Smoothing toleriert ~30+).

**Kosten.** Nur CI-Config-Änderungen + Benchmark-Runtime ×2. Kein neuer Code. Kein zusätzlicher `request.security()`-Pfad im Pine-Script.

**Evidenz-Markierung:** 🧪 zu messen (Q3 Phase E2), ✅ Config-Änderung trivial.

**Entscheidung:** **GO** — ohne weitere Prüfung umsetzen.

---

### 3.2 HTF-Trend-Stack-Erweiterung (4. Ebene: 30m oder 2H) ⚠ CONDITIONAL HOLD

**Hypothese.** Zwischen 15m-Chart und 4H-Trend-TF-1 liegt ein Faktor-16-Sprung. Bei schnell-wechselnden Regimes (z.B. FOMC-Tage) könnte eine 1H- oder 2H-Zwischenebene die Bias-Übergangs-Latenz reduzieren und FVG/OB-Gate-False-Positives in Übergangszonen senken.

**Evaluation mit Literatur.**

- **[ICT Kill-Zone Standard (Phidias Propfirm 2025)](https://phidiaspropfirm.com/education/kill-zones):** *„Daily charts help identify overall bias, 4-hour and 1-hour timeframes work best for signal clarity, 15-minute charts offer precise entry timing during active kill zones."* ICT selbst arbeitet mit **3 Trend-Ebenen** (Daily / 4H / 1H) plus Chart-TF plus LTF. Unsere 4H/1D/1W-Struktur ist bereits eine *Swing-Variante* davon; wenn wir die 1H-Ebene addieren, müssten wir 1H zur 4. Trend-TF machen.
- **[Freqtrade MTF-Guide (Lin 2025)](https://dev.to/henry_lin_3ac6363747f45b4/lesson-27-freqtrade-multi-timeframe-strategies-n03):** *„Avoid too close timeframes (5m+3m+1m = too close). Don't use too many timeframes (1d+4h+1h+15m+5m = too complex). 3 TFs are enough."* Der Autor zeigt Backtest-Zahlen: 3 TFs geben +31% Return, +50% Sharpe ggü. Single-TF; 5 TFs geben marginale Zugewinne bei deutlich höherer Komplexität.
- **Empirische Auswahl-Regel:** Faktor-3 bis Faktor-5 Abstand zwischen benachbarten TFs. Unser Stack hat Faktor 1m→15m (×15), 15m→4H (×16), 4H→1D (×6), 1D→1W (×5). Der 15m→4H-Gap ist der größte relative Sprung im Intraday-Bereich. Eine Zwischenebene *würde* den Abstand gleichmäßiger machen — aber nur wenn sie *Zusatzinformation* liefert.

**Statistische Belastbarkeit.** Bei 4 Trend-Ebenen und 3 Kontext-Dimensionen wird der Bucket-Split noch feiner. Risiko: Per-Bucket-Calibration unter Minimum → Overfit. Phase-F-Contextual-Calibration verbietet diese Erweiterung vor Sample-Expansion E.

**Kosten.** Neuer `request.security()`-Call → +1 im Pine-Quota-Budget. Laut [TradingView Pine-Limitations](https://www.tradingview.com/pine-script-docs/writing/limitations/) ist jede *unterschiedliche* TF ein separater Request-Slot. Wir nutzen derzeit geschätzt 4–6 Slots (LTF + 3 HTF + IPDA-Rechnung via Chart-Historie). Eine 4. Trend-TF bringt uns näher an 40er-Limit, das in Debug- und Performance-Pro-Modus (Zeile 2563 `performance_mode`) kritisch wird. Dashboard-Zeilen müssen ebenfalls erweitert werden (Zeile 22 Zone-Priority-Integration der neuen Ebene).

**Entscheidung:** **HOLD** bis Q4-Gate. Bedingter Release nur wenn alle drei erfüllt:

1. A/B-Test (Phase-G-Framework) zeigt **≥3pp HR-Uplift** gegenüber 3-TF-Baseline in mindestens 2 der 3 getesteten Kontext-Buckets (RTH/ETH × NORMAL/HIGH-VOL × LONG/SHORT-BIAS).
2. **Brier-Regression ≤ 0.02** (keine Verschlechterung der Kalibrierung). Hart gemessen via smECE.
3. **Bucket-Size pro Familie × Kontext ≥ 30 Events** nach Promotion (validiert nach Sample-Expansion E4).

Falls alle drei erfüllt: Kandidat **2H** (Faktor 2 von 1H, Faktor 2 zu 4H — passt in Factor-3-bis-5-Heuristik). **Nicht** 30m (zu nah an 15m-Chart-TF; bringt Noise).

**Evidenz-Markierung:** ⚠ hypothetisch, messbar erst ab Q3-Phase-E-Abschluss.

---

### 3.3 LTF-Sub-Minute-Expansion (1m → 5s/15s) 🔵 DEFER

**Rationale.** Microstructure-Analyse auf Sub-Minute-Ebene wäre ein Differenzierungs-Feature. [Petukhina et al. 2020 (Eur. J. Finance)](https://www.tandfonline.com/doi/pdf/10.1080/1351847X.2020.1789684?needAccess=true) zeigt, dass intraday-Patterns erst auf Sub-Minute-Ebene echte Mikrostruktur-Signaturen zeigen. [Luca et al. 2024 (Expert Systems)](https://onlinelibrary.wiley.com/doi/pdfdirect/10.1111/exsy.13537) nutzt Tick-Data-Reduktion für Intraday-Prediction.

**Gegenargumente.**

- **TradingView-Plan-Abhängigkeit:** Sub-Minute-Daten sind nur für Premium-Plans verfügbar. Das bricht unser Democratize-Trust-Versprechen. Free-Tier-Nutzer könnten das Produkt nicht gleich nutzen.
- **Pine-Quota:** `request.security_lower_tf()` ist ein separater Request-Typ; 5s bringt 12× mehr intrabars, verbraucht das 200k-Intrabar-Budget ([Pine-Limitations](https://www.tradingview.com/pine-script-docs/writing/limitations/)) nach ~28 Chart-Tagen.
- **Kalibrierung Zero:** Wir haben aktuell Null Sub-Minute-Events im Benchmark. Eine Feature-Integration ohne Messbarkeit wäre ein *claim not measured* — genau das, gegen das wir uns positionieren.

**Entscheidung:** **DEFER auf 2027 Q1** oder später. Nicht Teil des Q3/Q4-Roadmaps. Revisit wenn Databento-/Polygon-Tick-Integration für die benchmark side verfügbar ist (siehe `scripts/generate_smc_micro_base_from_databento.py` — Infrastruktur existiert bereits, aber Benchmark-Runner nutzt sie nicht für LTF < 1m).

**Evidenz-Markierung:** ⚠ rein theoretisch.

---

## 4. Warum KEINE Flux-style 7-TF-Architektur

[Flux Market Structure Dashboard](https://www.tradingview.com/script/vXui7vrm-Market-Structure-Dashboard-Flux-Charts/) wirbt mit:

> *„Each component is calculated independently across up to 7 configurable timeframes and displayed together in a single organized view. Trend weight controls how much each timeframe contributes to the overall bias calculation (0-10)."*

Attraktiv aus Marketing-Sicht. Aus Substanz-Sicht bricht das unsere Positionierung in **drei Punkten**:

### 4.1 Verantwortungsverschiebung auf den Nutzer

Bei 7 frei konfigurierbaren TFs plus 7 Gewichts-Sliders (0–10) ist der **Konfigurationsraum** > 1 Mio. Kombinationen. Kein Nutzer kann das kalibrieren. Flux löst das Problem, indem sie die Kalibrierungsverantwortung *implizit* auf den Nutzer abschieben — *„Timeframes wählen, Gewichte wählen, schauen was rauskommt"*. Das ist „claim not measured" mit extra Schritten. Unser Gegen-Versprechen *„kalibriert auf X Events"* funktioniert nur, wenn der Kalibrierungs-Space klein und stabil ist.

### 4.2 Statistische Unverträglichkeit mit per-Bucket-Kalibrierung

Phase-F (Contextual Calibration Promotion) splittet Gewichte bereits per session × vol_regime × htf_bias = 6–12 Buckets. Bei 7 zusätzlichen TF-Slots mit user-definierten Gewichten wird per-Bucket-Kalibrierung effektiv unmöglich — wir kalibrieren einen *anderen* Scorer für jeden Nutzer. Das bricht die Reproducibility-Garantie und macht den Preprint (Q4) unschreibbar.

### 4.3 Pine-Resource-Budget

Flux' 7-TF-Architektur sendet bei Vollausnutzung 7× Security-Calls × (OB + FVG + BOS + SWEEP + EMA + ADX + Session) = ~49 distinct request.security-Patterns. Das funktioniert in deren Repo nur, weil sie Early-Exit-Guards haben (disabled TFs werden gar nicht angefragt). Wir könnten das technisch nachbauen, aber:

- Aktueller `performance_mode` Input (Zeile 2563) hat 4 Stufen (Light / Balanced / Pro / Debug). In Light müssten wir die Hälfte der TFs deaktivieren — dann ist das 7-TF-Versprechen im günstigsten Nutzungsszenario nicht eingehalten.
- Dashboard-Zeilen-Budget: Wir nutzen 33 Zeilen (Deep Review v7 §3). 7 TFs × Mindestens 3 Info-Zeilen = 21 Zeilen nur für TF-Kontext. Bricht den compact-mode.

**Category-Strategy-Fazit.** Laut [Marketing Competitive-Analysis Skill](./skills/marketing/competitive-analysis/SKILL.md) gibt es vier Optionen: *Create new category · Reframe existing · Win existing · Niche within*. Wir haben uns für **Reframe** entschieden („Measured not claimed"). Flux-nachahmen wäre *„Win existing"* mit deren Regeln — Feature-Count als Wettbewerbs-Dimension. Verliert der neuere/kleinere Player garantiert. Wir spielen ein anderes Spiel.

---

## 5. Entscheidungs-Matrix (konsolidiert)

| Erweiterung | Erwarteter Uplift | Statistische Belastbarkeit | Kosten | Entscheidung | Evidenz |
|---|:-:|:-:|:-:|:-:|:-:|
| Chart-TF 5m + 4H (Phase E2) | **Hoch** — löst FVG-Sample-Problem | ✅ 1200 Events ÷ 4 TFs = 300/TF | Null neuer Code | **GO Q3** | 🧪 messbar |
| 4. HTF-Trend-Ebene 2H | **Mittel** — Gap-Closure 15m↔4H | ⚠ nur mit ≥1000 Events OK | Pine-Slot + Dashboard-Redesign | **HOLD → Q4-Gate** | ⚠ zu validieren |
| LTF < 1m (5s/15s) | Theoretisch hoch | ⚠ aktuell 0 Events | Plan-Abhängigkeit + Quota | **DEFER 2027** | ⚠ theoretisch |
| Flux-style 7-TF-Bias-Stack | Negativ bei ehrlicher Metrik | ❌ bricht per-Bucket-Cal | Story-Widerspruch | **REJECT** | n/a |
| 30m als 4. Trend-Ebene | Gering — zu nah an 15m | ⚠ Noise statt Signal | wie 2H-Variante | **REJECT** (vs. 2H) | ⚠ |

---

## 6. Rollout-Plan

### Phase 0 — Sofort (W0–W1) ✅ DONE (2026-04-22)

- [x] Parent-Plan um Querverweis auf dieses Addendum ergänzen (Abschnitt „2.8 MTF Scope").
      Geliefert in `docs/smc_deep_review_2026-04-20_improvement_plan.md` Z. 269–270
      („MTF-Scope-Entscheidung (2.8, 2026-04-21 Accepted)“).
- [x] README-Section *„Academic Grounding“* (Priority-1-Item 1.3) um 1 Satz erweitern: *„The HTF trend stack follows the ICT-standard 3-layer hierarchy (4H / 1D / 1W) with an adaptive IPDA range, consistent with [Hammer & Patel 2025](https://34.172.72.90/index.php/jse/article/view/77) session-filter findings.“*
      Geliefert in `README.md` Z. 111–113.
- [x] Pine-Dashboard-Legende Zeile 22: Tooltip ergänzen um *„Trend Stack: 4H · 1D · 1W (ICT-standard 3-layer, factor-~4 spacing)“* — damit Nutzer sehen, dass die Struktur *intentional* und nicht unterdimensioniert ist.
      Geliefert in `SMC_Dashboard.pine` Z. 1742–1746 (Variable `_htf_trend_tt`,
      via `dashboard_row_tt(...)` an die HTF-Trend-Zeile gebunden).

### Phase 1 — Q3 (W3–W8) ✅ DONE (2026-04-22)

- [x] Phase E2 (Chart-TF-Expansion) liefert 5m- und 4H-Benchmark-Runs.
      Geliefert via `smc-measurement-benchmark-rolling.yml`
      (`TIMEFRAMES="5m,15m,1H,4H"`); Out-of-Sample-Corpus
      `artifacts/ci/measurement_benchmark_2026-04-22_partial50_v3` enthält
      80 `scoring_<sym>_<tf>.json`-Artefakte (20 Symbole × 4 TFs). Doc-Close
      Q3 §E2 → Commit `e37bcaa9`.
- [x] `smc_core/calibration.py` loggt Events zusätzlich per `chart_tf`-Achse (aktuell nur symbol + chart_tf integriert in `scoring_{symbol}_{timeframe}.json` — siehe `smc_core/scoring.py` Zeile 1083; bestätigen dass 5m/4H korrekt persistiert werden).
      → Bestätigt: `export_scoring_artifact()` in `smc_core/scoring.py` (jetzt
      L1130–1170) schreibt pro `(symbol, timeframe)` ein eigenes JSON; im
      v3-Korpus liegen je 20 Dateien für 5m/15m/1H/4H. Hinweis: das im
      Addendum referenzierte `smc_core/calibration.py` existiert nicht
      separat — Family-Metriken werden direkt in der Scoring-Pipeline
      pro TF persistiert (`family_metrics.{OB,FVG,BOS,SWEEP}`).
- [x] Out-of-Sample-Auswertung Ende W8: Per-Family-HR für 5m (→ FVG-TTF-Hypothese D3 validieren) und 4H (→ BOS-Stabilität validieren).
      → v3-Korpus 2026-04-22 (n=10 064 Events):
        • **FVG TTF-Hypothese D3 falsifiziert** — 5m FVG HR=**0.549**
          (n=3693), 1H FVG HR=**0.644** (n=790, bester TF). Schnellere
          TFs erzeugen mehr False-Invalidations statt schnellerer Hits.
        • **BOS-Stabilität auf 4H/1H bestätigt** — 4H BOS HR=**0.908**
          (n=119), 1H BOS HR=**0.906** (n=203); 5m BOS fällt auf
          0.844 (n=1032), 15m auf 0.846 (n=260). 4H/1H bilden ein
          klares Stabilitäts-Plateau.
      Doc-Close Q3 §E2 + Memory `phase-e2-5m-fvg-falsified.md`.

### Phase 2 — Q4-Gate (W13)

- [ ] A/B-Experiment-Design-Doc: *„Rechtfertigt das ≥1000-Event-Sample eine 4. Trend-Ebene (2H)?"*
- [ ] A/B-Runner: 3-TF-Arm (Baseline) vs. 4-TF-Arm mit 2H-Ergänzung.
- [ ] Stop-Regel SPRT oder fixed-N über 30 Tage.
- [ ] Entscheidung Ende W13: Go/No-Go für 4-TF-Promotion.

### Phase 3 — Q4 (W14–W20) — nur falls Gate grün

- [ ] `SMC_Core_Engine.pine`: Neuer Input `DEFAULT_TREND_TF_0 = '120'` (= 2H) als optionale 4. Ebene, hinter `input.bool` feature-flag.
- [ ] Dashboard-Zeile 22 erweitert auf 4 Trend-Ebenen-Icons.
- [ ] Preprint-Appendix: „4-Layer HTF-Stack-Validation" als Subsection.

### Phase 4 — 2027 Q1+ (vorab-Backlog, nicht Teil Q3/Q4)

- [ ] Sub-Minute-LTF-Evaluation sobald Databento-Tick-Integration auch den Benchmark-Lauf unterstützt.
- [ ] Evtl. 7. Trend-Ebene für Multi-Asset-FX (Session-basiert: Tokyo / London / NY als TF-Äquivalente — ICT-Killzone-Architektur nach [Phidias Propfirm 2025](https://phidiaspropfirm.com/education/kill-zones)).

---

## 7. Offene Risiken / was könnte uns diese Entscheidung kosten?

| Risiko | P | Impact | Mitigation | Trigger |
|---|:-:|:-:|---|---|
| Nutzer fragt wiederholt *„warum nur 3 TFs? Konkurrenz hat 7"* | H | L | Tooltip auf Zeile 22 + FAQ-Eintrag *„Warum nicht mehr TFs? Weil wir jede Ebene kalibrieren, nicht nur anzeigen."* | ab W4 laufend |
| Flux-ähnliche Usecase kommt aus FX-Swingtrader-Community | M | M | Multi-Asset-Probe Q4 (§3.3 Parent-Plan) adressiert genau diese Zielgruppe | Q4 W18 |
| 2H-Ebene nach Gate doch nicht umgesetzt, Backlog stagniert | M | L | Q4-Gate-Doku erhält explizites *„reject reason"* in `docs/DECISIONS.md` | Q4 W13 |
| 5m/4H-Benchmark-Run zu teuer in CI-Minuten | L | L | Benchmark nimmt aktuell ~12 min auf GitHub Actions; ×2 TFs ist ~24 min, noch unter Cron-Budget | laufend Monitoring |
| Konkurrent publiziert 10-TF-Dashboard als direkte Antwort | L | M | Gegenpositionierung verstärken: *„Zehn Claims oder zwei Proofs?"* als Landing-Page-Headline | reaktiv |
| Nutzer definiert eigene Custom-TF-Sets und bricht Kalibrierung | M | M | Dashboard-Warning bei `mtf_trend_tf{1,2,3} != default`: *„Custom TF-Stack → per-family weights unkalibriert"* — ähnlich wie bereits in Phase 1.4 Preset-Handling | W5+ |

---

## 8. Referenzen

**Literatur:**
- [Lin 2025, Freqtrade MTF Strategies](https://dev.to/henry_lin_3ac6363747f45b4/lesson-27-freqtrade-multi-timeframe-strategies-n03) — 3-TF-Empfehlung mit Backtest-Daten, Faktor-Abstand-Heuristik.
- [Hammer & Patel 2025, JSE](https://34.172.72.90/index.php/jse/article/view/77) — ICT Session-Filter + 3-TF-Bias → reduzierte Drawdowns.
- [Rossellini et al. 2025, arXiv:2502.19851](https://arxiv.org/abs/2502.19851) — testable vs. actionable calibration, Bucket-Size-Anforderungen.
- [Błasiok & Nakkiran 2023, arXiv:2309.12236](https://arxiv.org/abs/2309.12236) — smECE RBF-Smoothing-Toleranz.
- [Luca et al. 2024, Expert Systems](https://onlinelibrary.wiley.com/doi/pdfdirect/10.1111/exsy.13537) — Tick-Data-Reduktion für Intraday.
- [Petukhina et al. 2020, Eur. J. Finance](https://www.tandfonline.com/doi/pdf/10.1080/1351847X.2020.1789684?needAccess=true) — Sub-Minute-Mikrostruktur-Patterns.

**Wettbewerber / Industry:**
- [Flux Market Structure Dashboard (TradingView)](https://www.tradingview.com/script/vXui7vrm-Market-Structure-Dashboard-Flux-Charts/) — 7-TF-Referenz, aus der wir uns bewusst unterscheiden.
- [Flux MTF Supply & Demand Zones](https://www.fluxcharts.com/articles/mtf-supply-demand-zones-multi-timeframe-analysis) — 3-TF-Limit im eigenen SD-Indikator (inkonsistent zu 7-TF-MSD).
- [Phidias Propfirm 2025, ICT Kill Zone Guide](https://phidiaspropfirm.com/education/kill-zones) — ICT-Standard-3-Layer-Empfehlung mit exakter TF-Zuordnung.
- [innercircletrader.net 2024, Kill Zones](https://innercircletrader.net/tutorials/master-ict-kill-zones/) — Session-basierte TF-Hierarchie.
- [Zaye Capital Markets 2026, Kill Zone Strategy](https://zayecapitalmarkets.com/kill-zone-in-ict-trading/) — Weekly + Daily + 4H pre-session-Prep als Industry-Standard.

**Pine / TradingView Limits:**
- [TradingView Pine-Docs — Writing / Limitations](https://www.tradingview.com/pine-script-docs/writing/limitations/) — `request.security()` Call-Limits, distinct-Pattern-Zählung, 200k-Intrabar-Budget.
- [TradingView Pine-Docs — Other timeframes and data](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/) — `request.security()` vs. `request.security_lower_tf()` Trade-offs.

**Intern:**
- [smc_improvement_plan_q3_q4_2026-04-20.md](./smc_improvement_plan_q3_q4_2026-04-20.md) — Parent-Plan, Phase E2 (Chart-TF-Expansion), Phase F (Contextual Calibration), §3.3 (Multi-Asset-Probe).
- `SMC_Core_Engine.pine` Zeilen 2326–2329, 2574–2577, 2363–2366 — HTF-Stack-Defaults & non-repainting request.security.
- `smc_core/htf_context.py` — IPDA-adaptiver 4.-Ebenen-Mechanismus.
- `smc_core/scoring.py` Zeile 1083 — Per-Symbol-Per-Timeframe-Persistenz.
- [marketing/competitive-analysis Skill](./skills/marketing/competitive-analysis/SKILL.md) — Category-Strategy-Framework.

---

## 9. Nächste Aktionen (nur diese, kein Scope-Creep)

1. **Heute (21.04):** Dieses Addendum im Repo committen unter `docs/smc_improvement_plan_addendum_2_8_mtf_scope_2026-04-21.md`.
2. **W0:** Querverweis in Parent-Plan-Abschnitt 2 ergänzen.
3. **W0:** Tooltip in `SMC_Dashboard.pine` Zeile 22 erweitern (1 Zeile Code).
4. **W3:** Phase E2 Start, 5m + 4H Benchmark-Runs aktivieren.
5. **W13 (Q3-Gate):** A/B-Design-Doc für 2H-Ebene erstellen *falls* Gate-Bedingungen zu Beginn von Q4 entscheidbar sind.

---

*Erstellt von Perplexity Computer am 21. April 2026, 15:38 CEST. Dieses Dokument ist Teil der Q3-Scope-Entscheidungs-Historie und sollte bei jeder späteren MTF-Scope-Frage als primärer Referenzpunkt dienen. Update-Policy: Nur ergänzen, nie rückwirkend ändern; neue Erkenntnisse als Suffix `_v2`.*
