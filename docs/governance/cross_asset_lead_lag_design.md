# Design pass: cross-asset lead-lag feature

| Field    | Value                                                          |
|----------|---------------------------------------------------------------|
| Status   | Design pass — exploration, NOT implementation                 |
| Date     | 2026-06-05                                                    |
| Author   | skipp-dev (autonomous mandate; product owner + principal quant) |
| Related  | ADR-0019 (multi-feature family score v2), [ADR-0020](../adr/0020-options-flow-datapath.md) §cross-asset, [saturation verdict](feature_onramp_saturation_verdict.md), [VPIN findings](adr0019_vpin_ab_findings.md) |

## Why this note exists

ADR-0020 ranked cross-asset lead-lag as the #3 axis after options flow and L2
depth, explicitly deferring it with: *"Conceptually the most elegant 'new axis'
but the most greenfield plumbing and the highest leakage risk."* With the OHLCV
microstructure axis now comprehensively exhausted (saturation verdict) and VPIN
the last candidate to null, this design pass explores **what a correct, leak-safe
implementation would look like** — the cost, the architecture, and the open
questions — so the team can decide whether to build it.

**This is a design-only note. No code, no branch, no PR.**

---

## 1. The thesis

Cross-asset lead-lag is the idea that price moves in a broad index or sector ETF
(SPY, QQQ, or ES futures) *lead* moves in individual constituents by seconds to
minutes — the "information cascade" or "common-factor price discovery" effect.
For SMC event families:

- A BOS/SWEEP in SPY preceding a BOS/SWEEP in AAPL is a *stronger* signal than
  a standalone AAPL event.
- The lag structure itself (how quickly the constituent responds) is informative
  about the event's probability of resolution.

This is a genuinely **orthogonal axis**: the v1 score is pure single-instrument
geometry; all tested microstructure features (`ofi`, `kyle_lambda`, `vpin`,
`relative_volume`, `average_trade_size`, `signed_uoa_notional`) are also
single-instrument. A cross-asset feature would be the first to look *outside* the
instrument's own bar series.

## 2. The bottleneck: `f(bars, anchor_idx)` is single-instrument by design

Every v2 extractor follows the pattern:

```python
def feature_at(bars: Sequence[Mapping], anchor_idx: int, *, period: int) -> float | None
```

The adapter (`family_event_adapter.py`) calls each extractor with the
instrument's own bars and the anchor index. There is **no second-instrument
parameter** in the function signature, and the adapter has no second-instrument
data path.

### 2.1 Why this was a deliberate design choice

- **Point-in-time safety:** With one instrument, the trailing window
  `[anchor_idx - period + 1, anchor_idx]` is trivially PIT — no future bar is
  ever accessed. With two asynchronous instruments, the "same time" concept is
  leaky: the benchmark instrument's bar that is "current at anchor time" may
  carry information that arrived microseconds *after* the anchor.
- **Honest-None:** If the second instrument's bars are missing for a window,
  the feature must return `None` — never fabricate or fill. With synchronous
  bars from the same source this is straightforward; with a separate data pull
  it needs explicit alignment validation.

## 3. Proposed architecture

### 3.1 Data path — SPY/ES as the benchmark instrument

**Choice: SPY (equity ETF) over ES (futures).** Rationale:

- Already available on Databento `XNAS.ITCH` (same dataset as constituent
  equities) — no new dataset subscription.
- Same market hours, same exchange calendar, no roll adjustment needed.
- The 15m OHLCV bars align directly with the constituent's bars (same
  timestamps) — eliminates the async alignment problem for bar-level features.
- ES futures would need `GLBX.MDP3` (CME), different hours (nearly 24h),
  roll-adjustment, and explicit timezone alignment — strictly more engineering
  for the same economic thesis.

**Pull modification:** `pull_databento_edge_input.py` adds a `--benchmark SPY`
flag. When set, pulls SPY bars alongside the constituent and embeds them as a
`benchmark_bars` key in the pipeline payload:

```python
{
    "symbol": "AAPL",
    "bars": [...],              # AAPL 15m bars (existing)
    "benchmark_bars": [...],    # SPY 15m bars (new)
    "structure": {...},
    ...
}
```

Cost: one additional symbol-pull per run (~800 extra bars per 3-month window).
Databento cost is negligible (SPY OHLCV is the same tier).

### 3.2 Extractor — `cross_lead_lag_at`

```python
def cross_lead_lag_at(
    bars: Sequence[Mapping],
    benchmark_bars: Sequence[Mapping],
    anchor_idx: int,
    *,
    period: int = ATR_PERIOD,
) -> float | None:
```

**Signature change:** this is the *only* extractor that takes a second
positional argument. All existing extractors keep `f(bars, anchor_idx)`.

**Algorithm options (ranked by complexity):**

