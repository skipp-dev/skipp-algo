# SMC HTF Context R5 technical-spike runbook

Status: repository contract implemented; private TradingView runtime gate pending.

This runbook owns the decision that must precede any replacement of
`SMC_HTF_Confluence.pine`. The current root script remains a known snapshot-era
consumer and is not modified by this spike.

## Question under test

Can the published private Context Engine `/4` execute its stateful
`ContextFrame` builder safely inside `request.security()` for fixed 15-minute,
1-hour, and 4-hour contexts without repaint, future leakage, memory failure, or
an unacceptable execution budget?

The fixture transports a compact primitive `HtfSnapshot`, not the complete
nested object. The canonical `ctx.build_context_frame()` still executes inside
each requested context. This separates the semantic question from the known
memory cost of copying large objects on every chart bar.

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
The compact projection also follows the documented
[request and object memory limits](https://www.tradingview.com/pine-script-docs/writing/limitations/).

## Immutable inputs

- Fixture:
  `tests/fixtures/pine/smc_htf_context_r5_spike.pine`
- Case matrix:
  `artifacts/governance/smc_htf_context_r5_spike_manifest.json`
- Library:
  `preuss_steffen/smc_context_engine_private/4`
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

Choose the direct stateful implementation only if all of the following hold:

- the fixture compiles against the published `/4` library;
- all strict-HTF relationship and confirmed-boundary cases pass;
- the confirmed arm remains stable while the raw arm is allowed to vary;
- all US/EU DST and regular/extended-session checkpoints pass;
- no memory-limit or runtime-timeout error occurs; and
- the profiler evidence is recorded and accepted for the intended layout.

If any compile, memory, timeout, or boundary-semantic case fails, do not weaken
the gate. Build a dedicated compact stateless HTF calculation layer and replay
the same matrix against it.

## Completion and rollback

The gate remains `partial` until immutable private runtime evidence records all
15 outcomes and the implementation decision. No result from source inspection
or Python tests can claim Pine compilation.

After the run, remove the fixture, restore the prior symbol, timeframe,
indicators, side panels, replay state, and saved script, then save the private
validation layout. No publication, alerts, Railway changes, or standard-layout
cutover are part of this gate.
