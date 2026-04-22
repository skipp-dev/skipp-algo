# FVG Quality D4 — Conditional Hit-Rate Audit

> **Q3 Strategie-Plan Phase D4 — Output-Doc.**
> **Datum:** 2026-04-22
> **Quelle:** `artifacts/ci/measurement_benchmark_2026-04-22_partial50_v3/`
> (5710 FVG events, 20 Symbole × 4 TFs)
> **Aggregator:** `scripts/fvg_quality_d4_audit.py --root <root>`
> **Re-run:** `python scripts/fvg_quality_d4_audit.py --root artifacts/ci/measurement_benchmark_2026-04-22_partial50_v3`

## 0. TL;DR

**D4-Hypothese (Plan-Doc):** *„Größe, HTF-Alignment und Distanz zum Preis
sollten die Erwartung beeinflussen."*

**Befund:** Hypothese gilt **nur unter dem lenient (any-touch) Label**.
Unter dem strict ≥50%-Partial-Fill-Label (D1-Empfehlung) sind die
zentralen Quality-Features **null bis invers korreliert**:

| Feature | Δ strict HR (high − low) | Δ lenient HR (high − low) |
|---|---:|---:|
| `htf_aligned` (T vs F) | **−0.034** | +0.001 |
| `is_full_body` (T vs F) | **−0.021** | +0.000 |
| `gap_size_atr` (Q4 vs Q1) | **−0.239** | **+0.554** |
| `distance_to_price_atr` (Q4 vs Q1) | **−0.284** | **+0.327** |

**Konsequenz:** Die in `smc_core/fvg_quality.py` fixierten Gewichte
(`gap_size_atr 0.30`, `htf_aligned 0.25`, `is_full_body 0.10`,
`hurst_50 0.20`, `distance_to_price_atr 0.15`) sind **ausschließlich
gegen das lenient Outcome kalibriert**. Sobald die D3-Promotion
(strict label als primäres FVG-Outcome) erfolgt, müssen diese Gewichte
neu kalibriert werden — sonst verstärkt der Quality-Score genau die
falschen Events.

## 1. Per-Feature Conditional HR (n=5710)

### 1.1 `htf_aligned`

| htf_aligned | n | strict HR | lenient HR |
|---|---:|---:|---:|
| True | 2862 | 0.7952 | 0.5695 |
| False | 2848 | 0.8294 | 0.5706 |
| Δ T−F | | **−0.034** | +0.001 |

→ **Faktisch kein Lift.** Slight inversion. Aktuelles Gewicht 0.25
ist nicht datengestützt.

### 1.2 `is_full_body`

| is_full_body | n | strict HR | lenient HR |
|---|---:|---:|---:|
| True | 2177 | 0.7993 | 0.5701 |
| False | 3533 | 0.8203 | 0.5701 |
| Δ T−F | | **−0.021** | 0.000 |

→ Identische lenient HR, leicht inverse strict HR. Aktuelles Gewicht
0.10 ist Rauschen.

### 1.3 `gap_size_atr` (Quartile, n=5100)

| Quartil | Range | n | strict HR | lenient HR |
|---|---|---:|---:|---:|
| Q1 (kleinste) | ≤ 0.255 | 1275 | **0.8965** | 0.2675 |
| Q2 | 0.255–0.640 | 1275 | 0.8729 | 0.5114 |
| Q3 | 0.640–1.537 | 1275 | 0.8102 | 0.6635 |
| Q4 (größte) | > 1.537 | 1275 | **0.6573** | 0.8212 |

→ **Klare Inversion.** Lenient HR steigt monoton (große Gaps werden
leichter „angetippt"), strict HR fällt monoton (große Gaps werden
selten zu ≥50% gefüllt). Aktuelles Gewicht 0.30 belohnt unter strict
genau die Loser.

### 1.4 `distance_to_price_atr` (Quartile, n=5100)

| Quartil | Range | n | strict HR | lenient HR |
|---|---|---:|---:|---:|
| Q1 (nächste) | ≤ 0.204 | 1276 | **0.9310** | 0.3691 |
| Q2 | 0.204–0.516 | 1274 | 0.8713 | 0.5730 |
| Q3 | 0.516–1.115 | 1275 | 0.7875 | 0.6251 |
| Q4 (fernste) | > 1.115 | 1275 | **0.6471** | 0.6965 |

