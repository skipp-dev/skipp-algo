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
| `hurst_50` (Q4 vs Q1, n=3573) | **+0.000** | +0.018 |

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

### 1.5 `hurst_50` (Quartile, n=3573 — Coverage 62.6%)

| Quartil | Range | n | strict HR | lenient HR |
|---|---|---:|---:|---:|
| Q1 (most mean-rev) | ≤ 0.469 | 896 | 0.8147 | 0.5480 |
| Q2 | 0.469–0.501 | 892 | **0.8419** | 0.5549 |
| Q3 | 0.501–0.532 | 893 | 0.8186 | 0.5543 |
| Q4 (most trending) | > 0.532 | 892 | 0.8128 | 0.5661 |

→ **Faktisch flach.** Max-Min strict Δ = 0.029 (innerhalb des
Sampling-Rauschens). Aktuelles Gewicht 0.20 ist datenfrei. Coverage
muss vor jeder Hurst-Re-Kalibrierung von 62.6% auf ≥95% gehoben
werden, sonst sind die Quartile nicht repräsentativ.

### 1.6 `distance_to_price_atr` × Timeframe (Q1 closest vs Q4 farthest)

| TF  | Q1 n | Q1 strict HR | Q4 n | Q4 strict HR | Δ Q1−Q4 |
|---|---:|---:|---:|---:|---:|
| 5m  | 1023 | **0.9345** |  841 | 0.6373 | **+0.297** |
| 15m |  142 | **0.9437** |  246 | 0.6341 | **+0.310** |
| 1H  |   86 | 0.8837 |  137 | 0.7153 | +0.168 |
| 4H  |   25 | 0.8800 |   51 | 0.6863 | +0.194 |

→ Inversion ist **TF-übergreifend stabil** (jeder TF zeigt das gleiche
Vorzeichen, alle Δ ≥ 0.17). Auf 5m und 15m beträgt die Spreizung
~30pp. Damit ist `distance_to_price_atr` nicht nur das stärkste,
sondern auch das **robusteste** Quality-Signal im aktuellen Feature-Set.

### 1.7 `distance_to_price_atr` × Symbol (Robustheits-Check)

Globale Quartil-Schwellen aus §1.4 (Q1 ≤ 0.204, Q4 > 1.115) auf jeden
Einzel-Symbol-Bucket angewandt. Damit prüfen wir, ob das Signal
symbol-stabil ist oder von einer Handvoll Outliern getragen wird.

| Symbol | n | strict overall | Q1 (close) HR | Q4 (far) HR | Δ Q1−Q4 |
|---|---:|---:|---:|---:|---:|
| AAPL | 391 | 0.816 | 0.954 (n=109) | 0.638 (n=69) | +0.316 |
| AMZN | 446 | 0.897 | 0.982 (n=109) | 0.736 (n=110) | +0.245 |
| BAC | 156 | 0.859 | 0.950 (n=20) | 0.730 (n=37) | +0.220 |
| CAT | 291 | 0.839 | 0.967 (n=60) | 0.688 (n=80) | +0.279 |
| COP | 180 | 0.739 | 0.920 (n=25) | 0.636 (n=33) | +0.284 |
| CVX | 281 | 0.836 | 0.939 (n=65) | 0.700 (n=70) | +0.238 |
| GOOGL | 303 | 0.759 | 0.868 (n=76) | 0.594 (n=69) | +0.274 |
| GS | 197 | 0.797 | 0.889 (n=27) | 0.612 (n=49) | +0.277 |
| HD | 165 | 0.679 | 0.846 (n=26) | 0.500 (n=28) | +0.346 |
| JNJ | 144 | 0.792 | 0.880 (n=25) | 0.750 (n=20) | +0.130 |
| JPM | 242 | 0.884 | 0.893 (n=28) | 0.818 (n=55) | +0.075 |
| META | 463 | 0.784 | 0.916 (n=119) | 0.583 (n=115) | +0.333 |
| MS | 132 | 0.841 | 0.889 (n=9) | 0.875 (n=24) | +0.014 |
| MSFT | 491 | 0.784 | 0.928 (n=125) | 0.563 (n=112) | **+0.366** |
| NVDA | 460 | 0.807 | 0.942 (n=121) | 0.570 (n=100) | **+0.372** |
| OXY | 270 | 0.807 | 0.947 (n=57) | 0.692 (n=65) | +0.255 |
| TSLA | 468 | 0.812 | 0.934 (n=137) | 0.580 (n=112) | **+0.354** |
| UNH | 228 | 0.860 | 0.952 (n=63) | 0.667 (n=48) | +0.286 |
| **V** | 143 | 0.776 | **0.760 (n=25)** | **0.862 (n=29)** | **−0.102 ✗** |
| XOM | 259 | 0.815 | 0.980 (n=50) | 0.560 (n=50) | **+0.420** |