| Method | Complexity | PIT-safe? | Sensitivity | Notes |
|--------|-----------|-----------|-------------|-------|
| **Rolling return correlation** | Low | Yes (trailing window only) | Low — measures co-movement, not lead | Baseline sanity check, not the feature |
| **Asymmetric cross-correlation at lag ±k** | Medium | Yes if k>0 only measures `benchmark[t-k]` vs `constituent[t]` | Medium | Hay-Johnson (2002). The ratio `corr(B_{t-1}, C_t) / corr(C_{t-1}, B_t)` is a clean lead-lag statistic |
| **Hayashi-Yoshida covariance estimator** | High | Yes, but needs tick-level timestamps | High — handles async arrivals | Canonical for tick-level lead-lag. Overkill at 15m bar level |

**Recommended: asymmetric cross-correlation.** At 15m bar resolution, bars are
synchronous (same exchange timestamps), so the Hayashi-Yoshida estimator's
async-handling adds complexity without benefit. The simple lag-1 cross-correlation
ratio is:

$$\text{lead\_lag} = \frac{\text{corr}(r^B_{t-k}, r^C_t)}{\text{corr}(r^C_{t-k}, r^B_t)}$$

where $r^B$ = benchmark returns, $r^C$ = constituent returns, computed over
the trailing PIT window `[anchor_idx - period + 1, anchor_idx]`. Ratio > 1
means benchmark leads; ratio < 1 means constituent leads.

**Honest-None conditions:**

- `period < 3` (need ≥2 data points for correlation)
- Benchmark bars missing or misaligned at any point in the window
- Zero-variance in either return series (denominator undefined)
- Any bar in the window lacks `close` or `timestamp`

**Point-in-time guarantee:** The trailing window uses only bars at or before
`anchor_idx`. The benchmark bar at `anchor_idx` is the SPY bar whose
timestamp matches the constituent's anchor bar — since both are 15m bars from
the same exchange, the benchmark bar's close is known at the same time as the
constituent's.

### 3.3 Adapter wiring

Two adapter sites (`_zone_event_to_family`, `_level_event_to_family`) need:

```python
# New: pass benchmark_bars through the adapter
if benchmark_bars is not None:
    lead_lag = cross_lead_lag_at(bars, benchmark_bars, anchor_idx)
    if lead_lag is not None:
        mapped["cross_lead_lag"] = lead_lag
```

**`family_events_from_structure` signature change:**

```python
def family_events_from_structure(
    structure: Mapping[str, Any],
    bars: Sequence[Mapping[str, Any]],
    *,
    benchmark_bars: Sequence[Mapping[str, Any]] | None = None,  # NEW
) -> list[FamilyEvent]:
```

The `benchmark_bars=None` default preserves backward compatibility. All existing
callers pass only `structure` and `bars` and get the same behaviour. Only the
new `--benchmark` data path passes the second series.

### 3.4 Alignment validation

The critical leak-safety check: verify that benchmark bars and constituent bars
share identical timestamps at every index. This is a **hard pre-condition**
checked once at the top of `family_events_from_structure`:

```python
if benchmark_bars is not None:
    assert len(benchmark_bars) == len(bars), "benchmark/constituent bar count mismatch"
    for i, (b, bm) in enumerate(zip(bars, benchmark_bars)):
        assert b["timestamp"] == bm["timestamp"], f"timestamp mismatch at bar {i}"
```

If alignment fails, `benchmark_bars` is set to `None` and the feature degrades
to `honest-None` everywhere — never silently misaligned.

## 4. Leakage risk analysis

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Benchmark bar look-ahead** — SPY bar at `t` includes information after constituent's anchor | HIGH | Mitigated by design: same exchange, same 15m grid, same close time. Bar-level alignment is exact, not approximate |
| **Intra-bar timing** — SPY may incorporate news faster than AAPL within the same 15m bar | MEDIUM | Irrelevant at bar level — both bars integrate the full 15m period. Would matter at tick level only |
| **Survivorship bias** — SPY always exists, constituent may delist | LOW | Not applicable for the 3-month windows used in A/B testing |
| **Weekend/holiday misalignment** — different holiday calendars | LOW | SPY and US equities share the NYSE calendar. No gap |
| **Backfill leak** — Databento may adjust older bars | VERY LOW | Same risk as constituent bars; not specific to cross-asset |

**Net assessment: leakage risk is LOW at bar-level resolution with SPY.** The
ADR-0020 "highest leakage risk" characterisation was about tick-level async
alignment (Hayashi-Yoshida territory). At 15m synchronous bars, the alignment
problem is trivially solved.

## 5. Implementation effort estimate

| Component | Effort | Notes |
|-----------|--------|-------|
| `pull_databento_edge_input.py --benchmark SPY` | Small | One extra `fetch_ohlcv_frame` call, embed in payload |
| `governance/family_cross_lead_lag_v2.py` extractor | Small | ~60 lines, same pattern as `vpin_at` |
| Adapter wiring (`family_event_adapter.py`) | Small | 3 lines × 2 sites + 1 kwarg |
| Alignment validation | Small | 5-line assertion block |
| Tests | Medium | PIT-safety, honest-None paths, poisoned-future-bars, alignment failure |
| A/B run | Zero (code) | Reuse `run_feature_ab.py` with `--feature cross_lead_lag` |
| **Total** | **~1 day** | Assuming existing patterns; no new infrastructure |

