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
- rollback and reload verification — **done 2026-07-31**,
  `smc_r5_htf_session_rebuild_rollback_2026-07-31.json` (perturbation took, the
  in-session restore matched, the layout was saved, and the state survived a
  reload); and
- the decision whether either companion enters the optional Pro HTF layout —
  **decided 2026-07-31**, see below.

Only then may traceability move to `complete` and Product Cut rollout state be
considered for a separate deployment change.

## Pro HTF preset decision (2026-07-31)

**`SMC HTF Confluence` enters the Pro HTF preset. `SMC Session Context` does
not.** Both keep `rollout_state = not_deployed`; preset membership and
deployment are separate steps, and this decision only settles the first.

### Why HTF Confluence is in

The architecture already designated it — §15.1 lists "Pro HTF: Pro Context plus
HTF Confluence" and phase R8 names "rebuilt HTF Confluence for the Pro HTF
layout". What was missing was the evidence, and
`SMC_Chart_Combinations.md` named the exact condition: the rebuilt roots stay
`not_deployed` "bis zum privaten Compile-, Replay-, Hash- und
Rollback-Nachweis". All four now exist:

| Nachweis | Beleg |
| --- | --- |
| Compile | `…preflight_green_2026-07-31.json` — every axis true, both targets |
| Replay | `…replay_`, `…extended_`, `…availability_`, `…live_no_repaint_` |
| Hash | manifest `sources.*.sha256`, re-verified by the rollback drill |
| Rollback | `…rollback_2026-07-31.json` |

Nothing else in Pro Context supplies multi-frame HTF confluence: Context BUS and
Context Overlay carry session, structure and zone context, not a 15m/1h/4h
trend, ATR-ratio, squeeze and divergence roll-up.

### Why Session Context is out

§15.2 recommended putting session and killzone in Context Overlay and Dashboard
by default, and keeping a separate compact Session script **only if** mobile or
layout tests show a distinct user need. Both halves were checked rather than
assumed:

- **The recommendation's premise holds.** `SMC_Context_Overlay.pine` already
  plots session high/low, opening-range high/low, a killzone background and a
  session row showing code and direction; `SMC_Long_Dip_Dashboard.pine` carries
  `BUS SessionVwap`. The session surface is present in Pro Context without this
  script.
- **The condition for keeping it is not met.** No mobile or layout test showing
  a distinct need exists.
- **It is unwired.** `SMC_Session_Context.pine` declares no `input.source` and
  imports nothing, and no script in the repo reads any of its outputs. The
  session data Context Overlay renders comes from `SMC_Context_Bus.pine`
  (`CTX Session*`), not from here — the two are parallel producers, not a chain.
- **It costs a pane.** It is `overlay = false`, so on top of an indicator slot
  it adds a second separate pane to a preset that already has one for HTF
  Confluence.

Its current real role is the **validation instrument** for this gate: the DST
and EXTENDED cases read its `Session Code` and `Session Source Close` rows. That
is an operator surface, which is exactly what `companion_operator_only` means,
and it stays one.

### Follow-up recorded, not silently dropped

Session Context is the only script that publishes session-level MSS
(`Session MSS Bull/Bear Confirmed`); nothing else in the repo does. That is a
genuine gap in the Pro Context surface — but the answer is to add it to Context
BUS and Context Overlay, where the session chain already lives, not to ship a
redundant parallel producer in a preset. Not in scope here.
