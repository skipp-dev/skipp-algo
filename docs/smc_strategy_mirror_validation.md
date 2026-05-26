# SMC strategy mirror — Pine-side validation procedure (#2353)

This procedure cross-validates the Python mirror under
[python/strategies/smc_mirror/](../python/strategies/smc_mirror/) (planned)
against its Pine v6 source on TradingView. **Run this whenever you
refresh `tests/fixtures/smc_strategy/<strategy>_expected_signals.csv`
with `scripts/regen_smc_strategy_fixtures.py --apply`**; otherwise the
test is pinning whatever the Python side currently emits, not actual
Pine parity.

## Why this is manual

TradingView Pine Script v6 strategies are not executable headlessly.
There is no Pine CLI, no Pine→Python compiler, and the TradingView
backtest engine is not open-source. Parity therefore has to be eyeballed
by the maintainer on the platform.

## Inputs

- `tests/fixtures/smc_strategy/<strategy>_input.csv` — the same 500-bar
  OHLCV slice the test consumes.
- `tests/fixtures/smc_strategy/<strategy>_expected_signals.csv` — the
  fixture you are about to commit.
- The corresponding Pine strategy file:
  - `long_strategy` → [SMC_Long_Strategy.pine](../SMC_Long_Strategy.pine)
  - (future) `short_strategy` → `SMC_Short_Strategy.pine`

## Procedure

1. **Pin the symbol and range.** Open TradingView, load the symbol and
   timeframe matched by `<strategy>_input.csv`'s `timestamp` column.
   Scroll to the first `bar_index` and set the chart's visible range to
   the last `bar_index`. The fixture's bar count must match the chart's
   bar count over that range — abort if not.
2. **Add the strategy.** Add `SMC_Long_Strategy.pine` to the chart with
   the exact same input parameters used by the Python mirror's default
   constructor. Document any deviation in the PR body — that is a
   parity bug, not a test artefact.
3. **Export Pine signals.** Use the strategy's Alert Log / List of
   Trades panel to export entries and exits. Translate each row into
   the fixture schema:
   - `bar_index` → match by `timestamp`.
   - `signal_type` → `LONG_ENTRY` / `LONG_EXIT` (and the short variants
     when that strategy lands).
   - `sl`, `tp` → the Pine-reported levels at fill time.
   - `confidence` → the strategy's published confidence at fill time
     (channel `STRAT_CONFIDENCE` on the BUS, if present).
4. **Diff against the candidate fixture.** Eyeball-compare against the
   newly generated `<strategy>_expected_signals.csv`. Any divergence
   means the Python mirror disagrees with Pine — fix the mirror, do not
   massage the fixture.
5. **Record the validation.** Add a line to the PR body of the form:

   > Pine-side validation: symbol `<sym>`, timeframe `<tf>`, bar range
   > `<first ts> .. <last ts>`, strategy version
   > `SMC_Long_Strategy.pine@<commit sha>`, 0 divergences.

## When to skip

- If you are only changing `tests/test_smc_strategy_snapshot.py` (the
  test harness) without touching the fixtures or the mirror, you do
  not have to re-run this. The skip-guard in the test will hold the
  contract.
- If the Python mirror itself does not exist yet (status as of
  2026-05-25), there is nothing to validate. The fixture file is a
  placeholder shape pinned by the schema check in
  `tests/fixtures/smc_strategy/README.md`.

## Audit trail

- Re-audit: [docs/reviews/external_pq_review_evaluation_2026-05-24.md](reviews/external_pq_review_evaluation_2026-05-24.md), Finding F4.
- Issue: #2353.