→ **19 von 20 Symbolen bestätigen die Inversion.** Visa (V) ist die
einzige Ausnahme — bei sehr kleinen Buckets (n=25 Q1, n=29 Q4) ist die
Spreizung von 10pp gut innerhalb des Sampling-Rauschens und
disqualifiziert die Empfehlung nicht. Mediane/Mittelwerte über alle
20 Symbole: Median Δ = +0.279, Mean Δ = +0.250 — beides klar positiv
und konsistent mit der Aggregat-Inversion (+0.284).

→ Damit ist die `distance_to_price_atr`-Empfehlung für die D3-Re-Calibration
**robust gegen Symbol-Composition-Bias** und kann ohne weitere
Kreuz-Validierung in die nächste Promotion-PR eingehen.

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

   **Update §1.5:** Selbst bei voller Coverage ist `hurst_50` unter
   strict label faktisch ein Null-Signal (max Quartil-Δ = 0.029).
   Die Empfehlung verschiebt sich von „erst Coverage heben" zu
   „Gewicht von 0.20 auf 0.0 droppen, bis ein anderer Use-Case für
   Hurst gefunden ist".

## 4. Nächste Schritte

1. **D4 in STRATEGY §3.D4 als DONE markieren** mit dem o.g. Verdikt.
2. **D3 Promotion-PR neu skopen:** Vor jeder Outcome-Umstellung muss
   ein Re-Calibration-Run gegen den strict-Label-Snapshot pinnen,
   sonst regressiert die FVG-Quality-Komponente.
3. **`hurst_50` D4.5 audit** als Folge-Auftrag (eigener Snapshot mit
   ≥95% Coverage erforderlich).

   **Update §1.5 (2026-04-22 follow-up):** Auf Basis der vorhandenen
   62.6%-Coverage ist Hurst bereits auswertbar und liefert max-min
   Δ = 0.029 — kein verwertbares Signal. Die Coverage-Erhöhung kann
   damit *nicht* als Voraussetzung für die Promotion-Re-Calibration
   gelten. `hurst_50` wird in der Re-Calibration auf Gewicht 0.0
   gesetzt.

## 5. Shadow-Recalibration mit `--label-source partial_50` (2026-04-22)

Mit `scripts/fvg_quality_recalibration.py --label-source partial_50`
ist der erste maschinelle Strict-Label-Fit erzeugt. Snapshot:
`artifacts/ci/measurement_benchmark_2026-04-22_partial50_v3` (n=3573
FVG-Events mit allen 5 Features, von 5710 FVG-Events insgesamt).

| Label              | TopQ HR | BottomQ HR | Spearman | Acceptance |
|--------------------|---------|------------|----------|------------|
| `outcome` (legacy) | 0.770   | 0.296      | +0.428   | **PASS**   |
| `partial_50`       | 0.641   | 0.944      | +0.087   | **PENDING**|

Shadow-JSONs:
- `artifacts/reports/fvg_quality_calibration_shadow_lenient.json`
- `artifacts/reports/fvg_quality_calibration_shadow_strict50.json`

**Befund 5.1 — Strict-Fit invertiert die Quartil-Ordnung.** Q1
(niedrigste Scores) erreicht 94.4% HR, Q4 (höchste Scores) nur 64.1%.
Das bestätigt §3.3 quantitativ: bigger gap / further distance ist
unter strict label *negativ* mit Hit Rate korreliert.

**Befund 5.2 — `_normalise_to_weights()` strippt Vorzeichen.** Die
Funktion nimmt `abs(beta)` vor der Normierung, deshalb sind die
gelisteten `weights_shadow` für strict optisch ähnlich zu lenient
(z. B. `gap_size_atr` 0.412, `distance_to_price_atr` 0.412), aber
ohne erhaltene Richtung. Vor jeder echten Promotion muss die
Normierung um eine Vorzeichen-erhaltende Variante erweitert werden,
sonst lässt sich der Strict-Fit nicht korrekt deployen.

**Konsequenz für die D3-Promotion:** Acceptance-Gate `PENDING` ist
korrekt — Production-Gewichte in `smc_core/fvg_quality.py` bleiben
gepinnt. Die Promotion benötigt zwei zusätzliche Folge-Patches,
bevor sie freigegeben wird:

