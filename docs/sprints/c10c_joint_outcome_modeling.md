# Sprint C10c — Joint-Outcome-Modellierung bei Co-Firing

**Status:** Aktiv (Pure-Analysis-Phase, Schritte 1–3)
**Eltern-Sprint:** C10b — Family-Partition-Validation (abgeschlossen 2026-05-13, PR #2196)
**Backlog-Anker:** `docs/sprints/backlog/joint_outcome_modeling.md`
**Sprache:** Deutsch
**Autor-Identität:** `skipp-dev <preuss.steffen@yahoo.com>`
**Start:** 2026-05-14 (Tag nach C10b-Merge und Cron-Brücke #2197)

---

## Auslöser (Wiederholung aus dem Backlog-Anker)

C10b Step 2f hat zwei widersprüchlich wirkende Signale produziert:

| Signal | Wert | Sprint-Schwelle |
|---|---|---|
| Multi-Firing-Bars (≥ 2 Familien auf gleicher Bar) | **22.61 %** | > 20 % → Pooling-Tendency |
| Max Cramér's V auf paarweisen Outcomes der Co-Firing-Bars | **0.27** | > 0.5 → Pooling, < 0.2 → Beibehalt |

Lesart: „komplementäre Signale, die sich auf derselben Bar überlappen". Die C10b-Architekturentscheidung (Beibehalt für BOS/SWEEP/FVG, OB intraday-only) bleibt unberührt. Diese Sprint klärt die Folgefrage: Was tun, wenn zwei oder drei Familien gleichzeitig feuern und je eine eigene Vorhersage liefern?

Das Promotion-Gate hat heute keinen sauberen Mechanismus, aus drei unabhängigen Wahrscheinlichkeiten (z. B. SWEEP=0.78, FVG=0.53, OB=0.62) eine kombinierte Entscheidung zu treffen.

---

## Vorbedingungen (alle erfüllt am 2026-05-14)

| # | Vorbedingung | Status |
|---|---|---|
| 1 | C10b in PR #2196 gemerged (Endurteil festgeschrieben) | erfüllt (`81c4f4a2`, 2026-05-14 01:46 UTC) |
| 2 | Cron-Brücke #2197 grün | erfüllt (`0eb0960d`, 2026-05-14 01:27 UTC) |
| 3 | ≥ 1 Woche Pause zwischen Backlog-Anker und Sprint-Start | **nicht erfüllt** — bewusst übersprungen auf User-Entscheidung. Risiko: methodische Übermüdung. Mitigation: harte Methoden-Schwellen, keine handgewählten Tests. |

---

## Methodik-Schwellen (vor der Analyse festgenagelt)

Damit nicht im Nachgang an Schwellen geschraubt wird:

| Test | Schwelle | Verdikt bei Reject |
|---|---|---|
| z-Test Co-Firing vs. Single Hitrate (zweiseitig, pro Familie) | Bonferroni p_adj < 0.05 (n=4 Familien) | Co-Firing hebt Trefferquote signifikant |
| G-Test Joint vs. Product (pro Familien-Paar) | p < 0.01 ohne Bonferroni-Korrektur (n_paare = 4–6) | echte Interaktion in der Outcome-Verteilung |
| Min-Sample-Größe je Joint-Distribution-Zelle | ≥ 5 erwartete Frequenzen | sonst Test als "underpowered" markieren statt zu reporten |

---

## Schritte

### Schritt 1: Per-Bar-Aggregation
**Input:** `/tmp/c10b_local_run/measurement_benchmark/*/1D/events_*_1D.jsonl` (20 Symbole × 1D)
**Script:** `scripts/c10c_aggregate_per_bar.py`
**Output:** `docs/research/co_firing/per_bar_predictions.jsonl`

Pro `(symbol, timestamp)` eine Zeile mit allen feuernden Familien, ihren `predicted_prob` und `outcome`-Werten.

### Schritt 2: Cofiring vs. Single Hitrate
**Script:** `scripts/c10c_cofiring_vs_single.py`
**Output:** `docs/research/co_firing/cofiring_vs_single_hitrate.json`

Pro Familie F: Hitrate-Vergleich {F feuert allein} vs. {F feuert in einer Multi-Firing-Bar}. Zweiseitiger z-Test für Anteilsdifferenz, Bonferroni-korrigiert über 4 Familien.

### Schritt 3: Joint vs. Product G-Test
**Script:** `scripts/c10c_joint_vs_product.py`
**Output:** `docs/research/co_firing/joint_vs_product.json`

Pro Familien-Paar {A, B} mit ≥ 10 Co-Firing-Bars: 2×2-Kontingenztafel `(outcome_A × outcome_B)`. Erwartete Frequenzen unter Unabhängigkeit = Produkt der Marginale × n_bars. G-Test (Likelihood-Ratio-Chi²) gegen Reject-Schwelle p < 0.01. Sample-Power-Marker bei E < 5.

### Schritt 4 (bedingt): Stacking-Skizze
Nur ausführen wenn **mindestens ein** G-Test in Schritt 3 p < 0.01 reportet. Sonst überspringen und im Findings-Doc dokumentieren, dass die Faktorisierungs-Annahme nicht zurückgewiesen wurde.

### Schritt 5 (bedingt): Architekturvorschlag
Folgesprint `docs/sprints/c10d_joint_stacking_implementation.md` öffnen, wenn Schritt 4 produktiv war.

---

## Datengrundlage — ehrliche Einschätzung

- 1D-Korpus: 410 events, 71 Co-Firing-Bars über vermutlich 4–6 Familien-Paare.
- Reicht für deskriptive Statistik in Schritten 2 + 3.
- Nicht ausreichend für Stacking-Training in Schritt 4 ohne Korpus-Erweiterung (siehe Backlog-Anker §Datengrundlage).
- Falls Schritt 3 signifikante Interaktionen findet aber n je Zelle < 20 ist: Schritt 4 wird als "Skizze auf dünnem Eis" markiert und Re-Run auf erweitertem Korpus als harte Vorbedingung für C10d definiert.

---

## Beziehung zum Hauptziel

> „Wenn die SMC-Calibration-Track-Record nicht eindeutig profitable Setups zeigt, dann habe ich nichts zu verkaufen."

Asymmetrisch:
- Wenn Joint-Modell **funktioniert**: zusätzliche Vermarktungs-Achse („Bei Mehrfach-Bestätigung steigt die Trefferquote auf X %").
- Wenn Joint-Modell **nicht funktioniert** (alle G-Tests p > 0.01): Familien sind in ihren Outcomes faktorisierbar — auch das ist eine verkaufbare Methodik-Aussage.

Beide Outcomes sind dokumentationswürdig.

---

## Nicht-Ziele

- Keine Änderung am C10b-Endurteil.
- Keine Änderung am Promotion-Gate, bis Joint-Modell empirisch belegt.
- Kein Refactor in `ml/training/` in diesem Sprint.

---

## Verdikt

(Wird am Ende dieses Sprints eingetragen — vorerst leer.)
