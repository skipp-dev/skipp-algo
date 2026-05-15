# Self-Hosted Runner Reservation Runbook

Stand: 2026-05-15

## Goal

Route the memory-heavy and GPU-specific GitHub Actions workflows onto the
Windows self-hosted pool when that pool is available, while preserving a safe
and fast fallback to GitHub-hosted runners whenever the self-hosted runner is
offline or already busy.

This document is the operator-facing policy for the runner labels and repo
variables used by:

- `.github/workflows/ci.yml`
- `.github/workflows/smc-fast-pr-gates.yml`
- `.github/workflows/smc-release-gates.yml`
- `.github/workflows/smc-databento-production-export.yml`
- `.github/workflows/smc-library-refresh.yml`
- `.github/workflows/smc-measurement-benchmark.yml`
- `.github/workflows/smc-measurement-benchmark-rolling.yml`
- `.github/workflows/run-open-prep-daily.yml`
- `.github/workflows/feature-importance-daily.yml`
- `.github/workflows/open-prep-outcome-backfill.yml`

## How runner selection works

`scripts/resolve_workflow_runner.py` resolves a self-hosted runner only when a
matching runner is both:

1. `online`, and
2. `busy == false`

Otherwise the workflow falls back immediately to
`${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest' }}`.

Operational consequence:

- a busy self-hosted runner does **not** create queueing at workflow start
- it causes immediate fallback to GitHub-hosted instead

That means the routing policy is mainly about **who gets first claim when the
self-hosted pool is idle**, not about building an internal queue.

## One-runner shared opportunistic option (recommended today)

This is the recommended setup while the repository has exactly one self-hosted
Windows runner.

### Repository variables

| Variable | Recommended value | Purpose |
| --- | --- | --- |
| `SMC_SELF_HOSTED_LABEL` | `generic-hosted-only` | Intentional non-match so generic workflows fall back to hosted |
| `SMC_PRIORITY_CRON_SELF_HOSTED_LABEL` | `priority-cron` | Preferred label for heavy cron / memory workflows |
| `SMC_PRIORITY_CRON_GPU_SELF_HOSTED_LABEL` | `priority-gpu` | Preferred label for GPU-oriented workflows |
| `SMC_CI_SELF_HOSTED_LABEL` | unset / blank | Lets CI reuse the cron runner opportunistically |

### Labels on the current self-hosted runner

Apply these labels to the current Windows runner (for example
`local-laptop-d6p88pla`):

- `priority-cron`
- `gpu`
- `priority-gpu`

Do **not** add these labels on the single-runner shared setup:

- `generic-hosted-only`
- `ci-heavy`

### What that routes

| Workflow family | Effective preference |
| --- | --- |
| `smc-databento-production-export`, `smc-library-refresh`, `smc-measurement-benchmark`, `smc-measurement-benchmark-rolling`, `run-open-prep-daily` | `priority-cron` |
| `feature-importance-daily`, `open-prep-outcome-backfill` | `priority-gpu` |
| `CI`, `smc-fast-pr-gates`, `smc-release-gates` | self-hosted only when the shared runner is idle; otherwise hosted fallback |

This shape gives the repository more self-hosted usage without reserving the
single machine so aggressively that CI loses its opportunistic speed-up.

### When to switch to safety-first mode

Leave the shared opportunistic profile in place unless one of the following
concrete triggers is observed; if any trigger fires, switch the repo variable
`SMC_CI_SELF_HOSTED_LABEL` to `ci-heavy` (without applying that label to the
runner) so the CI family fails over to GitHub-hosted and stops competing for
the `priority-cron` box.

Triggers (any one is sufficient):

- **Producer hosted-fallback rate**: `smc-databento-production-export` resolves
  `runner_environment=github-hosted` for **≥3 successful runs in any 7-day
  window**.
- **Producer OOM / SIGTERM on hosted**: any `smc-databento-production-export`
  run on hosted exits with code 137 or 143, or hits the 120-min cap, in the
  last **14 days** (this is the F-V8-Q5b / F-V8-C4 failure mode).
