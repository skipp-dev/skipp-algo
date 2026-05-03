{% raw %}
# J3-FOLLOWUP — cron→workflow_run conversion candidates

**Audit date**: 2026-05-01
**V4 audit class**: J3-FOLLOWUP
**Status**: analysis-only — implementation deferred to per-workflow follow-ups.

## Background

Several daily/weekly workflows in `.github/workflows/` use `schedule: cron` with **comments declaring an upstream dependency** on another scheduled workflow. Pattern:

```yaml
# 10:00 UTC daily — runs after smc-measurement-benchmark-rolling
# (07:30 UTC) and feature-importance-daily (09:00 UTC) so the
# dual-arm artifact dirs are guaranteed to be in place.
- cron: "0 10 * * *"
```

This is **timing-brittle**: if the upstream slips (CI queue, retries, extended runtime), the downstream still fires at its hard-coded slot and races against half-finished artifacts. The fix is `workflow_run` — fire downstream **after** upstream completes successfully, regardless of clock time.

## Cascade map

```
smc-measurement-benchmark-rolling.yml  (07:30 UTC daily)
   ├─ feature-importance-daily.yml      (09:00 UTC)  ← candidate
   ├─ public-calibration-dashboard.yml  (04:30 UTC)  ← candidate (depends "after rolling settles")
   ├─ fvg-context-pine-refresh.yml      (05:15 UTC)  ← candidate
   └─ f2-promotion-gate-daily.yml       (10:00 UTC)  ← candidate (also depends on feature-importance)

public-calibration-dashboard.yml       (04:30 UTC)
   └─ g23-ab-watchdog.yml               (05:30 UTC)  ← STRONG candidate (single upstream)
       └─ fvg-quality-quartile-gate.yml (06:00 UTC)  ← candidate (also depends on dashboard)

f2-promotion-gate-daily.yml            (10:00 UTC)
   └─ f2-weekly-digest.yml              (Mon 11:00 UTC)  ← candidate

smc-databento-production-export.yml    (12:00, 14:00, 16:00, 18:00 UTC)
   └─ smc-library-refresh.yml          (12:30, 14:30, 16:30, 18:30 UTC)  ← 4-tick cascade
```

## Conversion priority

Risk-ordered, lowest first. Each row should ship as its own PR with rollback.

| Priority | Downstream | Upstream | Risk |
|---|---|---|---|
| 1 | `g23-ab-watchdog.yml` | `public-calibration-dashboard.yml` | LOW — single upstream, single downstream |
| 2 | `feature-importance-daily.yml` | `smc-measurement-benchmark-rolling.yml` | LOW — single upstream |
| 3 | `public-calibration-dashboard.yml` | `smc-measurement-benchmark-rolling.yml` | LOW — single upstream |
| 4 | `fvg-context-pine-refresh.yml` | `smc-measurement-benchmark-rolling.yml` | LOW — single upstream |
| 5 | `f2-weekly-digest.yml` | `f2-promotion-gate-daily.yml` (Mon-only) | MED — Mon-only filter via `if: github.event.workflow_run.created_at` weekday check |
| 6 | `f2-promotion-gate-daily.yml` | `feature-importance-daily.yml` (last-of-2) | MED — depends on TWO upstreams; need either to wait for both via dispatched-run guard, or drop the rolling-bench dependency |
| 7 | `fvg-quality-quartile-gate.yml` | `g23-ab-watchdog.yml` (last-of-2) | MED — same dual-upstream issue |
| 8 | `smc-library-refresh.yml` cascade | `smc-databento-production-export.yml` | HIGH — 4-tick cascade, every conversion must preserve per-tick parity |

## `workflow_run` template

```yaml
on:
  workflow_run:
    workflows: ["smc-measurement-benchmark-rolling"]   # exact name: from upstream's `name:` key
    types: [completed]
    branches: [main]
  workflow_dispatch:
    inputs:
      lookback:
        description: "..."

jobs:
  guard:
    runs-on: ubuntu-24.04
    if: ${{ github.event_name == 'workflow_dispatch' || github.event.workflow_run.conclusion == 'success' }}
    steps:
      - run: echo "upstream succeeded; proceeding"
```

### Caveats

- `workflow_run` only fires from default-branch workflow definitions. Conversions cannot be tested on a feature branch — the trigger only activates after merge to `main`.
- The downstream loses access to `inputs` declared via `workflow_dispatch` when fired by `workflow_run`. Use `workflow_run.outputs` (requires upstream to emit them) or fall back to defaults.
- `workflow_run` runs in the context of the upstream's commit, **not** the downstream's. For workflows that read repo files, use `actions/checkout` with `ref: ${{ github.event.workflow_run.head_sha }}` or pin to `main`.
- For Mon-only / weekday-only schedules (e.g. `f2-weekly-digest.yml`), add a step-level guard:
  ```yaml
  if: ${{ github.event_name == 'schedule' || (github.event_name == 'workflow_run' && fromJSON(format('[{0}]', date(github.event.workflow_run.created_at, 'EEE'))) == 'Mon') }}
  ```
  (or simpler — keep weekday workflows on cron and let only daily ones convert).

## Recommendation

Ship priority 1–4 as four separate PRs. Re-evaluate priority 5–7 after observing whether priority 1–4 reduce the alert noise. Defer priority 8 indefinitely (4-tick cascade has too much per-run variance to justify the conversion risk).

## Defense regression guard

This PR adds no test (the `workflow_run` shape is a positive feature, not a forbiddable pattern). Each conversion PR will land its own assertion that the converted workflow has both `workflow_run` AND `workflow_dispatch` triggers, and that the upstream `name:` referenced exists.

## Out of scope for this audit

- `smc-databento-production-export.yml` (4-tick cascade) — too much variance.
- `drift-watchdog.yml` (Mon-only, depends on a "C2 walk-forward cron" that wasn't found in the current workflow set) — investigate upstream existence first.
- `plan-2-8-status-daily.yml` (intentional pre-bench timing per its comment) — keep cron.
{% endraw %}
