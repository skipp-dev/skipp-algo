# Cross-source volume decision contract

This contract separates three questions that the former single “parity” number
mixed together.

## 1. Engine parity

`scripts/report_a0_parity.py` replays the shared provider-neutral A0 threshold
contract for every recorded FMP and Databento snapshot. Its
`engine_parity.parity_rate` answers only:

> Did each producer apply the shared decision rule correctly to the snapshot it
> received?

The release expectation is `1.0`. Missing replay fields are reported as
`unverifiable`; they are never counted as matches.

## 2. Source equivalence

The same report places the cross-provider comparison under
`source_equivalence`. It retains decision matches, timing and both raw
snapshots, and now attributes material feature deltas to price, previous close,
change percentage, normalized volume pace, expected-volume fraction or
observation timing.

This is the cutover question:

> Do the two market-data sources produce equivalent A0 behaviour, even when
> both engines are correct?

Engine parity must not be used as a substitute for source equivalence, and a
price-only gate must not promote a producer whose live decision still consumes
volume.

## 3. FMP denominator and F3 measurement

The published realtime watchlist carries:

- `avg_volume_15_session`
- `avg_volume_15_session_as_of`
- `avg_volume_15_session_source`

These values are built from exactly 15 completed FMP EOD sessions. Presence is
authoritative. An explicit null is fail-closed and never falls back to profile
`averageVolume` with an undocumented lookback.

The post-close outcome workflow runs `scripts/measure_fmp_volume_basis.py` for
up to 20 current candidates. It stores one immutable artifact per session under
`artifacts/open_prep/volume_source_audit/` and compares, for the same symbol and
session:

- `/stable/quote` cumulative volume,
- the sum of `/stable/historical-chart/1min`,
- `/stable/historical-price-eod/full` volume.

`latest_summary.json` remains `accumulating_evidence` until at least five
sessions exist. It then emits one of:

- `basis_compatible`
- `confirmed_basis_mismatch`
- `inconclusive`

## Provider decision after evidence

No provider is promoted automatically. Apply this order after the five-session
F3 minimum and the corresponding source-equivalence reports are available:

1. If FMP quote volume matches FMP minute aggregation but EOD volume differs by
   more than 10%, replace the FMP ADV with a 15-session average computed from
   that same minute aggregation before evaluating Databento cutover.
2. Re-run source equivalence with aligned 15-session windows. Engine parity
   must remain `1.0`.
3. If normalized-volume-pace deltas still exceed 10% materially and continue to
   change A0 decisions, treat venue coverage as non-equivalent. Prefer a
   consolidated Databento dataset compatible with the production decision
   semantics.
4. Use source-specific symbol × minute-of-day percentiles only if a compatible
   consolidated source is unavailable or rejected on a separately recorded
   cost/coverage decision. Percentile normalization is a strategy change, not a
   transport fix; it requires threshold recalibration, at least 20 shadow
   sessions and a new explicit promotion approval.

Current default while evidence accumulates: keep FMP active, keep Databento in
shadow, and do not weaken the source-equivalence gate.