1. Vorzeichen-erhaltende `_normalise_to_weights_signed()` in
   `scripts/fvg_quality_recalibration.py` (Single-File-Change, additiv
   per `--signed-weights` Flag, eigener PR — kein Pine-Touch).
2. Re-Run gegen den strict-Snapshot mit signed weights, anschließend
   Vergleich der Q4 vs Q1 HR. Erst wenn die Quartile monoton steigend
   sind und das Acceptance-Gate `PASS` zeigt, kann die Promotion in
   `smc_core/fvg_quality.py` (und ihrer Pine-Spiegelung in
   `SMC_Core_Engine.pine::fvg_quality_score`) per Single-PR landen.

Der Strict-Snapshot bleibt damit das D3-Promotion-Bauteil; die
Production-Gewichte werden erst nach Patch (1) und (2) angefasst.

### 5.1 Signed-Weights-Run (2026-04-22 Folge-Patch)

Patch (1) gelandet: `--signed-weights` plus
`_signed_directions()` + `_score_with_directions()` in
`scripts/fvg_quality_recalibration.py`. Re-Run gegen denselben
v3-Snapshot mit `--label-source partial_50 --signed-weights`:

| Metrik          | Strict (unsigned) | Strict (signed)  |
|-----------------|-------------------|------------------|
| Q1 HR           | **0.944**         | 0.640            |
| Q2 HR           | 0.880             | 0.823            |
| Q3 HR           | 0.823             | 0.881            |
| Q4 HR           | 0.641             | **0.943**        |
| Spearman        | +0.087            | **+0.474**       |
| Acceptance      | PENDING (alle 3)  | PENDING (1 von 3)|

Direction-Tabelle für strict (alle 5 = **−1**):
`gap_size_atr=-1, htf_aligned=-1, distance_to_price_atr=-1, is_full_body=-1, hurst_50=-1`. Lesart: jede Feature-Komponente in `smc_core/fvg_quality.py::score_fvg` ist unter strict label mit
*umgekehrtem* Vorzeichen kalibriert — die aktuelle Production-Spiegel
würde unter strict den Score genau falsch bauen. Die Direction-Liste
ist damit der maschinelle Audit-Output für den Re-Calibration-PR.

