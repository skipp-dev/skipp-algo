# Tick-Level Hayashi-Yoshida Lead-Lag — Build Scope

> **Status:** SCOPING (not yet building — pending go-ahead)
> **Date:** 2026-06-05
> **Trigger:** `adr0021_cross_asset_lead_lag_ab_findings.md` — the 15m
> cross-asset A/B returned NULL, with a single faint above-random signal
> (SWEEP magnitude AUC 0.596). Per the locked pre-registration in
> `cross_asset_lead_lag_design.md` (which explicitly deferred Hayashi-Yoshida
> as "overkill at 15m, save for if/when tick infrastructure exists"), that null
> is the agreed trigger to scope the tick-level estimator.
> **Thesis:** the SPY→name lead exists but operates below 15m resolution; an
> async, tick-native covariance estimator can recover it where bar sampling
> cannot.

---

## 1. Why tick-level, why Hayashi-Yoshida

At 15m the lead-lag ratio is washed out (no resolution lift, no regime effect).
Two facts motivate going finer rather than abandoning the axis:

1. **Epps effect.** Measured correlation between two assets collapses toward
   zero as the sampling interval shrinks *if* you naively resample to a common
   grid — but the *true* lead operates on the scale of seconds. A 15m bar
   integrates the lead away entirely.
2. **Async arrivals.** SPY and a single name do not print at the same instants.
   Any common-grid resampling (what the 15m test did) either fabricates
   synchronicity or discards the micro-timing that *is* the signal.

The **Hayashi-Yoshida (2005)** estimator is the canonical fix: it sums products
of overlapping return intervals across two asynchronous tick series **without
resampling**, giving an unbiased covariance under non-synchronous trading. The
lead-lag variant (Hoffmann-Rosenbaum-Yoshida 2013 / shifted HY) computes the
HY covariance over a grid of lags `θ` and takes the `argmax |HY(θ)|` as the
lead time, with the signed peak as the directional statistic.

## 2. What already exists (do not rebuild)

| Asset | Where | Reuse |
|-------|-------|-------|
| `trades` schema pull (price/size/side, ADR-0016) | `scripts/pull_databento_edge_input.py` (`_TRADES_SCHEMA`) | **Tick source.** Trades-only, no depth — far smaller than MBP-10. |
| Entitlement on `XNAS.ITCH` trades/mbp-10/mbo | probe 2026-06-04 (ADR-0020) | Confirmed entitled; no tier blocker. |
| `cross_lead_lag_at(bars, benchmark_bars, anchor_idx)` extractor | `governance/family_cross_lead_lag_v2.py` | Same feature shape; HY variant slots in beside it as a v3. |
| Adapter `benchmark_bars` plumbing + strict alignment guard | `governance/family_event_adapter.py` | Reuse the threading; HY needs a **tick** benchmark, not bar benchmark — new kwarg. |
| A/B harness + purged WF + regime stratification | `scripts/run_feature_ab.py`, `governance/family_feature_*` | Unchanged — HY feature is just another `--feature-key`. |
| Recorded FamilyEvent dataset + SPY pull recipe | `~/.local/share/skipp/vpin_followup/` | Same symbols/window; add tick pulls alongside. |

**Key reuse insight:** everything downstream of the extractor (adapter wiring,
recorded-only discipline, A/B machinery) is already proven by the 15m run. The
new work is confined to **(a) a tick data layer** and **(b) the HY estimator**.

## 3. Build surface (the actual new work)

### 3a. Tick data layer
- Pull `trades` for SPY + the 5 names over the **same window** (2026-02-02 →
  2026-05-02), `XNAS.ITCH`, regular hours.
- **Volume class:** `trades` is the *cheap* tick schema (price/size/side only,
  no order-book depth). Order-of-magnitude ~10⁵–10⁶ prints/symbol-day for liquid
  names; SPY is the heaviest. This is 2–3 orders of magnitude smaller than the
  MBP-10 1.38 M rec/sym-day depth problem — **storage is tractable**, no MBP-10
  engineering gate applies.
- Store as nanosecond-timestamped `(ts, price)` series per symbol. Returns are
  log-returns between consecutive prints. **No resampling** — that is the whole
  point.

### 3b. HY estimator (`governance/family_cross_lead_lag_hy_v3.py`)
- `cross_lead_lag_hy_at(tick_series_c, tick_series_b, anchor_ts, *, window_s, lag_grid_s)`.
- Compute shifted-HY covariance over a trailing PIT window
  `[anchor_ts - window_s, anchor_ts]` only (leak-safe: never reads past the
  anchor).
- Sweep `lag_grid_s` (e.g. ±0…±60 s in 1–5 s steps); statistic = signed peak
  `argmax_θ |HY(θ)|` normalized by the zero-lag HY (a unitless lead ratio
  comparable to the v2 bar feature).
- **Honest-None** when: fewer than N prints in window, degenerate (zero)
  variance, anchor outside series, or unaligned clocks.

### 3c. Adapter threading
- New kwarg `benchmark_ticks=None` (distinct from `benchmark_bars`) so bar-level
  and tick-level features coexist. Backcompat: default `None` ⇒ feature absent.
