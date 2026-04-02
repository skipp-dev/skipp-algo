# No Shadow Logic Policy — v5.5b

**Scope**: SMC_Core_Engine.pine + generator builders  
**Last updated**: AP6 v5.5b

---

## Rule

> Pine consumers must not rebuild a competing interpretation layer that
> materially overrides the lean generator contract.

If a concept exists as a v5.5b lean field, Pine should consume that field
directly rather than recomputing an alternative meaning from broad fields.

For Event Risk, Session Context, and Structure State, the lean surface reuses
the canonical export names. Pine must not introduce or depend on parallel
`*_LIGHT_*` aliases for those shared fields.

## What is allowed

| Category | Allowed | Example |
|----------|---------|---------|
| Visualization logic | yes | Label formatting, color mapping, line drawing |
| Lifecycle transitions | yes | Zone armed → confirmed → ready state machine |
| Runtime constraints | yes | Bar-gap checks, freshness timeouts |
| Aggregation in unique direction | yes | `session_light_ok = lib_scl_context_score >= 2` |
| ~~BUS backward compat export~~ | ~~yes~~ | ~~Broad fields for ModulePackE/F/G~~ — **Removed Phase B** |

## What is NOT allowed

| Category | Violated | Example |
|----------|----------|---------|
| Parallel event risk computation | yes | ~~`event_risk_hard_block = lib_market_event_blocked or ...`~~ when lean gate exists |
| Reconstructing direction from old fields | yes | Using broad `STRUCTURE_STATE` to gate when `lib_strl_trend_strength` exists |
| Duplicate quality scoring | yes | Computing local quality score when Signal Quality lean fields exist |
| Alias drift | yes | Exporting `SESSION_LIGHT_*` while the contract says `SESSION_*` |

## BUS Backward Compat Fields (Removed Phase B)

All 33 broad fields previously exported to BUS ModulePackE/F/G have been
**removed in Phase B (AP6 v5.5b)**. Dashboard reads LeanPackA/B exclusively.
No backward compat code remains.

## Audit Status

| Area | Shadow Logic? | Status |
|------|--------------|--------|
| Event Risk gate | NO | Lean-only (v5.5b canonical exports) |
| Event Risk state | NO | Lean-only (v5.5b canonical exports) |
| Session Context gate | NO | Lean-only (`session_light_ok`) |
| Structure gate | NO | Lean-only (`struct_light_trending`) |
| OB gate | NO | Lean-only (`ob_light_bull_ok`) |
| FVG gate | NO | Lean-only (`fvg_light_active_ok`) |
| Signal Quality | NO | Primary gate for Ready / Best / Strict (`lib_sq_*`) |
| Context Quality | SUPPORT ONLY | Diagnostic / telemetry only; not a primary gate |
| ~~BUS ModulePackE/F/G~~ | ~~Compat~~ | **Removed Phase B** |
