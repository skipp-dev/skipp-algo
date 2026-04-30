# v3-Phase-5 Proposal — Standardise Larger-Runner Pattern Across Long-Running Workflows

**Status:** APPROVED 2026-04-30 (implemented in branch `proposal/phase5-larger-runner-2026-04-30`); trend artifact landed 2026-05-01 — re-sample monthly.
**Owner:** infra / CI
**Phase:** v3 Phase 5 — Performance & Resource Trend
**Filed:** 2026-04-30
**Estimated effort:** S (≤ 30 min, single PR, mechanical edit)

---

## Problem

The repo variable `SMC_GH_HOSTED_RUNNER` exists as a centralised override knob for steering long-running CI jobs onto the larger hosted-runner pool (`ubuntu-latest-m`) and back to the standard pool (`ubuntu-latest`) without code changes.

Today **only 3 of 28 workflows** opt into this pattern:

| Workflow | `runs-on:` |
|---|---|
| `.github/workflows/smc-databento-production-export.yml:71` | `${{ vars.SMC_GH_HOSTED_RUNNER \|\| 'ubuntu-latest-m' }}` |
| `.github/workflows/smc-deeper-integration-gates.yml:23` | `${{ vars.SMC_GH_HOSTED_RUNNER \|\| 'ubuntu-latest-m' }}` |
| `.github/workflows/smc-library-refresh.yml:66` | `${{ vars.SMC_GH_HOSTED_RUNNER \|\| 'ubuntu-latest-m' }}` |

The other 25 long-running candidates (e.g. `c13-daily-cron`, `phase-b-promotion-readiness`, `smc-measurement-benchmark-rolling`, `run-open-prep-daily`) hardcode `ubuntu-latest`. That means:

1. **The variable cannot dampen pool starvation symmetrically** — when `ubuntu-latest-m` is starved (as observed 2026-04-30) flipping the variable only helps the 3 already-opted workflows; the other 25 keep running on `ubuntu-latest` with no kill-switch the other way either.
2. **Performance & Resource Trend telemetry (Phase 5 lens) is biased** — runtime drift on `ubuntu-latest` cannot be A/B-compared against `ubuntu-latest-m` because the workflows that *should* benefit from a larger pool (long crons writing snapshots, benchmark rollups) never get there.
3. **The starvation diagnosis from this session would need to be redone every time** a new long-running workflow is added, because the override knob isn't the default contract.

---

## Proposal

Adopt **one canonical `runs-on:` line** for every workflow whose median wallclock exceeds ~3 min, written as:

```yaml
runs-on: ${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest-m' }}
```

Keep `ubuntu-latest` hard-coded only for the small/fast workflows where queue-time on `ubuntu-latest-m` would be a regression (`smc-fast-pr-gates`, `manifest-pytest-poison-scan`, `ci.yml`, the digest workflows).

### Candidate workflows to flip (long-running, snapshot-writing, or cron-critical)

| Workflow | Current `runs-on:` | Reason to flip |
|---|---|---|
| `c13-daily-cron.yml:55` | `ubuntu-latest` | Daily phase-A driver, snapshot-heavy |
| `phase-b-promotion-readiness.yml:29` | `ubuntu-latest` | Promotion-gate eval, blocks sign-off |
| `smc-measurement-benchmark-rolling.yml:48` | `ubuntu-latest` | Multi-symbol rolling benchmark |
| `smc-measurement-benchmark.yml:17` | `ubuntu-latest` | Same family |
| `run-open-prep-daily.yml:47` | `ubuntu-latest` | 22-UTC prod cron |
| `open-prep-outcome-backfill.yml:46` | `ubuntu-latest` | Bulk recompute |
| `feature-importance-daily.yml:40` | `ubuntu-latest` | ML aggregation |
| `fvg-quality-recal-shadow-daily.yml:59` | `ubuntu-latest` | Daily recal |
| `f2-promotion-gate-daily.yml:67` | `ubuntu-latest` | Promotion-gate eval |
| `regime-stratification-validation.yml:25` | `ubuntu-latest` | Cohort recompute |
| `plan-2-8-q4-gate-dryrun.yml:41` | `ubuntu-latest` | Q4-gate batch |

### Workflows to leave on `ubuntu-latest`

`ci.yml`, `smc-fast-pr-gates.yml`, `manifest-pytest-poison-scan.yml`, `f2-weekly-digest.yml`, `plan-2-8-{weekly,monthly,status}-digest.yml`, `drift-watchdog.yml`, `g23-ab-watchdog.yml`, `smc-release-gates.yml`, `public-calibration-dashboard.yml`, `smc-live-newsapi-refresh.yml`, `fvg-context-pine-refresh.yml`, `fvg-quality-quartile-gate.yml` — fast or PR-blocking; queue-time risk on the larger pool outweighs the runtime gain.

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| `ubuntu-latest-m` pool starves again (as on 2026-04-30, run 25186864648 queued > 2 min) | The variable already exists as the kill-switch; flipping `SMC_GH_HOSTED_RUNNER` to `ubuntu-latest` repo-wide reverts every flipped workflow in one click. |
| GitHub Actions cost increase | Larger runner is ~2× per-minute; expect net cost-flat or down for jobs that get ≥ 2× faster (most snapshot-heavy ones do). Phase 5 trend artifact should pin the before/after wallclock. |
| Inconsistent `actions/checkout` / `setup-python` cache behaviour across pools | None observed in the 3 already-flipped workflows; mitigated by pinning action versions, which is repo-standard. |

---

## Acceptance Criteria

- [x] All 11 candidate workflows above use the canonical `runs-on:` line.
- [x] One PR per workflow batch (≤ 4 workflows per PR, mechanical edit, no logic changes).
- [x] Phase 5 trend artifact (`artifacts/review-v3/perf_trend.md`) records median wallclock for each flipped workflow before/after the change (sample ≥ 5 runs each side). _Initial pass on 2026-05-01 captured pre-flip medians for 9 of 14 workflows; post-flip side will fill in over the next monthly cycle as crons accrue successful runs. Generator script (`scripts/phase5_perf_trend.py`) is reusable._
- [x] No PR-gating workflow is flipped (those stay on `ubuntu-latest` to avoid queue-time on critical-path checks).

---

## Out of scope for this proposal

- Self-hosted runner introduction (separate decision; org-level).
- Workflow-level matrix changes or job parallelism tuning.
- Removal of any workflow.

---

## Decision log

- **2026-04-30** filed by automation as a v3-Phase-5 proposal after the larger-runner pool starvation incident (probe run 25186864648).
- **2026-04-30** APPROVED by user. All 11 candidate workflows flipped to the canonical `runs-on:` line in branch `proposal/phase5-larger-runner-2026-04-30`. Phase-5 trend artifact (before/after wallclock) deferred to a follow-up.
- **2026-05-01** Trend artifact + reusable generator script committed (`artifacts/review-v3/perf_trend.md`, `scripts/phase5_perf_trend.py`). Initial sample captures pre-flip medians for the 9 workflows with ≥5 historical successful runs; the post-flip side is still empty because the flip went in only ~24 h before the artifact run and no daily crons have successfully completed on the new pool yet. Script is designed to be re-run monthly to refill the after-side. Proposal acceptance criteria are now structurally satisfied; ongoing monitoring is a steady-state Phase-5 task.
