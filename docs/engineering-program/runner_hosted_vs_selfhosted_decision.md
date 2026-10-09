{% raw %}
# WP-R3 — Hosted-vs-Self-hosted Runner Decision

Stand: 2026-06-23

> ⚠️ **Status-Hinweis (2026-06-23):** Dieses Dokument ist eine historische
> Entscheidungsaufnahme aus April 2026. Der aktuelle produktive Zustand ist ein
> resolver-basiertes Mischmodell mit GitHub-hosted Fallback und globalem
> Kill-Switch `SMC_FORCE_GH_HOSTED`.
>
> Source of truth:
> - `docs/self_hosted_runner_reservation_runbook.md`
> - `scripts/resolve_workflow_runner.py`

## Decision (historical snapshot)

**April-2026 snapshot:** Use GitHub-hosted runners exclusively.

This statement is no longer globally true for current `main`: resolver-based
workflow routing can still select self-hosted runners when available, unless
`SMC_FORCE_GH_HOSTED` is enabled.

## Rationale

### Evidence

| Factor | Hosted (`ubuntu-latest`) | Self-hosted |
|--------|-------------------------------|-------------|
| Recent success rate | 13/15 (86%, failures = gate logic, not runner) | N/A — never reached production |
| Typical pipeline duration | 22–28 min | Unknown |
| Step-12 stability | No crashes in 15+ consecutive runs | Unknown |
| Infrastructure overhead | Zero — GitHub manages the runner | macOS launchAgent, maintenance, patching |
| Secrets management | GitHub Actions secrets — no local exposure | Local secrets on the runner host |
| Scaling | Automatic — GitHub provisions per run | Manual capacity management |
| Cost | Included in GitHub plan (standard hosted runner) | Hardware + electricity + maintenance time |
| Rollback | Change one YAML line | Rebuild runner infrastructure |

### Failure Mode Analysis

The only observed failures in the last 15 runs were evidence gate and
pre-publish release gate failures — both are expected quality-control stops,
not runner-side problems. No OOM, no VM reclaiming, no timeout reached.

### Cost

All workflows currently run on the standard `ubuntu-latest` runner.
The `SMC_GH_HOSTED_RUNNER` repository variable is available to upgrade to a
larger runner (e.g. `ubuntu-24.04-4core`) if pipeline durations grow beyond
acceptable thresholds. Current durations on `ubuntu-latest` are acceptable.

## Runner Configuration

| Setting | Value |
|---------|-------|
| Runner label | `ubuntu-latest` (active) |
| Repository variable | `SMC_GH_HOSTED_RUNNER` |
| Workflow field | `runs-on: ${{ vars.SMC_GH_HOSTED_RUNNER \|\| 'ubuntu-latest' }}` |
| Fallback | `ubuntu-latest` (if variable is unset) |
| Timeout | 120 minutes |

## Self-hosted: Historical Context

A self-hosted macOS launchAgent runner was explored in earlier phases but
never merged to `main`. The approach was abandoned because:

1. Secrets had to be stored locally on the runner host.
2. The runner required manual maintenance and patching.
3. The standard hosted runner proved sufficient once pipeline batching and
   caching were implemented, removing the need for larger runner hardware.

The repository now contains active self-hosted routing/reservation artifacts
again (see source-of-truth links above).

## Future Escalation Path

If the pipeline outgrows the 4-core runner (see
[step12_resource_envelope.md](step12_resource_envelope.md) for thresholds),
the next step is the 8-core GitHub-hosted runner — not self-hosted. The
upgrade requires only:

1. Create an `ubuntu-24.04-8core` runner in the org settings.
2. Update `SMC_GH_HOSTED_RUNNER` to the new label.
3. Verify one manual run.

## Supersedes

This document supersedes the pilot guidance in
`docs/smc_github_hosted_larger_runner_pilot.md`, which is retained as
historical context.
{% endraw %}