## 6. What we DON'T know yet

1. **Does the thesis hold at 15m resolution?** Lead-lag effects are strongest at
   the microsecond-to-second scale. At 15m, the lead may have already propagated
   and washed out. This is the biggest risk: the feature may be correctly
   implemented, correctly leak-safe, and correctly measured — and still null.

2. **Is SPY the right benchmark?** For tech-heavy names (AAPL, MSFT, NVDA), QQQ
   may be a better benchmark than SPY. For sector-specific names, sector ETFs
   (XLF, XLE) may work better. But testing multiple benchmarks risks
   multiple-comparison inflation. Start with SPY; consider QQQ as a pre-registered
   robustness check.

3. **Lag horizon.** Lag-1 (15 minutes) is the natural starting point, but lag-2
   or lag-3 may carry more signal for slower-moving names. The period parameter
   already controls the correlation window length; the lag parameter could be
   exposed as well but risks overfitting.

4. **Event-type specificity.** A SWEEP in SPY preceding a SWEEP in AAPL is a
   different thesis than "SPY return correlation leads AAPL return correlation."
   The former needs cross-instrument *structure* detection (detecting SPY sweeps
   and checking temporal proximity to AAPL sweeps), which is a much larger
   engineering lift than return-correlation lead-lag.

## 7. Verdict

**Worth building — second priority, ahead of L2 depth.** ADR-0020 flagged
cross-asset lead-lag as "highest leakage risk," but that characterisation
assumed tick-level async alignment (Hayashi-Yoshida territory). At 15m
synchronous exchange bars the alignment problem is trivially solved and the
leakage risk drops to LOW (§4). Implementation is ~1 day on existing patterns
(§5), the thesis is genuinely orthogonal to everything tested so far, and the
data is already available (SPY on `XNAS.ITCH`, same subscription). By contrast,
L2 depth (MBP-10) is a ~1.7 B row engineering project with no new thesis — just
finer-grained versions of the same microstructure features that already nulled
at trade level. Lead-lag should run first; L2 only if lead-lag also nulls and
the team decides the 15m-coarseness risk (§6.1) warrants tick-level infra.

The main risk is that 15m bars are too coarse to capture lead-lag — which is
itself a valuable negative result that would redirect toward tick-level
infrastructure (Hayashi-Yoshida).

### Pre-conditions before coding

- [x] VPIN PR #2573 merged (clears the branch queue) — merged to `main`
- [x] SPY OHLCV data verified available on `XNAS.ITCH` at the same
      date range as the constituent pulls — same subscription as §3.1
- [x] A/B harness confirmed to handle the lead-lag flag — `scripts/run_feature_ab.py`
      is generic on `--feature-key`, so it reads the `cross_lead_lag` event-dict key
      with no registry change
- [x] Pre-register the pass criterion: same purged walk-forward protocol,
      same MIN_OOS_SAMPLES, same no-regression guards as all ADR-0019 candidates
      — see "Pre-registration (LOCKED)" below

### Pre-registration (LOCKED 2026-06-05)

This pass criterion is fixed **before** any A/B is run, exactly as for every
ADR-0019 candidate. No post-hoc tuning of the protocol, the lag, or the
threshold is permitted.

- **Feature key:** `cross_lead_lag` (the event-dict key emitted recorded-only by
  `governance.family_event_adapter.family_events_from_structure` when an
  index-aligned `benchmark_bars` series is supplied).
- **Extractor:** `governance.family_cross_lead_lag_v2.cross_lead_lag_at` — lag-1
  asymmetric cross-correlation ratio over the trailing `ATR_PERIOD` window. Lag is
  **fixed at one bar and is NOT optimized.**
- **Run command:**

  ```bash
  python scripts/run_feature_ab.py <events.jsonl> --feature-key cross_lead_lag
  ```

- **Protocol:** the same purged, embargoed walk-forward used for all ADR-0019
  candidates — identical folds, identical `MIN_OOS_SAMPLES` floor, identical
  no-regression guards. A fold that falls below `MIN_OOS_SAMPLES` is dropped, not
  back-filled.
- **Pass criterion:** the candidate must lift out-of-sample resolution
  (Brier / log-loss) on **at least one** event family **without regressing** any
  other family beyond the no-regression tolerance, with the `MIN_OOS_SAMPLES`
  floor satisfied on every scored fold.
- **Status:** RECORDED-ONLY. The feature rides alongside event outcomes; it is
  **NOT** wired into the v1 score or any gate. Wiring is considered only if this
  pre-registered A/B passes.

### What NOT to build

- ❌ Hayashi-Yoshida tick-level estimator (overkill at 15m, save for if/when
  tick infrastructure exists)
- ❌ Cross-instrument structure detection (SPY sweep → AAPL sweep matching) —
  separate ADR if ever pursued
- ❌ Multiple benchmark regression (SPY + QQQ + sector ETF) — overfitting risk,
  single benchmark first
- ❌ Dynamic lag selection — fix lag-1, do not optimize