- PIT discipline is the **highest-risk** part: the adapter today aligns by bar
  index; tick alignment is by **timestamp ≤ anchor**. Needs a dedicated,
  test-covered "ticks strictly before anchor" slice to prevent the classic
  async-lead leak the design doc warned about.

## 4. Pre-registration (to lock before building the A/B)

- **Feature key:** `cross_lead_lag_hy`.
- **Lag grid fixed** (e.g. ±60 s / 5 s steps) — `argmax` is over θ but the grid
  itself is pre-registered, **not** tuned to the outcome.
- **Window fixed** (e.g. trailing 30 min of ticks).
- Run on **same** recorded FamilyEvents, purged walk-forward, same
  MIN_OOS_SAMPLES, no-regression on Brier/ECE/coverage.
- **Pass:** lifts OOS resolution on ≥1 family without regressing others — the
  identical bar to the v2 test. RECORDED-ONLY first.
- **Pre-registered kill:** if HY *also* nulls (no lift, no regime effect), the
  cross-asset axis is closed for good and we do **not** escalate to MBP-10 depth
  for this thesis.

## 5. Effort & risk

| Dimension | Estimate / note |
|-----------|-----------------|
| Tick data layer | Moderate — reuses `trades` pull; new nanosecond store + PIT slice |
| HY estimator + tests | Moderate-high — async covariance math is subtle; needs property tests vs a known-lead synthetic |
| Adapter threading | Low-moderate — mirrors `benchmark_bars`, but tick PIT slice is the leak-risk hotspot |
| Data cost | Trivial $ (trades schema); tractable volume (≪ MBP-10) |
| Biggest risk | **Leakage** via tick/anchor time-alignment — must be test-gated before any A/B is trusted |
| Second risk | HY *also* nulls → axis closed (acceptable: a definitive negative on the most elegant remaining axis) |

## 6. Recommended sequencing

1. **Tick data layer first** — pull `trades` for SPY + 5 names, build the
   nanosecond PIT-sliced store, verify coverage on the existing event anchors.
   (Cheap, reversible, de-risks the data question before any math.)
2. **HY estimator + synthetic property tests** — validate the estimator
   recovers a *known* injected lead on synthetic async series before touching
   real data.
3. **Adapter threading + leak tests** — `benchmark_ticks` kwarg, strict
   "ticks-before-anchor" slice, regenerate events recorded-only.
4. **Lock pre-registration, run the A/B** — same harness, same families.
5. **Verdict** — promote to recorded→score only on a clean resolution lift;
   otherwise close the cross-asset axis.

**Open decision for the user:** approve starting at step 1 (tick data layer), or
review/adjust the pre-registration (lag grid, window, kill criterion) first.

## 7. Locked pre-registration (step 4 — frozen 2026-06-05)

Steps 1–3 are complete and committed (ns tick pull `85f462a0`, HY estimator
`f40020c8`, adapter threading + leak tests `2db13864`). The following is frozen
**before** the A/B is run; the parameters below match the committed estimator
(`governance/family_cross_lead_lag_hy_v3.py`) exactly and are **not** revisited
after seeing any result.

- **Feature key:** `cross_lead_lag_hy` (recorded-only shadow; does **not** feed
  any gate).
- **Headline scalar:** shifted-Hayashi-Yoshida peak ratio
  `max_{θ>0}|HY(θ)| / max_{θ<0}|HY(θ)|` — `> 1` ⇒ benchmark (SPY) leads the
  constituent; `< 1` ⇒ constituent leads.
- **Window (frozen):** trailing **1800 s** of ticks, `[anchor − 1800 s, anchor]`,
  nanosecond-exact, ending strictly at the event anchor (PIT slice).
- **Lag grid (frozen):** θ ∈ ±{2, 4, …, 60} s (step 2 s, 30 magnitudes). `argmax`
  is taken over θ but the **grid is pre-registered**, not tuned to the outcome.
- **Benchmark:** SPY trades tape. **Constituents:** AAPL, AMZN, MSFT, NVDA, TSLA
  (and SPY-vs-SPY is excluded — no self lead-lag).
- **Events:** the *same* recorded `FamilyEvent`s as the v2 cross-asset run,
  regenerated from the identical 6 symbol bar payloads with constituent + SPY
  benchmark ticks attached via the step-3 adapter path.
- **Test:** `scripts/run_feature_ab.py … --feature-key cross_lead_lag_hy`, purged
  walk-forward, same `MIN_OOS_SAMPLES` as v2, no-regression on Brier / ECE /
  coverage. Magnitude-labelled and `--stratify-by abs_feature` passes included,
  with **special attention to SWEEP magnitude** (the lone faint signal at 15 m,
  AUC 0.596).
- **Pass:** lifts OOS Brier resolution on **≥ 1 family** without regressing the
  others — the identical bar the v2 test had to clear. Promotion is
  recorded → score only on a clean lift.
- **Pre-registered kill:** if HY **also** nulls (no lift, no regime effect), the
  cross-asset axis is **closed for good** for this thesis and we do **not**
  escalate to MBP-10 depth.
