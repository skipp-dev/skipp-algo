# C10c — Joint-Outcome-Modellierung: Findings auf dem 1D-Korpus

**Datum:** 2026-05-14
**Korpus:** `/tmp/c10b_local_run/measurement_benchmark/*/1D/events_*_1D.jsonl` (20 Symbole, 1D, n_events = 410)
**Eltern-Sprint:** [c10c_joint_outcome_modeling.md](../../sprints/c10c_joint_outcome_modeling.md)
**Verdikt:** **Faktorisierungs-Annahme nicht zurückweisbar** auf diesem Korpus — keine Joint-Outcome-Implementierung gerechtfertigt (Schritte 4+5 entfallen). Empfehlung: Re-Run auf erweitertem Korpus, bevor C10d eröffnet wird.

---

## TL;DR

Die zwei Vermutungen aus dem Backlog-Anker werden auf dem 1D-Korpus **beide nicht bestätigt**:

| Vermutung | Test | Schwelle | Ergebnis |
|---|---|---|---|
| Konfidenz: Co-Firing-Bars haben höhere Trefferquote als Single-Firing | z-Test per Familie, Bonferroni p_adj < 0.05 (alpha_each=0.0125) | 0/4 Familien signifikant | nicht zurückweisbar |
| Komplementarität: Joint-Outcome ≠ Produkt der Marginale | G-Test pro Paar, p < 0.01 | 0/4 testbare Paare reject | nicht zurückweisbar |

Zusätzlich: alle 4 testbaren Paare sind **underpowered** (mindestens eine Zelle mit erwarteter Frequenz < 5). Zwei weitere Paare unter dem `n < 10`-Cutoff geschmissen.

**Asymmetrischer Upside (laut Sprint-Anker):** Wenn das Joint-Modell nicht funktioniert, ist die Familien-Faktorisierbarkeit selbst eine verkaufbare Methodik-Aussage. Genau das passiert hier — aber mit dem ehrlichen Caveat, dass der Korpus zu dünn ist, um die Aussage robust zu treffen.

---

## Schritt 1 — Per-Bar-Aggregation

Skript: [`scripts/c10c_aggregate_per_bar.py`](../../../scripts/c10c_aggregate_per_bar.py)
Output: [`per_bar_predictions.jsonl`](per_bar_predictions.jsonl) (314 Zeilen)

| Größe | Wert |
|---|---|
| events insgesamt | 410 |
| eindeutige Bars (symbol, timestamp) | 314 |
| n_families = 1 (Single-Firing) | 243 (77.39 %) |
| n_families = 2 (Doppel-Firing) | 65 |
| n_families = 3 (Triple-Firing) | 6 |
| Co-Firing-Bars (≥ 2 Familien) | 71 (22.61 %) |

Das reproduziert die Step-2f-Zahl aus C10b exakt (22.61 %).

### Familien-Verteilung

| Familie | Single-only Bars | Co-Firing Bars (incl. Triple-Beteiligung) |
|---|---|---|
| BOS   | 18  | 18 (in Paaren: BOS-FVG=12, BOS-OB=12, BOS-SWEEP=6) |
| FVG   | 111 | 36 (FVG-SWEEP=24, BOS-FVG=12, FVG-OB=5) |
| OB    | 58  | 38 (OB-SWEEP=24, BOS-OB=12, FVG-OB=5) |
| SWEEP | 56  | 50 (FVG-SWEEP=24, OB-SWEEP=24, BOS-SWEEP=6) |

Drei Triple-Firings im Korpus: `(BOS,FVG,OB)`, `(BOS,FVG,SWEEP)`, `(BOS,OB,SWEEP)` — jeweils 2 / 3 / 1 Bars.

---

## Schritt 2 — Co-Firing vs. Single-Firing Hitrate

Skript: [`scripts/c10c_cofiring_vs_single.py`](../../../scripts/c10c_cofiring_vs_single.py)
Output: [`cofiring_vs_single_hitrate.json`](cofiring_vs_single_hitrate.json)

| Familie | Single-Hit | Co-Hit | Δ (pp) | z | p (two-sided) | reject @ Bonferroni 0.0125 |
|---|---|---|---|---|---|---|
| BOS   | 1.000 (18/18)  | 0.958 (23/24)  | −4.2   | +0.879 | 0.380 | nein |
| FVG   | 0.568 (63/111) | 0.417 (15/36)  | −15.1  | +1.576 | 0.115 | nein |
| OB    | 0.655 (38/58)  | 0.737 (28/38)  | +8.2   | −0.844 | 0.399 | nein |
| SWEEP | 0.768 (43/56)  | 0.780 (39/50)  | +1.2   | −0.149 | 0.881 | nein |

**Verdikt:** „no per-family hit-rate lift from co-firing detected".

Bemerkenswert (deskriptiv, nicht inferenz-tauglich): FVG verliert in Co-Firing 15 pp Hitrate, OB gewinnt 8 pp. Beide nicht signifikant. Wenn überhaupt ein Muster, dann „SWEEP/OB scheinen Co-Firing-stabil, FVG schwächelt in Mehrfachbestätigung" — aber das ist mit n=36 / 38 nicht belastbar.

---

## Schritt 3 — Joint vs. Product G-Test

Skript: [`scripts/c10c_joint_vs_product.py`](../../../scripts/c10c_joint_vs_product.py)
Output: [`joint_vs_product.json`](joint_vs_product.json)

