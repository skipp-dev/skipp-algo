# SMC Context BUS R4 Shadow Runbook

This runbook covers the private, non-gating rollout of `SMC Context Bus`
(schema `8001`) and `SMC Context Overlay`. It does not authorize a public Pine
publication or any trade-gating change.

The canonical channel order and budget live in
`artifacts/governance/smc_context_bus_v3_manifest.json`. The producer exports
60 direct `CTX ` channels and reserves four TradingView plot slots. The overlay
must bind all 60 channels to the one producer instance in the same chart pane.

## Required order

1. Confirm the repository commit and normalized source hashes.
2. Open the private shadow layout and set its exact URL in `TV_CHART_URL`.
3. Run the R4 preflight. It creates or updates the two exact private Saved
   Scripts, compiles them, adds them to the chart, and verifies the overlay
   exposes the complete 60-label contract.
4. Bind and verify all `CTX ` inputs with the producer named
   `SMC Context Bus`.
5. Save the layout only after readback reports 60/60 exact bindings and no
   unknown-parent runtime error.
6. Record execution time, visible object counts, source hashes, binding
   readback, Suite/Breakout parity observations, and rollback evidence.

## Commands

The URL must identify the private shadow layout; do not use the generic
`https://www.tradingview.com/chart/` route.

```bash
export TV_CHART_URL='https://www.tradingview.com/chart/<shadow-layout-id>/'
TV_PERSISTENT_PROFILE_DIR=automation/tradingview/auth/chromium-profile \
  npx tsx scripts/tv_preflight.ts \
  --config automation/tradingview/preflight-r4-context-shadow.json
```

After the producer and overlay compile and are both present on that layout:

```bash
TV_PERSISTENT_PROFILE_DIR=automation/tradingview/auth/chromium-profile \
  npx tsx scripts/tv_verify_consumer_bindings.ts \
  --source SMC_Context_Overlay.pine \
  --saved-script-name 'SMC Context Overlay' \
  --script-name 'SMC Context Overlay' \
  --producer-name 'SMC Context Bus' \
  --force-rebind
```

Run the same verifier without `--force-rebind` for the final read-only
selection check. The mutating run is not complete until the layout has been
saved and reloaded and the readback still reports 60/60.

## Fail-closed conditions

Stop without promotion when any of these is true:

- schema is not exactly `8001`;
- producer or consumer source hash differs from the reviewed repository commit;
- fewer than 60 bindings are visible or any selection is not
  `SMC Context Bus: CTX <Channel>`;
- producer age is unavailable or stale on a live bar;
- price bounds are inverted;
- TradingView reports an unknown parent, compile error, or execution timeout;
- Engine BUS v2 changed or gained a `CTX ` channel;
- Context results alter a Suite decision or alert; or
- structure/zone discrepancies against Suite and Breakout evidence are
  unexplained.

## Rollback

Remove `SMC Context Overlay` and `SMC Context Bus` from the shadow layout and
save it. Do not modify Engine BUS v2, Suite, Dashboard, Strategy, alerts, or
their layouts. Verify those existing surfaces remain unchanged.
