# ADR-0019 VPIN A/B Findings

> **Date:** 2026-06-05
> **Feature:** `vpin` — Volume-Synchronized Probability of Informed Trading
> **Module:** `governance/family_vpin_v2.py`
> **Adapter sites:** zone (OB / FVG) + level (BOS / SWEEP)
> **PR:** [#2573](https://github.com/skippALGO/skipp-algo/pull/2573)
> **Verdict: RECORDED-ONLY — no promotion warranted**

---

## 1. Feature definition

```
vpin_at(bars, anchor_idx, *, period=ATR_PERIOD) -> float | None
```

VPIN = `sum(abs(signed_volume_k))` / `sum(abs_volume_k)` over the trailing
point-in-time window `[anchor - period + 1, anchor]`, clamped to `[0, 1]`.

- **Distinction from `ofi_imbalance`:** OFI is the *net* imbalance
  (`sum(signed) / sum(abs)`); VPIN is the *total activity* ratio
  (`sum(|signed|) / sum(abs)`). Balanced-but-toxic flow (`+100` then `−100`)
  yields VPIN = 1.0, OFI = 0.0 — confirmed on real data and by test.
- **Inputs:** `signed_volume` and `abs_volume` per bar, embedded by
  `pull_databento_edge_input.py --with-trades` (equity tape, not OPRA).
- **Honest-None:** returned on missing/NaN/negative volumes, zero total volume,
  short history, bad period, out-of-range anchor.
- **Leak-safe:** strictly point-in-time; proven by poisoned-future-bars test.

## 2. Data

| Parameter | Value |
|-----------|-------|
| Source | Databento `XNAS.ITCH` trades schema |
| Symbols | AAPL, MSFT, NVDA, AMZN, TSLA |
| Window | 2026-02-02 → 2026-05-02 (3 months, 15m bars) |
| Total events | 10,981 |
| Events with `vpin` attached | 8,905 (81%) |
| VPIN range | 0.0023 – 0.8268, mean 0.136 |

Persisted locally at `~/.local/share/skipp/vpin_followup/` (5 per-symbol
`*_15m.json` + `events.json`). Reproducible runner:
`run_vpin_followup.sh [REPO_DIR]`.

## 3. A/B results

### 3.1 Direction (does VPIN predict trade direction?)

| Family | n_oos | baseline AUC | candidate AUC | resolution Δ | verdict |
|--------|------:|-------------:|--------------:|-------------:|---------|
| BOS | 2,065 | 0.569 | 0.482 | −0.0066 | `no_lift` |
| FVG | 1,645 | 0.550 | 0.467 | −0.0042 | `no_lift` |
| OB | 1,625 | 0.527 | 0.493 | −0.0010 | `no_lift` |
| SWEEP | 360 | 0.537 | 0.450 | −0.0058 | `no_lift` |

**Exit code 2.** Candidate AUC < 0.5 everywhere → VPIN-alone is
anti-predictive of direction. `no_regression = true` across the board (Brier
didn't blow up). `families_lifted = []`.

### 3.2 Magnitude (does VPIN predict trade-outcome magnitude?)

| Family | n_oos | baseline AUC | candidate AUC | resolution Δ | verdict |
|--------|------:|-------------:|--------------:|-------------:|---------|
| BOS | 2,065 | 0.632 | 0.482 | −0.0093 | `regresses_calibration` |
| FVG | 1,645 | 0.580 | 0.509 | −0.0023 | `no_lift` |
| OB | 1,625 | 0.587 | 0.520 | −0.0017 | `no_lift` |
| SWEEP | 360 | 0.693 | 0.437 | −0.0162 | `regresses_calibration` |

**Exit code 2.** Score-alone predicts magnitude well (baseline AUC 0.58–0.69),
but VPIN-alone adds nothing; BOS and SWEEP actively regress calibration.
VPIN's thesis (toxicity → volatility → magnitude) is **not confirmed** on
this data. `families_lifted = []`.

### 3.3 Regime × Direction (`--stratify-by abs_feature`)

| Family | verdict | resolution spread | n_oos |
|--------|---------|------------------:|------:|
| BOS | `no_regime_effect` | — | 2,065 |
| FVG | `no_regime_effect` | — | 1,645 |
| OB | `no_regime_effect` | — | 1,625 |
| SWEEP | `regime_conditions_resolution` | 0.0250 | 360 |

`families_conditioned = ['SWEEP']`. Only SWEEP (smallest family, n=360)
shows any regime interaction; BOS/FVG/OB show no regime effect.

### 3.4 Regime × Magnitude (`--stratify-by abs_feature --label magnitude`)

| Family | verdict | resolution spread | n_oos |
|--------|---------|------------------:|------:|
| BOS | `no_regime_effect` | — | 2,065 |
| FVG | `no_regime_effect` | — | 1,645 |
| OB | `no_regime_effect` | — | 1,625 |
| SWEEP | `regime_conditions_resolution` | 0.0635 | 360 |

`families_conditioned = ['SWEEP']`. Same pattern — SWEEP alone conditions,
but never lifts standalone. At n=360, this is most likely noise.

## 4. Interpretation

1. **VPIN does not lift resolution** on direction or magnitude, standalone
   or regime-conditioned. The equity-tape toxicity signal is informationally
   redundant with what `score` already captures.

2. **Same outcome class as `signed_uoa_notional`** (ADR-0020): the feature
   extracts correctly, attaches cleanly, but the A/B says don't promote it.
   The onramp process worked as designed — it protected the gate from a
   feature that would have degraded calibration.

3. **SWEEP regime conditioning** (spread 0.025 direction, 0.064 magnitude)
   is thin-sample noise (n=360), not a promotion signal. SWEEP is the
   smallest family and never lifts standalone; the conditioning likely
   reflects the low-n instability rather than a real interaction.

4. **VPIN vs OFI:** despite being mathematically distinct (triangle
   inequality holds: `vpin >= |ofi|`), the distinction doesn't translate
   into a predictive edge on the SMC event families in this 3-month window.

## 5. Decision

**VPIN stays RECORDED-ONLY.** No gate/score wiring. The feature is safe to
merge as a shadow feature (PR #2573); it simply records without influencing
trading decisions. If future windows or additional symbols show a different
signal, the persisted data and runner make re-evaluation free.

## 6. Lessons learned

- The paid `--with-trades` Databento pull also re-feeds `ofi_imbalance`,
  `kyle_lambda`, and `average_trade_size` — one pull validates all
  trade-based features simultaneously.
- VPIN's candidate AUC < 0.5 means it's not just neutral but
  **anti-predictive** of direction — a stronger negative signal than
  random. This matches the microstructure literature: VPIN was designed to
  predict **flash-crash risk** (extreme events), not the direction of
  ordinary SMC zone/level outcomes.
- The magnitude test was the most theoretically promising (toxicity →
  volatility), but even there VPIN shows no lift. The score's existing
  magnitude prediction (AUC 0.58–0.69) already captures whatever
  information the spread/volume structure contains.
