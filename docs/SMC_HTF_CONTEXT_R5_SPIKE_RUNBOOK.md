# SMC HTF Context R5 technical-spike runbook

Status: direct builder rejected; stateless fallback compiled and passed 12 of
15 registered cases; three temporal cases remain pending.

This runbook owns the decision that must precede any replacement of
`SMC_HTF_Confluence.pine`. The current root script remains a known snapshot-era
consumer and is not modified by this spike.

## Question under test

Can a compact stateless calculation layer provide fixed 15-minute, 1-hour, and
4-hour context without repaint, future leakage, memory failure, or an
unacceptable execution budget?

The first private compile answered the preceding direct-builder question:
`ctx.build_context_frame()` is not a legal `request.security()` expression
because its collection-backed builders have side effects (`CE10061`). The gate
therefore follows the pre-registered fallback decision and transports compact
primitive tuples calculated only from stateless series expressions. A first
object-transport fallback compiled but produced a chart runtime error and three
conditional-calculation warnings (`CW10003`); it is rejected in favor of four
fixed tuple request sites whose equal/lower-timeframe results are masked
unavailable.

## Correct confirmed-bar pattern

The original rollout plan required `lookahead_off`. That is insufficient for a
non-repainting realtime higher-timeframe value: an unoffset request can expose
the still-open HTF bar and change before its close.

The accepted candidate therefore combines:

- a one requested-context bar offset on every transported field; and
- `barmerge.lookahead_on`.

Together they publish the last closed HTF state at the start of the next HTF
interval. The test-only `lookahead_off` arm is disabled by default and exists
solely to observe the realtime divergence. It must never feed a product
decision.

This follows TradingView's current documentation for
[repainting requests](https://www.tradingview.com/pine-script-docs/concepts/repainting/)
and [other timeframes and data](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/).
The fixed tuple projection also follows the documented
[request and object memory limits](https://www.tradingview.com/pine-script-docs/writing/limitations/).

## Immutable inputs

- Fixture:
  `tests/fixtures/pine/smc_htf_context_r5_spike.pine`
- Case matrix:
  `artifacts/governance/smc_htf_context_r5_spike_manifest.json`
- Rejected direct library path:
  `preuss_steffen/smc_context_engine_private/4` (`CE10061`)
- Active implementation:
  compact stateless fixed-tuple HTF fallback
- Script name:
  `SMC HTF Context R5 Spike TEST ONLY`
- Private layout:
  `SMC HTF Context R5 Validation`
- Symbol:
  `NASDAQ:AAPL`
- Chart timeframes:
  `5m`, `15m`, `1h`, and `4h`
- Surface class:
  test-only, unmanaged, and not publishable

Always run `python scripts/smc_htf_context_r5_spike_manifest.py --check` before
transferring source. The manifest hash must match the transferred fixture.

## Private TradingView gate

Use a dedicated private layout and do not add the fixture to any managed
portfolio. Execute the 15 manifest cases in their registered modes:

1. compile the fixture;
2. verify confirmed 15m, 1h, and 4h publication from a 5m chart;
3. verify equal and lower requested frames fail closed on 15m, 1h, and 4h
   charts;
4. observe the raw comparison during a live, open 15m bar;
5. replay the five registered New York checkpoints around the independent US
   and European spring/autumn DST transitions;
6. replay the registered extended-hours checkpoint; and
7. capture the Pine Profiler, memory, runtime, request-site, and drawing-object
   evidence.

For each case, capture only the redacted Data Window values named in the
manifest. Do not record credentials, cookies, account internals, or unrelated
chart data.

## Decision rule

Accept the compact stateless fallback only if all of the following hold:

- the fixture compiles without the rejected `/4` request expression;
- all strict-HTF relationship and confirmed-boundary cases pass;
- the confirmed arm remains stable while the raw arm is allowed to vary;
- all US/EU DST and regular/extended-session checkpoints pass;
- no memory-limit or runtime-timeout error occurs; and
- the profiler evidence is recorded and accepted for the intended layout.

The direct-builder compile failure must remain recorded; it must not be hidden
by rewriting the result as a direct-path pass. If the fallback has any compile,
memory, timeout, or boundary-semantic failure, do not weaken the gate.

## Recorded private result on 2026-07-30

The redacted immutable evidence is
`artifacts/governance/smc_htf_context_r5_spike_tradingview_2026-07-30.json`.
The private fixture revision compiled, the saved-source readback matched SHA-256
`404c5380d1a8a58d80d36a282d6eb0e7da458810c1a33778d0a0e03849267b87`,
and 12 cases passed without a memory-limit or runtime-timeout error.

The successful cases cover confirmed 15m, 1h, and 4h publication, equal/lower
timeframe fail-closed behavior, the three historical spring US/EU DST
checkpoints, the extended-session checkpoint, and the Pine Profiler budget.
TradingView exposed relative execution-share percentages rather than an
independent absolute total runtime; the evidence records that limitation
instead of inventing an absolute value.

These cases remain open:

- `R5-HTF-08`: observe the diagnostic raw arm during a live open NASDAQ
  regular-session 15-minute bar;
- `R5-DST-04`: replay after the 2026-10-26 checkpoint exists; and
- `R5-DST-05`: replay after the 2026-11-02 checkpoint exists.

The private chart was restored to AAPL 5m, RTH, Europe/Berlin, replay off,
profiler off, fixture removed, panels closed, and `All changes saved`.

## Completion and rollback

The gate remains `partial` until immutable private runtime evidence records all
15 outcomes and the implementation decision. No result from source inspection
or Python tests can claim Pine compilation.

After the run, remove the fixture, restore the prior symbol, timeframe,
indicators, side panels, replay state, and saved script, then save the private
validation layout. No publication, alerts, Railway changes, or standard-layout
cutover are part of this gate.
