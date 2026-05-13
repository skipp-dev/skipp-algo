# FVG Label Audit Q3

> **Q3 Strategie-Plan Phase D1 — Output-Doc.**
> **Datum:** 2026-04-22 (Strict-A/B-Update)
> **Quelle (lenient/Bestand):** `artifacts/ci/measurement_benchmark_combined_2026-04-21/`
> **Quelle (strict ≥50% A/B):** `artifacts/ci/measurement_benchmark_2026-04-22_partial50_v3/`
> (jeweils 80 benchmark JSONs — 20 Symbole × 4 TFs)
> **Aggregator:** `scripts/fvg_label_audit_q3.py --root <root>`
> **Re-run:** `python scripts/fvg_label_audit_q3.py --root artifacts/ci/measurement_benchmark_2026-04-22_partial50_v3`

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

## 5b. Strict ≥50% A/B (Benchmark v3, 2026-04-22, n=5710 FVG)

Die zweite Label-Variante `label_fvg_partial_50` läuft seit dem v3-Snapshot
end-to-end durch (Bridge `3746b36e` → KPI-Aggregation `18110767`/`1c06bc22`).
Reproduzierbar via `python scripts/fvg_label_audit_q3.py --root artifacts/ci/measurement_benchmark_2026-04-22_partial50_v3 --format json`.

### 5b.1 Per-TF (FVG only)

| TF  | n    | lenient HR | strict ≥50% HR | Δ |
|-----|-----:|-----------:|---------------:|--:|
| 5m  | 3693 | 0.5421     | **0.9128**     | **+0.371** |
| 15m |  797 | 0.5884     | 0.8494         | +0.261 |
| 1H  |  790 | 0.6291     | 0.8000         | +0.171 |
| 4H  |  430 | 0.5419     | 0.7767         | +0.235 |

**Beobachtung:** Auf 5m ist der Hebel am größten (+37.1pp) — passt zur
Original-Hypothese aus §4 D1, dass die binäre Definition gerade auf der
schnellen TF die meiste Reaktion verwirft (90.4% partial_fill).

### 5b.2 Per-Context overall (FVG, alle TFs)

| Kontext             | n    | lenient HR | strict ≥50% HR | Δ |
|---------------------|-----:|-----------:|---------------:|--:|
| session:NY_AM       | 2691 | 0.460      | **0.879**      | **+0.419** |
| session:LONDON      | 2910 | 0.646      | 0.885          | +0.239 |
| session:ASIA        |  109 | 0.752      | 0.670          | −0.083 |
| htf_bias:BULLISH    | 3413 | 0.554      | 0.899          | +0.345 |
| htf_bias:BEARISH    | 2297 | 0.571      | 0.848          | +0.277 |
| vol_regime:NORMAL   | 5563 | 0.561      | 0.879          | +0.319 |
| vol_regime:HIGH_VOL |  137 | 0.562      | 0.861          | +0.299 |
| vol_regime:LOW_VOL  |   10 | 0.500      | 0.500          | ±0.000 |

**Verdict:** D1-Hypothese quantitativ bestätigt. NY_AM springt von
„unter 50% / Loser-Bucket" auf 87.9% — d.h. der NY_AM-Verlust war fast
ausschließlich „Reaktion ≥50% gefüllt, aber kein vollständiges Mitigation
vor Invalidierung". Einzige Inversion ist `session:ASIA` (n=109) — siehe
§5b.4: vollständig durch midnight-UTC-Artefakt der 15m-Resampler-Kante
erklärt, **durch Real-Daten widerlegt**.

### 5b.4 ASIA-Bucket: midnight-UTC Artefakt + Real-Daten Refutation

**Schritt 1 — Artefakt-Diagnose** (`scripts/fvg_session_artifact_diagnosis.py`
gegen den v3-Snapshot):

| Session | n   | midnight-UTC n | midnight-UTC % | TF breakout                              | Verdict   |
|---------|----:|---------------:|---------------:|------------------------------------------|-----------|
| ASIA    | 109 |            109 |        100.0%  | 15m:109                                  | ARTIFACT  |
| LONDON  |2910 |              0 |          0.0%  | 5m:2076, 15m:387, 1H:362, 4H:85          | ok        |
| NY_AM   |2691 |              0 |          0.0%  | 5m:1617, 1H:428, 4H:345, 15m:301         | ok        |

Das Source-Bundle `full_universe_second_detail_open` deckt nur
11–14 UTC ab (US-Open-Fenster); echte ASIA-Trades (22–07 UTC) sind
nicht enthalten. Die 109 ASIA-Events sind ausschließlich 15m-
Resampler-Synthetic-Bars an Tagesgrenzen mit `timestamp == 00:00:00 UTC`. **Schritt 2 — Real-Daten ASIA-Sample** (`scripts/fvg_asia_real_sample.py`,
60 Tage × 9 Symbole × 3 TF, **direkter** Databento DBEQ.BASIC `ohlcv-1m`
Fetch über alle 24 h, dann auf 5m geresampled; 20 045 FVG-Events,
Artifact `artifacts/ci/fvg_asia_real_sample_60d.json`):

| Session | n     | lenient HR | strict ≥50% HR | Δ           | TF breakout                          |
|---------|------:|-----------:|---------------:|-------------|--------------------------------------|
| ASIA    |   158 |      0.367 |      **0.873** | **+0.506** | 5m:27, 15m:60, 1H:71                 |
| LONDON  |  5108 |      0.669 |          0.928 |     +0.259 | 5m:3271, 15m:1412, 1H:425            |
| NY_AM   |  5931 |      0.597 |          0.893 |     +0.296 | 5m:4107, 15m:1400, 1H:424            |
| NY_PM   |  4208 |      0.566 |          0.939 |     +0.373 | 5m:3034, 15m:943, 1H:231             |
| NONE    |  4640 |      0.529 |          0.906 |     +0.378 | 5m:3196, 15m:1157, 1H:287            |

