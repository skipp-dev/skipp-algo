# ADR-0010: Cron-workflow invariants — per-workflow contract tests vs. generative suite

| Field      | Value                                                                 |
|------------|-----------------------------------------------------------------------|
| Status     | Accepted (Option C) — initial suite implemented                       |
| Date       | 2026-05-30                                                            |
| Deciders   | skipp-dev                                                             |
| Related    | `tests/test_credential_health_workflow.py`, `tests/test_ci_workflow_structural_pin.py`, `tests/test_run_open_prep_daily_workflow_contract.py`, `tests/test_promotion_gate_daily_workflow_contract.py`, `tests/test_phase_b_promotion_readiness_workflow_contract.py`, `tests/test_f2_promotion_gate_daily_workflow_contract.py`, `tests/test_workflow_freshness_monitor_workflow_contract.py`, F-V5-C2, F-V6-F2.1, F-V8 |

## Context

Cron-only workflows in `.github/workflows/` carry a fixed set of
structural invariants:

- F-V5-A2: `PYTHONUNBUFFERED=1` in `env:`
- F-V5-C2: `concurrency:` block with `cancel-in-progress: false`
- F-V6-F2.1: `# live-window: <classification>` marker in first 10 lines
- F-V8: `paths-ignore` + runner pinning
- Permissions minimised to `contents:read` (+ `issues:write` for crons
  that open dedup issues)

These are pinned today via a **per-workflow contract test**:
`tests/test_<name>_workflow_contract.py`. Six such files exist already
(`credential_health`, `ci`, `run_open_prep_daily`,
`promotion_gate_daily`, `phase_b_promotion_readiness`,
`f2_promotion_gate_daily`, `workflow_freshness_monitor`), and each is
~80% identical boilerplate.

## Decision drivers

- **Drift cost**: adding F-V6-F2.x or similar requires editing all N
  contract files. The recent live-window-marker rollout (#2449) hit
  exactly this — multiple workflows needed identical changes.
- **Coverage gap**: new cron workflows lack coverage until someone
  copies the template (the freshness-monitor was added in #2433 with
  no pin until #2453).
- **Customisation**: each contract test does pin *workflow-specific*
  things (e.g. monitored-inventory in freshness-monitor, validate-job
  list in ci). A pure generative test cannot capture this.

## Options

### Option A — Status quo (per-workflow contract tests)
Pros: full control, ad-hoc workflow-specific pins fit naturally. Cons:
boilerplate drift, slow rollout of new global invariants.

### Option B — Single parametrised invariant suite + per-workflow spec YAML
One `tests/test_cron_workflow_invariants.py` loops over every cron in
a `tests/_workflow_specs/` directory. Each workflow has a small
`<name>.yaml` declaring its window class, monitored crons, budget hours,
etc. The suite enforces the universal invariants; the spec YAML
captures the workflow-specific pin data.

Pros: adding a global invariant = one-line change in the suite. New
cron = drop a YAML, auto-pinned. Cons: harder to read at a glance for
a single workflow; debug-on-failure jumps through indirection.

### Option C — Hybrid (universal suite + targeted contract test per workflow)
Universal invariants live in B-style suite; workflow-specific pins
stay in their existing files but shrink to ~20 lines (just the
specifics). Pros: best of both. Cons: two homes for the same
workflow's pins; coordination cost.

### Option D — Lint plugin
Custom `yamllint`/`actionlint` rule that enforces the invariants at
lint time, no pytest involvement. Pros: fastest feedback. Cons: outside
the pin-ledger philosophy; not version-controllable as test data.

## Decision

**Option C — Hybrid.** A parametrised generic suite covers the
universal invariants (concurrency, timeout, permissions, on-schedule,
upload-artifact version, SMC_GH_HOSTED_RUNNER selector). Workflow-
specific contract tests stay for special markers (e.g. live-window
marker on credential-health, freshness-monitor URL pin). New global
invariants land in one place; existing files shrink incrementally.

## Consequences

- B is the largest one-time migration but has the highest long-term
  leverage; new global invariants become trivial.
- C is the safe incremental path: roll out the universal suite, leave
  existing tests, retire boilerplate over time.
- D fundamentally re-locates the contract; may conflict with ADR-0009.

## Implementation

`tests/test_cron_workflow_invariants.py` is the universal suite. It
parametrises over every pure-cron workflow (shared `_is_pure_cron`
definition with `test_workflow_concurrency_cron_no_cancel.py`) and owns
the **net-new** universal invariant: F-V10 — every cron job must declare
a sane `timeout-minutes` runaway guard. The other universal invariants
named in the Decision are *already* enforced generically by dedicated
parametrized guards (`test_workflow_concurrency_cron_no_cancel`,
`test_workflow_permissions_present`, `test_workflow_python_unbuffered`,
`test_workflow_runner_pinned`); the suite cross-references those rather
than duplicating them, to avoid two enforcement sites drifting. As the
contract files shrink over time, additional universal pins migrate here.

Rollout also closed the one pre-existing gap the new invariant exposed:
`plan-2-8-monthly-digest.yml` had no `timeout-minutes` on its sole job
(now `10`, matching the sibling `plan-2-8-weekly-digest.yml`).
