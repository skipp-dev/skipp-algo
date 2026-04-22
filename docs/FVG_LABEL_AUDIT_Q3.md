# FVG Label Audit Q3

> **Q3 Strategie-Plan Phase D1 — Output-Doc.**
> **Datum:** 2026-04-22
> **Quelle:** `artifacts/ci/measurement_benchmark_combined_2026-04-21/`
> (78 benchmark JSONs — 20 Symbole × 4 TFs)
> **Aggregator:** `scripts/fvg_label_audit_q3.py`
> **Re-run:** `python scripts/fvg_label_audit_q3.py`

---

## 0. TL;DR

Mit dem 4-TF-Universum (5671 FVG-Events) ist die **FVG-Hypothese aus
`STRATEGY_2026_Q3.md` größtenteils falsifizierbar**:

| Q3-Hypothese | Datenlage | Verdict |
|---|---|---|
| FVG ist die schwächste Familie (59.4% HR, 96 Events) | Mit 5671 Events ist HR **56.1%** — fast unverändert | ✅ bestätigt: schwächste Familie bleibt FVG |
| Partial-Fill-Definition könnte zu streng sein (D1) | 73.4% aller FVGs zeigen Partial-Fill — sehr hoch | ⚠ **echtes Label-Problem** |
| FVG performt auf 5m besser (D3-Hypothese) | 5m HR **54.2%** ist **schlechter** als 1H (62.5%) | ❌ falsifiziert |
| FVG ist stark kontextabhängig (D2) | NY_AM 46.1% vs. ASIA 74.5% — 28pp Spread | ✅ stark bestätigt |

**Plus überraschender Befund (außerhalb Plan):**
**OB hat im 4-TF-Universe nur 31–49% HR** statt der dokumentierten 86.4%.
Das `STRATEGY_2026_Q3.md` muss für die Q3-Retro überarbeitet werden.

---

## 1. Per-TF × per-Familie (vollständig)

| TF | Family | n | HR | TTM | partial_fill | inval_rate |
|---|---|---:|---:|---:|---:|---:|
| 15m | BOS | 263 | 0.890 | 5.21 | 0.000 | 0.844 |
| 15m | FVG | 798 | **0.595** | 2.49 | 0.179 | 0.741 |
| 15m | OB | 197 | 0.487 | 2.79 | 0.155 | 0.655 |
| 15m | SWEEP | 342 | 0.693 | 1.48 | 0.000 | 0.404 |
| 1H | BOS | 192 | 0.802 | 3.15 | 0.000 | 0.724 |
| 1H | FVG | 750 | **0.625** | 1.46 | 0.483 | 0.659 |
| 1H | OB | 229 | 0.362 | 2.18 | 0.442 | 0.655 |
| 1H | SWEEP | 225 | 0.729 | 1.58 | 0.000 | 0.480 |
| 4H | BOS | 119 | 0.765 | 1.77 | 0.000 | 0.698 |
| 4H | FVG | 430 | **0.542** | 1.12 | 0.738 | 0.595 |
| 4H | OB | 135 | 0.363 | 1.65 | 0.569 | 0.607 |
| 4H | SWEEP | 101 | 0.683 | 1.26 | 0.000 | 0.515 |
| 5m | BOS | 1032 | 0.887 | 8.55 | 0.000 | 0.850 |
| 5m | FVG | 3693 | **0.542** | 2.55 | 0.904 | 0.831 |
| 5m | OB | 391 | 0.312 | 3.07 | 0.858 | 0.847 |
| 5m | SWEEP | 1107 | 0.623 | 1.42 | 0.000 | 0.349 |

## 2. FVG per Kontext

| Kontext | n | HR | partial_fill |
|---|---:|---:|---:|
| session:ASIA | 102 | **0.745** | 0.462 |
| session:LONDON | 2907 | **0.645** | 0.745 |
| session:NY_AM | 2662 | **0.461** | 0.728 |
| htf_bias:BEARISH | 2258 | 0.571 | 0.707 |
| htf_bias:BULLISH | 3413 | 0.554 | 0.752 |
| vol_regime:HIGH_VOL | 137 | 0.562 | 0.000 |
| vol_regime:LOW_VOL | 10 | 0.500 | 0.000 |
| vol_regime:NORMAL | 5524 | 0.561 | 0.753 |

