# SMC R5 HTF and session rebuild runbook

This runbook validates the rebuilt private companions without turning a
repository implementation into a deployment claim.

## Scope

The two product roots are:

- `SMC_HTF_Confluence.pine`
- `SMC_Session_Context.pine`

Their snapshot-era predecessors remain available only as rollback references:

- `pine/legacy/SMC_HTF_Confluence_v1_snapshot.pine`
- `pine/legacy/SMC_Session_Context_v1_snapshot.pine`

The execution contract is generated at
`artifacts/governance/smc_r5_htf_session_rebuild_manifest.json`.

Regenerate it after every source change:

```bash
python scripts/smc_r5_htf_session_rebuild_manifest.py
```

The checked-in source hashes and all cases must match before a private browser
run starts.

## Safety boundaries

- Use TradingView account `preuss_steffen`.
- Use private layout `SMC HTF Context R5 Validation`.
- Use `NASDAQ:AAPL`.
- Do not publish either script.
- Do not create alerts.
- Do not change Railway.
- Do not end another TradingView session.
- Capture rendered chart and Data Window diagnostics only.
- Restore and save the prior chart state after the run.

The preflight config is
`automation/tradingview/preflight-r5-htf-session.json`. Its Product Cut scope
may create a fresh private draft when the saved script is absent and may add
the validated script to the private chart. It does not authorize publication.

## What the implementation proves locally

HTF Confluence has three fixed request sites. Each transports primitive,
stateless values from source index `[1]` using
`barmerge.lookahead_on`. A requested timeframe is available only when it is
strictly higher than the chart timeframe, its transported bar is confirmed,
and its required history is present. Aggregate confluence requires all three
frames; partial input fails closed.

Session Context has no `request.security` call. Asia, London, NY AM, and NY PM
are evaluated in `Asia/Tokyo`, `Europe/London`, and `America/New_York`.
TradingView therefore applies European and US daylight-saving changes
independently. Session state, range, volume, VWAP, opening range, MSS, bias,
and score advance only on confirmed chart bars.

These code properties are guarded by
`tests/test_smc_r5_htf_session_rebuild.py`. They do not replace TradingView
compile and replay evidence.

## Private execution

1. Record the current chart symbol, timeframe, layout, and attached scripts.
2. Confirm that the manifest source hashes match the two local roots.
3. Save and compile `SMC HTF Confluence` privately.
4. Save and compile `SMC Session Context` privately.
5. Execute every manifest case at its specified chart timeframe or UTC
   checkpoint.
6. Record only the expected rendered diagnostics and any redacted compile or
   runtime error.
7. Verify that HTF source-close values advance only on the matching closed HTF
   boundary and remain stable inside an open source bar.
8. Verify that equal/lower requested frames and incomplete history report
   unavailable rather than reusing chart-timeframe or snapshot data.
9. Verify the EU/US autumn DST checkpoints and extended-session outside state.
10. Restore the exact prior chart state, save the layout, and verify it after a
    reload.

## Exit gate

`R5-REBUILD` remains `partial` until a separate immutable evidence artifact
records:

- both exact source SHA-256 values;
- successful private compile for both saved scripts —
  **done 2026-07-31**, `smc_r5_htf_session_rebuild_preflight_green_2026-07-31.json`
  (every preflight axis true for both targets, runtime smoke included);
- all 11 manifest cases;
- layout identity and chart state;
- zero unredacted secret or editor-source capture;
- rollback and reload verification; and
- the decision whether either companion enters the optional Pro HTF layout.

Only then may traceability move to `complete` and Product Cut rollout state be
considered for a separate deployment change.
