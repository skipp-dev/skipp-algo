# C10b — Co-Firing + Replikation auf zweitem Korpus

**Status:** Beweisstück, nicht Endurteil
**Datum:** 2026-05-13
**Branch:** `docs/c10b-family-partition-validation`
**Author identity:** `skipp-dev <preuss.steffen@yahoo.com>`

## Zweck

Schließt die zwei in PR #2196 als „offen" gekennzeichneten Punkte des Sprints
`c10b_family_partition_validation`:

1. **Co-Firing-Anteil pro Bar + Cramér's V auf Co-Firing-Outcomes** — vorher technisch
   blockiert (leere `events_*_*.jsonl` aus CI, weil weder Production-Bundle noch
   Workbook im CI-Runner verfügbar).
2. **Replikation auf einem zweiten, unabhängigen Korpus** — bevor die provisorische
   Step-2e-Empfehlung („Beibehalt für BOS/SWEEP/FVG, OB-Sonderbehandlung") zu einem
   Endurteil wird.

## Setup des zweiten Korpus

| Eigenschaft | v4-Korpus (Step 2a–2e) | 1D-Korpus (diese Replikation) |
|---|---|---|
| Quelle | `artifacts/ci/measurement_benchmark_combined_2026-04-23/` (aggregiert) | Lokaler Lauf `2026-05-13`, `/tmp/c10b_local_run/measurement_benchmark/` |
| `bars_source_mode` | (CI, Production-Bundle) | `workbook_fallback` |
| Workbook | – | `databento_volatility_production_20260307_114724.xlsx` (Root), Sheet `daily_bars`, 27 928 Zeilen, 965 Symbole |
| Symbole | benchmark universe | AAPL, MSFT, AMZN, GOOGL, META, NVDA, TSLA, JPM, BAC, GS, MS, V, UNH, JNJ, HD, XOM, CVX, COP, OXY, CAT (20) |
| Timeframes | 5m / 15m / 1H / 4H | 1D (einzig möglich über Workbook-Fallback in `_load_source_bars`, line 208 `measurement_evidence.py`) |
| n_events | 10 064 | 410 |
| Zeitraum | bis 2026-04-23 | 2026-01-26 → 2026-03-06 |
| Per-Event-Bar-Zeitstempel | rekonstruiert (binned) | echt aus `EventLedgerRecord.timestamp` |

Der 1D-Korpus ist **echt unabhängig** vom v4-Korpus: andere Bar-Quelle (Workbook
statt Production-Bundle), anderer Zeithorizont, anderer Timeframe, andere
Universe-Größe. Co-Firing kann erstmals direkt aus echten `bar_timestamp`
ausgewertet werden, weil der Roh-Ledger (`events_*_1D.jsonl`) jetzt nicht-leer ist.

## 1) Co-Firing pro Bar

Artefakt: `docs/research/c10b/co_firing_matrix.json`

| Familien pro Bar | # Bars |
|---|---|
| 1 | 243 |
| 2 | 65 |
| 3 | 6 |
| 4 | 0 |
| **Total Bars** | **314** |
| **Multi-Firing (≥2)** | **71** |
| **Multi-Firing-%** | **22.61 %** |

Sprint-Schwellen (`docs/sprints/c10b_family_partition_validation.md`):
- `< 5 %` → Beibehalt-Tendency
- `> 20 %` → Pooling-Tendency

**Co-Firing-Verdikt: POOLING_TENDENCY (22.61 %).**

Paarweise Co-Occurrence:
| Pair | # Co-Firing-Bars |
|---|---|
| OB & SWEEP | 24 |
| FVG & SWEEP | 24 |
| BOS & OB | 12 |
| BOS & FVG | 12 |
| BOS & SWEEP | 6 |
| FVG & OB | 5 |

## 2) Cramér's V auf Co-Firing-Outcomes

Artefakt: `docs/research/c10b/cramers_v_pairwise.json`

Methode: pro Family-Paar (A,B) — 2×2 Kontingenztafel mit binärem Outcome
(TP-Hit vor SL) eingeschränkt auf Bars, auf denen **beide** Familien gefeuert haben.

| Pair | V | n (gemeinsame Bars) | χ² |
|---|---|---|---|
| BOS × OB | 0.000 | 12 | 0.000 |
| BOS × FVG | 0.255 | 12 | 0.779 |
| BOS × SWEEP | 0.000 | 6 | 0.000 |
| OB × FVG | 0.250 | 5 | 0.313 |
| OB × SWEEP | 0.178 | 24 | 0.758 |
| FVG × SWEEP | 0.266 | 24 | 1.698 |

Sprint-Schwellen:
- alle V < 0.2 → Beibehalt
- irgendein V > 0.5 → Pooling

**Cramér's-V-Verdikt: INCONCLUSIVE_ZONE (max V = 0.266).**
n in den meisten Kontingenztafeln ist klein (5–24); keine V überschreitet 0.5.

## 3) Replikation der Variance-Decomposition (Step 2d)

Artefakt: `docs/research/c10b/family_partition_analysis_1d_corpus.json`

### Baseline-Hit-Raten

| Familie | v4 (n) | v4-Rate | 1D (n) | 1D-Rate | Δ |
|---|---|---|---|---|---|
| BOS | 1 614 | 0.857 | 42 | 0.976 | +0.119 |
| OB | 966 | 0.319 | 96 | 0.688 | +0.369 |
| FVG | 5 710 | 0.570 | 147 | 0.531 | −0.039 |
| SWEEP | 1 774 | 0.656 | 125 | 0.784 | +0.128 |

**Globale Rangfolge:** v4: `BOS > SWEEP > FVG > OB`. 1D: `BOS > SWEEP > OB > FVG`.
OB-Hit-Rate ist auf 1D **signifikant höher** als auf 5m/15m/1H/4H. Mögliche
Erklärung: Daily-Bars filtern Mikrostruktur-Noise weg, dem OB-Familie am
empfindlichsten ausgesetzt war.

### Paarweise z-Tests (Bonferroni α = 0.00833)

| Pair | Δhit | z | p | reject pool? |
|---|---|---|---|---|
| BOS vs OB | 0.289 | 3.739 | 0.000185 | ✅ |
| BOS vs FVG | 0.446 | 5.274 | ~0 | ✅ |
| BOS vs SWEEP | 0.192 | 2.885 | 0.003919 | ✅ |
| OB vs FVG | 0.157 | 2.433 | 0.014964 | ❌ (p > α_bonf) |
| OB vs SWEEP | −0.096 | −1.625 | 0.104082 | ❌ |
| FVG vs SWEEP | −0.253 | −4.358 | 0.000013 | ✅ |

4 von 6 Paaren signifikant. Die zwei nicht-signifikanten Paare (OB×FVG, OB×SWEEP)
sind beide power-limitiert (n=96 für OB) und im 1D-Regime ist OB *quantitativ
näher an SWEEP als auf 5m/15m*. Auf v4 mit n=966 OB hatten alle 6 Paare p≈0.

### Variance-Decomposition auf kontextuellen Gewichten

| Komponente | v4 | 1D-Replikation |
|---|---|---|
| η²_family | 0.7944 | **0.9845** |
| η²_context | 0.1109 | 0.0068 |
| η²_residual | 0.0947 | 0.0087 |

**η²_family bleibt nicht nur hoch — es ist auf dem 1D-Korpus sogar dominanter.**
Das ist die zentrale Replikations-Aussage: das Hit-Rate-Signal kommt
überwältigend aus der Family-Achse, nicht aus dem Kontext-Mix. Die v4-Schlüssel-
Aussage „Pooling über Familien zerstört Information" überträgt sich auf den 1D-Korpus.

### Within-family context dispersion (std über alle Kontext-Buckets)

| Familie | v4 std | 1D std |
|---|---|---|
| BOS | 0.0204 | 0.0194 |
| OB | **0.1245** | **0.0052** |
| FVG | 0.0552 | 0.0069 |
| SWEEP | 0.0549 | 0.0454 |

OB's auffällige hohe Kontext-Streuung in v4 (std=0.124, der Hauptgrund für die
„Sonderbehandlung"-Empfehlung) **reproduziert sich auf 1D nicht** (std=0.005).
Wahrscheinlichste Lesart: die OB-Heterogenität in v4 stammte aus
Session-Mikrostruktur (ASIA 0.77 vs LONDON 0.37), die auf Daily-Bars wegfällt
weil Daily-Events nur ein Session-Bucket (`NONE`) haben.

### Rank-Inversionen

v4 hatte zwei Rank-Inversionen (session:ASIA, session:LONDON). Auf 1D sind keine
nachweisbar, weil die Daily-Bar-Daten nur einen Session-Wert (`NONE`) tragen
(keine Intraday-Aufteilung möglich). Diese Frage ist im 1D-Korpus **nicht
beantwortbar**, nicht „beantwortet mit Nein".

## Zusammenfassung & ehrliche Einordnung

Was repliziert:
- **η²_family bleibt dominant** (0.79 → 0.98). Pooling über Familien zerstört
  Information — auf beiden Korpora.
- **4 von 6 paarweisen Familien-Vergleichen bleiben signifikant** trotz n=410
  (vs. n=10 064). Das ist ein starkes power-bereinigtes Replikationssignal.

Was sich verschoben hat:
- **OB-Hit-Rate stark höher** auf 1D (0.69) als auf 5m/15m/1H/4H (0.32). OB
  ist auf längerem Timeframe ein qualitativ anderes Setup.
- **OB-Kontextstreuung ist auf 1D nicht reproduzierbar** — fast sicher weil
  Daily-Bars nur einen Session-Wert haben, nicht weil OB konsistenter geworden ist.

Was neu auftaucht:
- **Co-Firing 22.6 % auf Bar-Ebene** überschreitet die 20 %-Pooling-Schwelle des
  Sprints. Aber Cramér's V (max 0.27) bleibt in der mittleren Zone, weit unter
  der 0.5-Pooling-Schwelle. Beide Signale zusammen: Familien feuern oft *auf
  derselben Bar*, ihre *Outcomes* sind aber nicht stark korreliert.

Konsequenz für das Endurteil:
- Die Step-2e-Empfehlung (Beibehalt für BOS/SWEEP/FVG, OB-Sonderbehandlung)
  steht **nicht im Widerspruch zu dieser Replikation**, aber sie ist auf 1D
  *nicht vollständig prüfbar* (Session-Kontext fehlt).
- Die OB-Sonderbehandlung sollte explizit als „intraday-only" geltend gemacht
  werden — auf Daily verhält sich OB anders und braucht andere Behandlung.
- Co-Firing > 20 % auf Bar-Ebene rechtfertigt einen separaten Punkt im
  Sprint-Backlog: *Joint-Outcome-Modellierung* (nicht Pooling der Familien,
  sondern explizites Modell für „mehrere Familien feuern gemeinsam → kombinierte
  Vorhersage").

Provisorische Step-2e-Verdikt-Empfehlung bleibt bestehen, mit den drei
explizit dokumentierten Vorbehalten oben.

## Artefakt-Pfade

- `docs/research/c10b/co_firing_matrix.json`
- `docs/research/c10b/cramers_v_pairwise.json`
- `docs/research/c10b/family_partition_analysis_1d_corpus.json`
- `docs/research/c10b/family_partition_analysis_v4_corpus.json` (existing baseline)
- Local-only (not committed): `/tmp/c10b_local_run/measurement_benchmark/` (events_*_1D.jsonl)

## Reproduktions-Kommandos

```bash
# 1) Roh-Events erzeugen
python3 scripts/run_smc_measurement_benchmark.py \
  --symbols AAPL,MSFT,AMZN,GOOGL,META,NVDA,TSLA,JPM,BAC,GS,MS,V,UNH,JNJ,HD,XOM,CVX,COP,OXY,CAT \
  --timeframes 1D \
  --output-dir /tmp/c10b_local_run/measurement_benchmark

# 2) Co-Firing + Cramér's V
python3 /tmp/c10b_local_run/compute_cofiring.py

# 3) Variance-Decomposition (Step 2d-Replikation)
python3 /tmp/c10b_local_run/compute_variance_decomp.py
```