→ Strict HR fällt monoton mit Distanz — Q1 erreicht 0.931. Das ist
das **stärkste vorhandene Signal** im Feature-Set, aber die
Richtung des aktuellen Score-Beitrags müsste validiert werden
(je näher, desto besser; das Gewicht 0.15 sollte deutlich höher
sein und negative Distanz bestrafen, nicht belohnen).

## 2. Combined Conditional HR

### 2.1 `htf_aligned × is_full_body`

| aligned | full_body | n | strict HR | lenient HR |
|---|---|---:|---:|---:|
| True  | True  | 1093 | 0.7868 | 0.5764 |
| True  | False | 1769 | 0.8005 | 0.5653 |
| False | True  | 1084 | 0.8118 | 0.5637 |
| False | False | 1764 | **0.8401** | 0.5748 |

→ Beste Kombination ist *unaligned + not full_body*. Das ist die
Umkehrung der eingebauten Score-Heuristik.

### 2.2 Top-Quality vs. Bottom-Quality Combo

| Bucket | Definition | n | strict HR | lenient HR |
|---|---|---:|---:|---:|
| TOP | aligned & full_body & `gap≥Q3` & `dist≤Q1` | **0** | — | — |
| BOT | unaligned & not full_body & `gap≤Q1` | 396 | **0.9293** | 0.2778 |

→ Die TOP-Definition (alle vier „high-quality"-Constraints
gleichzeitig) selektiert **keine Events** — die Features sind
empirisch antikorreliert. Die BOT-Definition (vermeintlich „low-quality")
liefert die **höchste strict HR im gesamten Audit (0.929)**.

## 3. Empfehlung

1. **Promotion-Gating für D3:** Die strict-Label-Promotion darf nicht
   ohne Re-Kalibrierung der Quality-Gewichte ausgerollt werden. Sonst
   entsteht ein Scoring-Anti-Pattern (hohe Quality-Scores → niedrige
   strict-HR).
2. **Single-Feature-Monotonisierung:** `distance_to_price_atr` ist das
   einzige robust monotone Feature unter strict HR. Vorschlag für die
   Re-Kalibrierung: Gewicht von 0.15 → ≥0.40, Vorzeichen prüfen
   (näher = besser).
3. **`gap_size_atr` umkehren oder droppen:** Unter strict label ist die
   Richtung invers. Entweder Vorzeichen umkehren oder Feature aus dem
   Score entfernen.
4. **`htf_aligned` und `is_full_body` deprecaten:** Beide liefern
   Δ < 0.05 absolut. Vorschlag: Gewichte (0.25 + 0.10 = 0.35) auf
   `distance_to_price_atr` und `hurst_50` umverteilen — letzteres ist
   im D4-Audit nicht analysiert (n=3573, Coverage 62.6%) und braucht
   eine eigene Stratifizierung.
5. **Hurst-Coverage als Voraussetzung:** Bevor `hurst_50` höher
   gewichtet wird, muss seine Coverage von 62.6% auf ≥95% gehoben
   werden, sonst schlagen die `insufficient_features`-Fallbacks zu
   und verwässern jede Re-Kalibrierung.

## 4. Nächste Schritte

1. **D4 in STRATEGY §3.D4 als DONE markieren** mit dem o.g. Verdikt.
2. **D3 Promotion-PR neu skopen:** Vor jeder Outcome-Umstellung muss
   ein Re-Calibration-Run gegen den strict-Label-Snapshot pinnen,
   sonst regressiert die FVG-Quality-Komponente.
3. **`hurst_50` D4.5 audit** als Folge-Auftrag (eigener Snapshot mit
   ≥95% Coverage erforderlich).

---

*Erstellt mit `scripts/fvg_quality_d4_audit.py`. Re-runnable gegen
jeden Benchmark-Snapshot, der `events_*.jsonl` mit `label_partial_50`
und A1.B-FVG-Quality-Features enthält (ab Bridge-Commit `3746b36e`).*