| Paar | n_cofiring | observed table | G | p | underpowered | reject @ α=0.01 |
|---|---|---|---|---|---|---|
| BOS-FVG    | 12 | `[[0,0],[5,7]]`  | 1.14 | 0.285 | ja | nein |
| BOS-OB     | 12 | `[[0,0],[1,11]]` | 0.00 | 1.000 | ja | nein |
| BOS-SWEEP  | 6  | n < 10 → skipped | —    | —     | — | — |
| FVG-OB     | 5  | n < 10 → skipped | —    | —     | — | — |
| FVG-SWEEP  | 24 | `[[3,10],[2,9]]` | 1.81 | 0.178 | ja | nein |
| OB-SWEEP   | 24 | `[[3,3],[3,15]]` | 2.45 | 0.117 | ja | nein |

Cell-format: rows = outcome_a (False, True), cols = outcome_b (False, True).

**Verdikt:** 0/4 testbare Paare zurückweisen H₀ (Unabhängigkeit). Schwelle p < 0.01 nicht erreicht; nicht einmal p < 0.10.

Alle 4 testbaren Paare sind underpowered (mindestens eine Zelle mit E < 5). Das heißt:
- Selbst wenn echte Interaktion existieren *würde*, könnten wir sie auf diesem Korpus nicht zuverlässig detektieren.
- Die Nicht-Zurückweisung darf **nicht** als „Faktorisierbarkeit bewiesen" gelesen werden, sondern als „auf diesem Korpus ist die Frage nicht entscheidbar."

---

## Caveats und Limitationen

1. **Korpus zu dünn:** 410 events / 71 Co-Firing-Bars / 4 testbare Paare, alle underpowered. Die robuste Beantwortung der Joint-vs-Product-Frage braucht erstens mehr Bars pro Paar (Ziel: E ≥ 5 in jeder 2×2-Zelle, also typischerweise n_paar ≥ 30) und zweitens mehrere Korpus-Schichten (1D + Intraday).
2. **Familien-Imbalance:** BOS hat 100 % Single-Hitrate (18/18). Das ist ein Korpus-Artefakt — BOS feuert nur in eindeutig trending Phasen, und 18 Bars sind für robust 100 % zu wenig.
3. **Triple-Firings unzureichend modelliert:** Die 6 Triple-Bars werden als Beiträge zu allen Paaren gezählt (`(A,B,C)` → trägt zu `(A,B)`, `(A,C)`, `(B,C)` bei). Eine echte 3-way Interaktion (z. B. Stratifikation) wird auf 6 Bars nicht testbar.
4. **Methodisch vorgegeben, nicht nachjustiert:** Die Schwellen (α_FWER=0.05 Bonferroni für Schritt 2, α=0.01 ohne Korrektur für Schritt 3, n_min=10 Co-Firing-Bars, E_min=5) sind im Sprint-Anker festgenagelt bevor die Tests liefen. Keine post-hoc Justage.
5. **OB intraday-only Caveat aus C10b:** OB-Hitrate verdoppelte sich auf Daily gegenüber Intraday. Das könnte in Schritt 2/3 die OB-Co-Firing-Zahlen verzerren — alle 38 OB-Co-Firings sind hier Daily.

---

## Empfehlungen für Folgesprint(s)

### Wenn Joint-Outcome-Modellierung weiter verfolgt werden soll
- **Vorbedingung:** Korpus mit ≥ 30 Co-Firing-Bars pro Paar — entweder über mehr Symbole (Workbook hat 965, Benchmark nutzt 20 → 48× Headroom) oder über Intraday-Korpus (5m/15m).
- **Methodik:** Wiederhole Schritte 2+3 auf dem erweiterten Korpus. Falls dann G-Tests p < 0.01 — *erst dann* Schritt 4 (Stacking-Skizze) öffnen.
- **Ticket:** Folgesprint `docs/sprints/backlog/c10c_replication_widened_corpus.md` (neu) als Vorbedingung für C10d.

### Wenn nicht
- Faktorisierungs-Annahme bleibt **provisorisch akzeptiert**: Pro Familie ein unabhängiger Klassifikator, kein Joint-Modell. Bei Co-Firing-Bars im Promotion-Gate eine simple Aggregations-Regel (z. B. „nimm max(predicted_prob) über alle feuernden Familien", oder „nur traden wenn alle feuernden Familien predicted_prob > threshold sind") — keine zweite Modell-Stufe.
- C10d wird **nicht** eröffnet.

---

## Beziehung zum Hauptziel

> „Wenn die SMC-Calibration-Track-Record nicht eindeutig profitable Setups zeigt, dann habe ich nichts zu verkaufen."

Status nach C10c:
- Die drei profitablen Setups aus C10b (BOS, SWEEP, FVG) sind durch dieses Sprint **nicht entwertet**. Die Per-Familie-Architektur bleibt der Verkaufs-Kern.
- Joint-Outcome-Modellierung als zusätzliche Vermarktungs-Achse: **noch nicht aufschlagbar** auf diesem Korpus. Ehrliche Aussage statt erfundene Zahlen.
- Faktorisierbarkeit als Methodik-Aussage: **provisorisch ja**, aber mit dem Caveat „underpowered". Nicht als Marketing-Claim verwendbar, ohne den Korpus zu erweitern.

---

## Reproduktion

```bash
python3 scripts/c10c_aggregate_per_bar.py
python3 scripts/c10c_cofiring_vs_single.py
python3 scripts/c10c_joint_vs_product.py
```

Erwartet bit-identische Outputs gegenüber den hier verlinkten Artefakten, solange `/tmp/c10b_local_run/measurement_benchmark/` unverändert bleibt.