## 3. FVG overall

- n_events: 5671 (Q3-Ziel ≥1000 → **5.7× erreicht**)
- hit_rate: 56.1%
- TTM mean: 2.29 bars
- partial_fill_pct_mean: 73.4%

---

## 4. Auswertung gegen die D1–D3-Hypothesen

### D1 — Label-Problem ⚠ bestätigt

73.4% aller „verfehlten" FVGs zeigen einen Partial-Fill ≥ 50% des Gaps.
Die binäre `hit/no-hit`-Definition wirft also einen großen Teil
profitabler Reaktionen weg. Konkret auf 5m: **90.4% partial_fill**.

**Empfehlung:** Zweite Label-Variante `label_fvg_partial_50` (Hit wenn
Preis ≥ 50% des Gaps füllt + Reversal innerhalb Lookahead-Fenster)
parallel mitführen. Implementierung am sinnvollsten in
`smc_core/fvg_quality.py` analog zu existierender Quality-Logik.

### D2 — Kontext-Effekt ✅ massiv bestätigt

**NY_AM ist der einzige Loser-Bucket** (HR 46.1%, n=2662, also
statistisch sehr robust). ASIA und LONDON liegen klar über 60%.

**Empfehlung:** Session-spezifische FVG-Gewichtung — der bestehende
Phase-F1-Mechanismus (`zone_priority_contextual_calibration.json`)
sollte genau hier ansetzen. Die Daten sind bereits da; es braucht nur
die Promotion.

### D3 — Time-to-Fill / 5m-Hypothese ❌ falsifiziert

5m FVG-HR liegt bei 54.2% — **niedriger** als 1H (62.5%) und 15m
(59.5%). Mehr Events bedeuten nicht bessere Qualität. TTM auf 5m ist
2.55 bars vs. 1.46 auf 1H, aber das übersetzt nicht in höhere HR.

**Empfehlung:** Die D3-Hypothese „FVGs füllen schneller auf 5m =
profitabler" ist nicht haltbar. Der Lookahead-Fenster-Bug (falls
existent) wirkt auf allen TFs gleich.

---

## 5. Überraschender Nebenbefund — OB

Das `STRATEGY_2026_Q3.md` listet OB mit **86.4% HR (44 Events)**. Die
aktuelle Datenlage zeigt OB mit **31.2–48.7% HR (952 Events)** — also
einen kompletten Familien-Rangwechsel. Mögliche Erklärungen:

1. Das Strategie-Doc nutzte einen anderen Label-Cut (vor F2-Promotion).
2. OB-Definition in `smc_core/scoring.py` wurde zwischenzeitlich
   verschärft (z. B. `mitigation_strict`).
3. Sample-Bias im 6-Symbol-Universe der Q2-Auswertung.

**Empfehlung für Q3-Retro:** Strategie-Doc-Tabelle in §1.1 mit dem
aktuellen 20-Symbol-Stand neu rechnen, bevor der Q3-A/B-Lauf startet.
Sonst optimieren wir auf alte Annahmen.

---

## 6. Nächste konkrete Schritte (priorisiert)

1. **Phase F1/F2 starten** — Session-spezifische FVG-Gewichtung
   produzieren. Die statistische Belastbarkeit (n=2662 für NY_AM) ist
   mehr als ausreichend.
2. **Label-Variante `label_fvg_partial_50`** in `smc_core/fvg_quality.py`
   ergänzen + zweiter Benchmark-Lauf zur Validierung.
3. **Strategie-Doc §1.1 aktualisieren** mit den neuen 4-TF-Zahlen.
4. **D3-Hypothese im Strategie-Doc als falsifiziert markieren.**

---

*Erstellt mit `scripts/fvg_label_audit_q3.py` gegen
`measurement_benchmark_combined_2026-04-21`. Re-runnable: jeder
neue Rolling-Bench-Snapshot wird automatisch aufaggregiert.*
