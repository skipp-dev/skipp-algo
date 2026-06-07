# ADR-0021 Cross-Asset Lead-Lag A/B Findings

> **Date:** 2026-06-05
> **Scope:** Pre-registered A/B of the `cross_lead_lag` shadow feature
> (ADR-0021) — an asymmetric lag-1 cross-correlation ratio between a SPY
> benchmark and each traded name — on the recorded FamilyEvent dataset.
> **Extractor:** `governance.family_cross_lead_lag_v2.cross_lead_lag_at`
> (lag fixed at 1 bar, **not** optimized)
> **Harness:** `scripts/run_feature_ab.py --feature-key cross_lead_lag`
> (purged walk-forward; also re-run on `--label magnitude` and
> `--stratify-by abs_feature`)
> **Verdict: NULL at 15m — no lift, no regime effect. The SPY→name lead is
> washed out at 15-minute granularity. Per the locked pre-registration and the
> standing "evidence before building" discipline, this null is the trigger to
> invest in tick-level infrastructure. `cross_lead_lag` stays recorded-only.**

---

## 1. The thesis under test

Single-name microstructure features were exhausted on both the direction and
magnitude axes (see `adr0019_magnitude_regime_ab_findings.md`). The next
hypothesis is **cross-instrument**: a liquid benchmark (SPY) leads individual
names by a short interval, so an asymmetric lag-1 cross-correlation ratio
`corr(r^B_{t-1}, r^C_t) / corr(r^C_{t-1}, r^B_t)` (>1 ⇒ benchmark leads) should
add resolution the single-instrument v1 score cannot see.

The design pass (`cross_asset_lead_lag_design.md`) deliberately **deferred** the
Hayashi-Yoshida tick-level estimator as "overkill at 15m, save for if/when tick
infrastructure exists" and locked a single-benchmark, fixed-lag-1, 15m A/B as
the first cheap test. This document reports that test.

## 2. Data

| Parameter | Value |
|-----------|-------|
| Source | Databento `XNAS.ITCH`, 15m bars |
| Symbols | AAPL, MSFT, NVDA, AMZN, TSLA |
| Benchmark | **SPY** (`XNAS.ITCH`, `ohlcv-1m` → 15m, OHLCV-only, no trades) |
| Window | 2026-02-02 → 2026-05-02 (3 months) |
| Events | 10,981 (BOS · FVG · OB · SWEEP) |
| Events file | `~/.local/share/skipp/vpin_followup/events_v2_spy.json` |
| `cross_lead_lag` coverage | **10,958 / 10,981 (99.8%)** |

> **Benchmark alignment note.** SPY was pulled on the same 15m regular-hours
> grid (3,997 bars). The adapter's `_benchmark_aligned` guard is strict
> (equal length **and** per-bar timestamp equality), and each symbol overlaps
> SPY at ~100% but for exactly **one** session-edge timestamp. That single
> missing bar per symbol was filled with a flat synthetic bar carrying the
> last-known SPY close stamped at the symbol timestamp — index-aligning the
> series without injecting signal (a flat bar degrades the lag-1 correlation to
> honest-None). One synthetic bar per symbol; 99.8% real coverage.

## 3. Results

All four passes returned a no-pass exit with **no** errors — genuine null, not a
harness failure.

### 3a. Direct input (plain A/B) — `families_lifted = []`, both axes

| Family | Direction Δ-res | Direction AUC | Magnitude Δ-res | Magnitude AUC |
|--------|----------------|---------------|-----------------|---------------|
| BOS | −0.0061 | ~0.48 | −0.0114 (regresses calibration) | 0.499 |
| FVG | −0.0054 | ~0.47 | −0.0030 | 0.455 |
| OB | −0.0008 | ~0.49 | −0.0041 | 0.511 |
| SWEEP | −0.0024 | ~0.48 | −0.0156 (regresses calibration) | **0.596** |

Resolution deltas are negative on both axes; candidate AUC is at or below 0.5
everywhere **except SWEEP on the magnitude axis (0.596)**. No family lifts; BOS
and SWEEP actively regress calibration on the magnitude axis.

### 3b. Regime gate (`--stratify-by abs_feature`) — no conditioning at all

| Family | n_oos | Direction regime | Magnitude regime |
|--------|-------|------------------|------------------|
| BOS | 2,375 | `no_regime_effect` | `no_regime_effect` |
| FVG | 1,985 | `no_regime_effect` | `no_regime_effect` |
| OB | 1,805 | `no_regime_effect` | `no_regime_effect` |
| SWEEP | 410 | `no_regime_effect` | `no_regime_effect` |

`families_conditioned = []` on both axes. Unlike the single-name microstructure
features — which at least conditioned the v1 score's resolution on `SWEEP` —
`cross_lead_lag` does **not** even work as a regime gate.

## 4. Interpretation

- **The cross-asset lead is washed out at 15m.** As a score input it subtracts
  resolution on every family; as a regime gate it conditions nothing.
