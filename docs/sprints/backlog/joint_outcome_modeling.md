# Backlog — Joint-Outcome-Modellierung bei Co-Firing

**Status:** Vorgemerkt (kein aktiver Sprint)
**Eltern-Sprint:** C10b — Family-Partition-Validation (abgeschlossen 2026-05-13)
**Sprache:** Deutsch
**Autor-Identität:** `skipp-dev <preuss.steffen@yahoo.com>`

---

## Auslöser

Step 2f der C10b-Replikation (siehe `docs/research/c10b/co_firing_and_replication_findings.md`) hat zwei zunächst widersprüchlich wirkende Signale produziert:

| Signal | Wert | Sprint-Schwelle |
|---|---|---|
| Multi-Firing-Bars (≥ 2 Familien auf gleicher Bar) | **22.61 %** | > 20 % → Pooling-Tendency |
| Max Cramér's V auf paarweisen Outcomes der Co-Firing-Bars | **0.27** | > 0.5 → Pooling, < 0.2 → Beibehalt |

Lesart: **Familien feuern oft gleichzeitig auf derselben Kerze, ihre Outcomes sind aber nicht stark korreliert.** Das ist nicht das Bild „die schauen alle auf dasselbe" (das wäre hohes V), sondern das Bild „komplementäre Signale, die sich auf derselben Bar überlappen."

Die C10b-Architekturentscheidung (Beibehalt für BOS/SWEEP/FVG, gesonderte Behandlung OB intraday-only) bleibt davon unberührt — sie löst aber **nicht** die Folgefrage: Was tun wir, wenn zwei oder drei Familien auf derselben Bar feuern und je eine eigene Vorhersage liefern?

Heute: Die Per-Familie-Klassifikatoren liefern unabhängige Wahrscheinlichkeiten. Bei Co-Firing entstehen Konflikte (z. B. SWEEP sagt 0.78, FVG sagt 0.53, OB sagt 0.62), und das Promotion-Gate / die Trade-Sizing-Logik hat keinen sauberen Mechanismus, daraus eine kombinierte Entscheidung zu treffen.

---

## Hypothese, die geprüft werden soll

Eine *joint-outcome model* (z. B. eine zweite Modell-Stufe oberhalb der vier Per-Familie-Klassifikatoren) kann auf den 22.6 % Co-Firing-Bars eine bessere Kalibration und höhere Konfidenz liefern als jede Einzelfamilie alleine — **ohne** die Familien-Separation aufzugeben.

Konkret zwei prüfbare Vermutungen:
1. **Konfidenz-Vermutung:** Auf Co-Firing-Bars ist die Trefferquote höher als auf Einzelfeuer-Bars (intuitiv: zwei unabhängige Bestätigungen). Heute nicht in der Pipeline.
2. **Komplementaritäts-Vermutung:** Die maximale Cramér's V von 0.27 lässt rein theoretisch noch Raum für eine Joint-Probability, die nicht das Produkt der Einzelwahrscheinlichkeiten ist — sprich: eine echte Interaktion in der Outcome-Verteilung.

---

## Vorgeschlagener Mini-Sprint (1–2 Tage Analyse, bevor Code geschrieben wird)

Genau analog zum C10b-Schnitt: Status-Anker-Doc, keine Code-Änderung an `ml/`, bis Daten sprechen.

### Schritte

| # | Schritt | Output |
|---|---|---|
| 1 | Auf dem 1D-Korpus (`/tmp/c10b_local_run/measurement_benchmark/`): Per-Bar-Aggregation → für jede Bar mit ≥ 2 Familien die Liste `(family, predicted_prob, outcome)` extrahieren. | `docs/research/co_firing/per_bar_predictions.jsonl` |
| 2 | Trefferquote auf Co-Firing-Bars vs. Single-Firing-Bars vergleichen (deskriptiv + z-Test pro Familie). | `docs/research/co_firing/cofiring_vs_single_hitrate.json` |
| 3 | Outcome-Verteilung auf Co-Firing-Bars: für jede Familien-Kombination (z. B. {FVG, SWEEP}) die empirische Joint-Distribution (TT, TF, FT, FF) gegen Produkt-der-Marginale testen (G-Test / Likelihood-Ratio). Schwelle: G-Test p < 0.01 → Interaktion vorhanden. | `docs/research/co_firing/joint_vs_product.json` |
| 4 | Falls Schritt 3 Interaktionen findet: einfaches Stacking-Modell skizzieren (LightGBM auf `(symbol, timeframe, family_set, [predicted_prob_je_familie], context)` → joint outcome). Noch kein Training. | `docs/research/co_firing/stacking_skizze.md` |
| 5 | Architekturvorschlag schreiben: Wo lebt das Stacking-Modell, wie greift es ins Promotion-Gate `smc_integration/release_policy.py`, wie ändern sich C8-Phase-B-Kriterien für Co-Firing-Bars? | `docs/sprints/c10c_joint_outcome_modeling.md` (würde dann ein eigener Sprint werden) |