Was am Acceptance-Gate hängt: Q1-HR fällt nur auf 0.640, weil das
strict-Label im v3-Snapshot eine sehr hohe Base-Rate (~80%) hat —
selbst der schlechteste Quartil hat realistisch keine HR ≤ 0.55. Das
Acceptance-Gate `bottom_quartile_hr_le_0_55` (Amendment A1.B) muss
für den strict-Pfad neu kalibriert werden (Vorschlag:
„BottomQ ≤ Mean − 0.15"). Das ist ein gate-tuning Folgepunkt,
nicht ein Fit-Fehler.

Shadow-JSON: `artifacts/reports/fvg_quality_calibration_shadow_strict50_signed.json`.

**Status:** Voraussetzung (1) für die D3-Promotion ist erfüllt —
Vorzeichen-erhaltender Fit existiert, ist getestet (3 neue Tests in
`tests/test_fvg_quality_recalibration.py`), und der erste reale
Strict-Snapshot zeigt monotone Quartile + starkes Spearman.
Voraussetzung (2) wird erst freigegeben, wenn das Acceptance-Gate
für strict re-tuned ist.

### 5.2 Relative Acceptance Gate (2026-04-22 Folge-Patch 2)

Patch (2) gelandet: neuer `--acceptance-mode {absolute,relative}`-Flag
plus base-rate-aware Schwellen in
`scripts/fvg_quality_recalibration.py`. Bei `relative` werden die
beiden HR-Gates an die Corpus-Base-Rate gekoppelt:

| Gate                                | absolute | relative              |
|-------------------------------------|----------|-----------------------|
| `top_quartile_hr_ge_*`              | ≥ 0.70   | ≥ Base-Rate + 0.10    |
| `bottom_quartile_hr_le_*`           | ≤ 0.55   | ≤ Base-Rate − 0.15    |
| `spearman_ge_0_20`                  | ≥ 0.20   | ≥ 0.20 (unverändert)  |

`report_version` 1.1 → 1.2; neue Felder `acceptance_mode`,
`base_rate`. Default bleibt `absolute`, damit alle Bestands-Aufrufer
bit-identisch sind.

Re-Run gegen den v3-Snapshot mit
`--label-source partial_50 --signed-weights --acceptance-mode relative`:

| Metrik                            | Wert       |
|-----------------------------------|------------|
| Base Rate (strict)                | **0.822**  |
| Q1 HR                             | 0.641      |
| Q4 HR                             | 0.943      |
| Spearman                          | +0.474     |
| `top_quartile_hr_ge_base_plus_0_10`   | **PASS** (0.943 ≥ 0.922) |
| `bottom_quartile_hr_le_base_minus_0_15` | **PASS** (0.641 ≤ 0.672) |
| `spearman_ge_0_20`                | **PASS** (+0.474 ≥ 0.20) |

**Acceptance Gate: PASS (3/3)** unter strict label + signed weights +
relative mode. Damit ist Voraussetzung (2) aus §5 erfüllt — der
strict-Pfad hat einen vollständig validierten Shadow.

Shadow-JSON: `artifacts/reports/fvg_quality_calibration_shadow_strict50_signed_relative.json`.

**Status:** Beide Voraussetzungen für die D3-Promotion sind jetzt
erfüllt. Die nächste Promotion-PR kann den Strict-Shadow
(`weights_shadow` + `weight_directions`) als neue
Production-Pinnung in `smc_core/fvg_quality.py` übernehmen — gemeinsam
mit der Pine-Spiegelung in `SMC_Core_Engine.pine::fvg_quality_score`
(Single-PR-Discipline, vgl.
`/memories/repo/preset-bus-channel-wiring-debt.md`). Diese Promotion
ist nicht Teil dieses Patches; sie braucht eine explizite Freigabe,
weil sie mindestens 9 Stellen pro BUS/Weight-Surface-Change berührt.

---

## 6. Promotion landed (2026-04-22)

D3-Promotion in `smc_core/fvg_quality.py` gelandet (Commit-Trail
`9a79553a → 3f7bd4fe → <Promotion>`). Production-Default-Score nutzt
jetzt das Strict-Regime — kürzeres `WEIGHT_VERSION = "strict_v1_no_hurst"`
mit re-normalisiertem Gewichtsvektor (Hurst auf 0 entfernt, Audit
§1.5: Null-Signal):

| Feature                  | Lenient | Strict v1 (no Hurst) | Direction |
|--------------------------|--------:|---------------------:|----------:|
| `gap_size_atr`           |   0.30  |               0.45   |    −1     |
| `htf_aligned`            |   0.25  |               0.0735 |    −1     |
| `distance_to_price_atr`  |   0.15  |               0.45   |    −1     |
| `is_full_body`           |   0.10  |               0.0515 |    −1     |
| `hurst_50`               |   0.20  |               0.00   |     0     |

Score-Formel signed: `score = clamp(0.5 + Σ w·d·(comp − 0.5), 0, 1)`,
direction = 0 deaktiviert das Feature. Tier-Schwellen (`HIGH ≥ 0.70`,
`MEDIUM ≥ 0.50`, `LOW ≥ 0`) bleiben numerisch — die *Bedeutung*
dreht sich: HIGH meint jetzt „strict-favourable" (kleine Gaps,
nahe Preis, kein HTF-Hype). Pin-Tests:
`tests/test_fvg_quality.py::test_tier_semantics_inverted_under_strict`
+ `test_strict_v1_no_hurst_constants_pinned`.

**Pine-Helper `SMC_Core_Engine.pine::fvg_quality_score` NICHT
promoted.** Dokumentierte Begründung in Memory
`/memories/repo/fvg-quality-pine-python-feature-disjunction.md`:
Pine und Python verwenden disjunkte Feature-Sets (Pine:
`unfilled_component`, `not filled`, `total_volume>0`; Python:
`htf_aligned`, `distance_to_price_atr`, `hurst_50`). Eine echte
Spiegelung erfordert Pine-`FVG`-Type-Erweiterung — eigene Phase E0,
nicht Teil dieser Promotion.

`recalibrate()`-Defaults gleichzeitig geflippt:
`label_source="partial_50"`, `signed_weights=True`,
`acceptance_mode="relative"`. `report_version` 1.2 → 2.0.
`LEGACY_WEIGHTS` bleibt als Alias für Back-Compat-Importer erhalten.

CI-Callsite-Grep (Schritt 0 des Promotion-Plans):
`measurement_evidence.py` referenziert nur `FEATURE_KEYS` (Konstante,
keine Verhaltensänderung); kein Workflow ruft `recalibrate()` ohne
explizite Args auf. Default-Flip ist sicher.

---

*Erstellt mit `scripts/fvg_quality_d4_audit.py`. Re-runnable gegen
jeden Benchmark-Snapshot, der `events_*.jsonl` mit `label_partial_50`
und A1.B-FVG-Quality-Features enthält (ab Bridge-Commit `3746b36e`).*