- **But the lead is not absent — it is under-resolved.** The lone signal above
  random is **SWEEP magnitude AUC 0.596**: on the most impulsive family, the
  benchmark-leads ratio carries faint magnitude information. A 15m bar is simply
  too coarse to capture a lead that, if it exists, operates on a sub-minute
  scale. This is the predicted failure mode (`design §6`: "15m too coarse → lead
  washed out → null").
- **This null is informative, not merely negative.** A washed-out-but-nonzero
  SWEEP magnitude signal is exactly the evidence the design pass said would
  justify revisiting the deferred tick-level estimator.

## 5. Decision

| Item | Outcome |
|------|---------|
| `cross_lead_lag` as score input | **Rejected** — no lift, both axes; BOS/SWEEP regress calibration on magnitude |
| `cross_lead_lag` as regime gate | **Rejected** — `no_regime_effect`, all families, both axes |
| `cross_lead_lag` feature | **Stays RECORDED-ONLY** — not wired into v1 score or any gate |
| ADR-0021 pre-registered A/B | **Closed — NULL** |
| Tick-level (Hayashi-Yoshida) infrastructure | **Greenlit to build** — the 15m null + faint SWEEP-magnitude AUC is the pre-agreed trigger |

## 6. Lessons

- **A cheap coarse test before an expensive fine one is the right order.** The
  15m A/B cost one OHLCV-only SPY pull and answered whether the lead survives at
  bar granularity before committing to tick infrastructure. The null is worth
  more than the feature would have been.
- **Distinguish "absent" from "under-resolved."** A flat null across all axes
  *with* a single >0.5 AUC on the most impulsive family is not "no signal" — it
  is "signal below the sampling resolution," which points to *how* to look next
  (finer time scale) rather than *whether* to look at all.
- **Strict benchmark alignment is non-negotiable.** The adapter's length+timestamp
  guard silently drops an unaligned benchmark, which would have produced a false
  null (0% coverage). Verifying 99.8% coverage *before* trusting the A/B was the
  step that made the null credible.

## 7. Tick-level follow-up — shifted Hayashi-Yoshida (2026-06-05): also null → axis closed

The lone faint signal at 15 m (SWEEP magnitude AUC 0.596) triggered the
pre-registered escalation to tick resolution. We built a nanosecond `trades`
data layer (`scripts/pull_tick_trades.py`, `85f462a0`), a shifted
Hayashi-Yoshida lead-lag estimator that needs no resampling and so sidesteps the
Epps effect (`governance/family_cross_lead_lag_hy_v3.py`, `f40020c8`), and
threaded a recorded-only `cross_lead_lag_hy` shadow feature through the adapter
with point-in-time leak tests (`2db13864`). The pre-registration was frozen
**before** the run (scope doc §7, `58bbb1b4`).

**Data:** SPY benchmark + 5 constituents (AAPL, AMZN, MSFT, NVDA, TSLA), XNAS.ITCH
`trades`, 2026-02-02 → 2026-05-02, ~90 M ticks. The same 10,981 recorded
FamilyEvents as the v2 run were regenerated with constituent + SPY tick tapes
attached; **~95 % carried `cross_lead_lag_hy`** (per-window coverage 100 %, the
~5 % gap is degenerate single-tick windows that honestly return None). Headline
scalar = shifted-HY peak ratio `max_{θ>0}|HY| / max_{θ<0}|HY|`, trailing 1800 s
window, lag grid ±{2…60} s, all frozen.

**Result — null on every axis the v2 test used:**

| A/B | Verdict | Detail |
|-----|---------|--------|
| direction | `no_lift` ×4 | candidate AUC ≤ baseline on all families (BOS .499 vs .552, FVG .471 vs .536, OB .503 vs .532, SWEEP .437 vs .519); resolution delta negative throughout. |
| magnitude | `no_lift` ×4 | SWEEP — the one hope — *drags down* the score-alone AUC (0.565 vs 0.684) and **regresses calibration** (ECE .079 vs .064); BOS also regresses, FVG/OB flat. |
| stratify `abs_feature` (direction) | `no_regime_effect` ×4 | resolution spread ≤ 0.0017 across `|HY|` quantiles — the feature does not even *condition* the score. |
| stratify `abs_feature` (magnitude) | `no_regime_effect` ×4 | same: no family conditioned. |

**Verdict — pre-registered kill triggered.** HY also nulls: no lift, no regime
effect, and on the one family that flickered at 15 m it makes calibration
*worse*. Per the frozen kill criterion the **cross-asset lead-lag axis is closed**
for this thesis — we do **not** escalate to MBP-10 depth. The 15 m 0.596 was
sampling noise, not under-resolved signal: looking at the same relationship with
~100× finer time resolution and an Epps-robust estimator did not surface it.

- **Lesson — a pre-registered kill makes a negative result a clean stop.** The
  most elegant remaining version of the idea (async tick covariance, no Epps
  contamination) was the right thing to falsify it with: the null is now
  definitive rather than "maybe we didn't look hard enough."
- **Lesson — `recorded-only` shadow + purged A/B caught a feature that actively
  hurts.** Had `cross_lead_lag_hy` been wired to score on intuition, it would
  have *degraded* SWEEP magnitude calibration in production. The discipline gate,
  not judgement, is what kept it out.

The tick infrastructure (ns `trades` pull, the HY estimator, the adapter path)
remains in the tree as committed, reusable building blocks; only the cross-asset
*thesis* is closed.