- **Library refresh handoff slip**: any week where `smc-library-refresh` PR
  cycle missed its release-gates handoff window because the producer ran on
  hosted and dragged the chain.

Switching back to shared opportunistic is symmetric: clear
`SMC_CI_SELF_HOSTED_LABEL` and confirm none of the triggers above have fired
in the trailing 30 days.

## One-runner safety-first option

Use this mode when protecting the producer / refresh cron chain matters more
than letting CI opportunistically land on self-hosted.

### Repository variables

| Variable | Safety-first value |
| --- | --- |
| `SMC_SELF_HOSTED_LABEL` | `generic-hosted-only` |
| `SMC_PRIORITY_CRON_SELF_HOSTED_LABEL` | `priority-cron` |
| `SMC_PRIORITY_CRON_GPU_SELF_HOSTED_LABEL` | `priority-gpu` |
| `SMC_CI_SELF_HOSTED_LABEL` | `ci-heavy` |

### Labels on the single current runner

Keep only:

- `priority-cron`
- `gpu`
- `priority-gpu`

Do **not** add:

- `ci-heavy`

### Why this works

The CI workflows already resolve:

`SMC_CI_SELF_HOSTED_LABEL || SMC_PRIORITY_CRON_SELF_HOSTED_LABEL || ''`

When `SMC_CI_SELF_HOSTED_LABEL=ci-heavy` and the current runner does not carry
that label, the CI family falls back to GitHub-hosted instead of competing for
the only `priority-cron` box.

Important: switching between the recommended shared mode and this safety-first
mode requires only repo variable / runner label changes. No workflow YAML needs
to change.

## Two-runner ideal split

Use this when a second self-hosted runner is available.

### Repository variables

| Variable | Two-runner value |
| --- | --- |
| `SMC_SELF_HOSTED_LABEL` | `generic-hosted-only` |
| `SMC_PRIORITY_CRON_SELF_HOSTED_LABEL` | `priority-cron` |
| `SMC_PRIORITY_CRON_GPU_SELF_HOSTED_LABEL` | `priority-gpu` |
| `SMC_CI_SELF_HOSTED_LABEL` | `ci-heavy` |

### Runner A — batch / memory / GPU

Labels:

- `priority-cron`
- `gpu`
- `priority-gpu`

Primary workloads:

- Databento producer
- library refresh
- measurement benchmark
- rolling benchmark
- open-prep daily
- FI / outcome-backfill GPU jobs

### Runner B — CI only

Labels:

- `ci-heavy`

Primary workloads:

- `CI / validate`
- `smc-fast-pr-gates / fast-gates`
- `smc-release-gates / release-gates`

### Rule

Do **not** cross-label the two runners if the goal is true reservation.

In particular:

- do not put `priority-cron` on the CI runner
- do not put `ci-heavy` on the cron runner

Otherwise the separation becomes advisory rather than real.

## Three-runner ideal split

Use this when CI, batch/memory work, and GPU work all deserve their own lane.

### Repository variables

Keep the same variable values as the two-runner model:

| Variable | Three-runner value |
| --- | --- |
| `SMC_SELF_HOSTED_LABEL` | `generic-hosted-only` |
| `SMC_PRIORITY_CRON_SELF_HOSTED_LABEL` | `priority-cron` |
| `SMC_PRIORITY_CRON_GPU_SELF_HOSTED_LABEL` | `priority-gpu` |
| `SMC_CI_SELF_HOSTED_LABEL` | `ci-heavy` |

### Runner lanes

| Runner | Labels | Recommended role |
| --- | --- | --- |
| Runner A | `priority-cron` | long-running memory-heavy cron / batch jobs |
| Runner B | `ci-heavy` | PR/push/release validation |
| Runner C | `gpu`, `priority-gpu` | GPU-heavy Open-Prep / ML / RL jobs |

This keeps GPU experiments from competing with Databento export / library
refresh memory spikes or with merge-critical CI gates.

## Decision table

