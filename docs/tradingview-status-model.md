# TradingView Status Model

## Purpose

The TradingView preflight report is now stage-based instead of relying on one coarse `ok` flag.

This keeps UI, compile, binding, and runtime smoke evidence separate.

## Per-Target Stages

Each target now reports these fields:

- `auth_ok`
- `chart_ok`
- `editor_ok`
- `compile_ok`
- `script_found_on_chart_ok`
- `settings_open_ok`
- `inputs_tab_ok`
- `bindings_count_ok`
- `bindings_names_ok`
- `runtime_smoke_ok`
- `overall_preflight_ok`

Additional target-level metadata:

- `auth_mode`
- `auth_source_path`
- `auth_reused_ok`
- `expected_input_labels`
- `observed_input_labels`
- `missing_input_labels`
- `bindings_names_not_verified`
- `screenshots`

## Aggregate Scopes

The report also exposes user-facing scope summaries:

- `ui_green`
- `compile_green`
- `binding_green`
- `runtime_green`

These aggregates are derived from the target stages, not from a separate heuristic.

## Status Values

Every stage uses one of these values:

- `true`: the stage was executed and passed
- `false`: the stage was executed and failed
- `not_run`: the stage was not applicable for that target
- `not_verified`: the stage was relevant but not safely proven

`not_run` and `not_verified` never count as success.

## Aggregate Rules

- Any `false` in scope produces a `false` aggregate.
- If no relevant stage ran for a scope, the aggregate is `not_run`.
- If no stage failed but one relevant stage is `not_verified`, the aggregate is `not_verified`.
- An aggregate is `true` only if all relevant stages are `true`.

## Meaning Of `overall_preflight_ok`

`overall_preflight_ok` is only `true` when every relevant stage for that target passed.

Examples:

- `SMC Core Engine` can be fully green without `settings_open_ok` because settings validation is not part of that target.
- `SMC Dashboard` cannot be fully green if binding names are missing, even if compile already passed.
- `SMC Long Strategy` cannot be fully green if the script compiles but does not remain visible on chart.