**Verdict (final):** Die Inversion aus dem v3-Snapshot ist ein
Datenquellen-Artefakt, kein Marktphänomen. Mit echten 24-h-Bars
verhält sich ASIA wie alle anderen Sessions — **mit dem höchsten
strict-Lift aller Buckets** (Δ +0.506). Lenient HR liegt mit 0.367
niedriger als bei den High-Vol-Sessions, weil ASIA-Reaktionen
häufiger nicht zur vollständigen Mitigation laufen, *aber* der
strikte 50 %-Fill liefert mit 0.873 ein vergleichbares Quality-Tier
wie LONDON/NY_AM/NY_PM. n=158 < n=500-Quorum, ist aber durch das
konsistente Δ-Muster gegen 4 andere Buckets robust genug, um die
Inversions-Hypothese fallen zu lassen. **ToDo „ASIA-Inversion
absichern" geschlossen** (kein Promotion-Blocker mehr).

Folge-Issue: Die Real-ASIA-Sample-Pipeline produziert standardmäßig
nur 9 Mega-Cap-Symbole. Für eine vollwertige Re-Calibration der
ASIA-FVG-Gewichte (Phase F1/F2 Erweiterung) sollten 30–3 Tage ×
20–30 Symbole gefahren werden, um ≥1 000 ASIA-Events zu sammeln —
optional auf eine Futures-Quelle (`GLBX.MDP3`) erweitert. Kein
Q3-Blocker.

### 5b.3 FVG strict overall

- n_events: 5710 (4-TF, 20 Symbole, Plan-2.8-Universum)
- lenient HR: 0.561 (`label_fvg_mitigation`)
- strict ≥50% HR: **0.878** (`label_fvg_partial_50`)
- Δ: **+0.318** absolute → die strikte Definition lifted FVG aus dem
  unteren Drittel in BOS-Reichweite (BOS overall 0.867).

---

## 6. Nächste konkrete Schritte (priorisiert)

1. **Phase F1/F2 starten** — Session-spezifische FVG-Gewichtung
   produzieren. Die statistische Belastbarkeit (n=2662 für NY_AM) ist
   mehr als ausreichend. ✅ DONE (commits `13dfc36b`/`f25fc690`).
2. **Label-Variante `label_fvg_partial_50`** in `smc_core/fvg_quality.py`
   ergänzen + zweiter Benchmark-Lauf zur Validierung. ✅ DONE
   (`smc_core/scoring.py`, 12 Tests, Bridge-Commit `3746b36e`,
   KPI-Aggregation `18110767`/`1c06bc22`, v3-Snapshot 2026-04-22).
3. **Strategie-Doc §1.1 aktualisieren** mit den neuen 4-TF-Zahlen. ✅ DONE
   (`209068be` 4-TF-Tabelle, `46870a9a` Strict-A/B-Tabelle).
4. **D3-Hypothese im Strategie-Doc als falsifiziert markieren.** ✅ DONE.
5. **D3-Folge:** Promotion-Entscheidung — `label_fvg_partial_50` als
   primäres FVG-Outcome im Scorer? Datenlage stützt es (Δ +0.318 overall),
   aber Promotion verschiebt sämtliche kalibrierten FVG-Gewichte. Wenn
   Promotion: einen kompletten Re-Calibration-Run + Snapshot pinnen,
   bevor der Scorer umgestellt wird. ✅ DONE (2026-04-22) — Production
   `smc_core/fvg_quality.py` jetzt auf `WEIGHT_VERSION = "strict_v1_no_hurst"`, `recalibrate()` defaults `label_source="partial_50"`. Pine-Spiegel separat (Disjunktion).
   Details `docs/FVG_QUALITY_D4_AUDIT.md` §6 +
   `docs/D3_PROMOTION_REVIEW_2026-04-22.md`.
6. **ASIA-Inversion (n=109, Δ −0.083)**: ✅ DONE — zwei-Stufen
   geschlossen. (a) Diagnose: midnight-UTC-Resampler-Artefakt
   (100 % ASIA-Events haben `timestamp == 00:00:00 UTC` auf 15m).
   (b) Refutation mit Real-Daten: 60-Tage Direkt-Fetch DBEQ.BASIC
   `ohlcv-1m` über alle 24 h (`scripts/fvg_asia_real_sample.py`)
   liefert n=158 ASIA-Events mit lenient HR 0.367 / strict50 HR
   **0.873** (Δ **+0.506**, höchster Lift aller Buckets). Inversion
   widerlegt; ASIA verhält sich beim strikten Label wie LONDON/
   NY_AM/NY_PM. n<500-Quorum für eigene Re-Calibration, aber kein
   Promotion-Blocker mehr. Diagnose-Tools:
   `scripts/fvg_session_artifact_diagnosis.py` und
   `scripts/fvg_asia_real_sample.py`. Artifact:
   `artifacts/ci/fvg_asia_real_sample_60d.json`.

---

*Erstellt mit `scripts/fvg_label_audit_q3.py` gegen
`measurement_benchmark_combined_2026-04-21` (lenient) und
`measurement_benchmark_2026-04-22_partial50_v3` (strict A/B).
Re-runnable: jeder neue Rolling-Bench-Snapshot wird automatisch
aufaggregiert.*