Vor Schritt 4 ist die Entscheidung pure Datenanalyse — kein Code-Eingriff.

### Datengrundlage

Genug oder zu wenig? — Ehrliche Einschätzung:

- 1D-Korpus: 71 Co-Firing-Bars über 4 Familien-Paare. Reicht für deskriptive Statistik, **nicht** für robustes Stacking-Training. Für Training braucht es entweder:
  - Mehr Symbole (das Workbook hat 965 Symbole, der Benchmark nutzt 20 → 48× mehr möglich, wenn man bereit ist auf den vollen Universe-Lauf zu warten), oder
  - Intraday-Korpus zurück (5m/15m), sobald Cron-Brücke #2197 grün ist und das Production-Bundle wieder im CI-Runner verfügbar ist.

Empfehlung: Schritte 1–3 jetzt auf dem 1D-Korpus → wenn Interaktion gefunden wird, dann erst Schritt 4 + 5 + Daten-Erweiterung anpacken.

---

## Beziehung zum Hauptziel

> „Wenn die SMC-Calibration-Track-Record nicht eindeutig profitable Setups zeigt, dann habe ich nichts zu verkaufen."

Die Joint-Outcome-Modellierung ist **keine Voraussetzung** dafür, die heutige Per-Familie-Architektur zu verkaufen — die drei profitablen Setups (BOS, SWEEP, FVG) stehen auch ohne das. Aber:

- Wenn das Joint-Modell **funktioniert**, dann sind die Co-Firing-Bars eine zusätzliche Vermarktungs-Achse: „Bei Mehrfach-Bestätigung steigt die Trefferquote von 78 % (Einzel-SWEEP) auf X %."
- Wenn das Joint-Modell **nicht funktioniert** (alle G-Tests p > 0.01), dann ist die Frage geklärt: Familien sind nicht nur statistisch unterscheidbar (das wussten wir aus C10b), sondern auch in ihren Outcomes faktorisierbar. Das ist ebenfalls eine verkaufbare Methodik-Aussage.

Beide Outcomes sind nützlich. Kein Risiko, nur Asymmetrischer Upside.

---

## Nicht-Ziele

- Keine Änderung an C10b-Verdikt (Beibehalt-Architektur).
- Keine Änderung am Promotion-Gate, bis das Joint-Modell empirisch belegt ist.
- Kein Refactor in `ml/training/`, bis die Datenfrage geklärt ist.

---

## Vorbedingungen, bevor dieser Sprint aktiviert wird

1. C10b in PR #2196 gemerged (Endurteil festgeschrieben).
2. Cron-Brücke #2197 grün — sonst gibt es keinen Intraday-Korpus zur Verbreiterung der Co-Firing-Beobachtungen.
3. Mindestens eine Woche zwischen dieser Markierung und dem Sprint-Start — die Lehre aus C10b ist, dass solche Methodik-Sprints nicht zwischen anderen Arbeiten gedrückt werden sollten.

---

## Referenzen

- `docs/sprints/c10b_family_partition_validation.md` (Eltern-Sprint, Step 2f, Endurteil)
- `docs/research/c10b/co_firing_matrix.json` (22.61 % Multi-Firing)
- `docs/research/c10b/cramers_v_pairwise.json` (max V = 0.27)
- `docs/research/c10b/co_firing_and_replication_findings.md` (Findings + Methodik)
- `scripts/c10b_compute_cofiring.py` (Reproduktion)