| Available self-hosted runners | Recommended policy | Why |
| --- | --- | --- |
| 1 | shared opportunistic (`SMC_CI_SELF_HOSTED_LABEL` unset) | maximizes self-hosted usage without adding label churn |
| 1 with producer instability | safety-first (`SMC_CI_SELF_HOSTED_LABEL=ci-heavy`, but no runner has that label) | protects the memory-critical cron chain |
| 2 | dedicated CI split (`ci-heavy` + `priority-cron`) | first point where separate labels materially help |
| 3 | dedicated CI + batch + GPU lanes | removes cross-family contention completely |

## Operator steps

### 1. Set repository variables

Set the repo variables to the target profile from the tables above.

Minimum recommended current production values:

- `SMC_SELF_HOSTED_LABEL=generic-hosted-only`
- `SMC_PRIORITY_CRON_SELF_HOSTED_LABEL=priority-cron`
- `SMC_PRIORITY_CRON_GPU_SELF_HOSTED_LABEL=priority-gpu`
- `SMC_CI_SELF_HOSTED_LABEL` unset

### 2. Apply runner labels

Label each self-hosted runner according to its lane.

For the current single-runner shared setup, the one Windows runner should carry:

- `priority-cron`
- `gpu`
- `priority-gpu`

### 3. Verify the selected runner

Each routed workflow exposes the selection in three places:

1. the `select-runner` job output
2. an early `Announce selected runner` / `Emit runner selection` step
3. the workflow summary rows where implemented

Key fields to check:

- `runner_environment`
- `resolution_reason`
- `matched_runner_name`

Expected reasons:

- `matched_idle_self_hosted_runner`
- `no_idle_matching_self_hosted_runner`

### 4. Watch for unhealthy fallback patterns

If these workflows repeatedly fall back to hosted during their intended windows,
move to the next reservation profile:

- `smc-databento-production-export`
- `smc-library-refresh`
- `feature-importance-daily`
- `open-prep-outcome-backfill`

If CI is the only family that keeps missing self-hosted windows, the current
shared opportunistic mode is still working as designed.

#### Quick fallback audit (copy-paste)

List the most recent producer runs with their conclusion / timestamp:

```bash
gh run list -R skippALGO/skipp-algo \
  --workflow smc-databento-production-export.yml \
  --limit 50 \
  --json databaseId,conclusion,createdAt,displayTitle,headBranch \
  --jq '.[] | [.createdAt, .conclusion, .databaseId, .displayTitle] | @tsv'
```

For any individual run, inspect the `select-runner` job log to see why the
resolver chose hosted vs. self-hosted:

```bash
RUN_ID=<paste-databaseId>
gh run view "$RUN_ID" -R skippALGO/skipp-algo --log \
  | grep -E 'runner_environment|resolution_reason|matched_runner_name'
```

A healthy single-runner shared profile shows mostly
`resolution_reason=matched_idle_self_hosted_runner` for the producer; a
string of `no_idle_matching_self_hosted_runner` or
`runner_inventory_unavailable:*` for the producer is the signal to switch to
the safety-first profile (see *When to switch to safety-first mode* above).

> If the resolver consistently reports `runner_inventory_unavailable:HTTPError`
> the issue is not contention but token scope: confirm the `select-runner`
> job still declares `permissions: { administration: read }` and that any
> `GH_PAT` override (if set) has the `administration:read` scope on the repo.

## Anti-patterns

- Do not put `generic-hosted-only` on an actual runner.
- Do not create `ci-heavy` until you intend to reserve a CI lane.
- Do not cross-label the CI and cron runners in the split modes.
- Do not rename `priority-gpu` to `priority-cron-gpu` unless every workflow,
  test, variable, and runner label is updated in lockstep; there is no
  scheduling benefit in the current setup.

## Current recommendation summary

Today, with one self-hosted Windows box, keep:

- `priority-cron` for heavy cron / memory workflows
- `priority-gpu` for GPU-oriented jobs
- CI self-hosted usage as best-effort via the existing fallback chain

Only introduce a dedicated CI label (`ci-heavy`) when a second runner exists or
when protecting the memory-critical cron chain matters more than opportunistic
CI acceleration.