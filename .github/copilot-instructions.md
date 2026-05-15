# GitHub Copilot Repository Instructions

## Workflow authoring rules

### Mandatory boilerplate (every workflow file)

Every `.github/workflows/*.yml` must open with this skeleton — fill in the
`<replace>` placeholders:

```yaml
# live-window: any-trigger  # <feature-flag-id> (<YYYY-MM-DD>)
name: "<replace: workflow name>"

on:
  <replace: trigger>

permissions:
  contents: read

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

env:
  PYTHONUNBUFFERED: "1"
  PYTHONPATH: ${{ github.workspace }}
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: "true"

defaults:
  run:
    shell: bash

jobs:
  my-job:
    runs-on: ${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest' }}
    timeout-minutes: 20
```

Use `.github/workflow-templates/python-job.yml` or `docs-lint.yml` as a
copy-paste starting point for the two most common job shapes.

---

### Shell default (enforced by fast-gates lint)

Every workflow must have `defaults: run: shell: bash` before `jobs:`.  The
repository uses a Windows self-hosted runner (`SMC_GH_HOSTED_RUNNER`); without
this declaration every `run:` step defaults to PowerShell (`pwsh`), which cannot
parse bash syntax (`[[ ]]`, `set -o pipefail`, heredocs, etc.).  On
`ubuntu-latest` the block is a no-op.

The `fast-gates` required status check blocks any PR that adds a workflow file
missing this declaration.

### Runner contract

Use one of these two patterns:

1. **Hosted-only / scheduled / background workflows** keep the direct hosted expression:

```yaml
runs-on: ${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest' }}
```

2. **Merge-critical PR workflows** (`ci.yml`, `docs-lint.yml`,
   `manifest-pytest-poison-scan.yml`, `smc-fast-pr-gates.yml`) must use a
   hosted `select-runner` control-plane job plus a resolved worker runner:

```yaml
jobs:
  select-runner:
    runs-on: ${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest' }}

  validate:
    needs: select-runner
    runs-on: ${{ fromJson(needs.select-runner.outputs.runs_on_json) }}
```

The selector uses `scripts/resolve_workflow_runner.py` to prefer an idle
`self-hosted/windows/x64` runner (plus optional `vars.SMC_SELF_HOSTED_LABEL`)
and falls back to the hosted runner defined by `SMC_GH_HOSTED_RUNNER`.

`SMC_GH_HOSTED_RUNNER` is the **hosted fallback** runner label (currently
`ubuntu-latest`). Repository-variable fallback is **not** availability fallback;
do not point it at `self-hosted` and assume GitHub will fail over automatically.

**Never** use `ubuntu-latest-l` or `ubuntu-latest-m` — both labels are retired.

### Permissions

Declare `permissions: contents: read` at the workflow level (least-privilege).
Only escalate individual jobs that genuinely need it:

```yaml
jobs:
  comment:
    permissions:
      pull-requests: write
```

Never rely on the implicit default (it grants broad write access to the token).

### Timeouts

Always set `timeout-minutes` on every job. Guideline by type:

| Job type | Recommended limit |
|---|---|
| Lint / docs | 5–10 min |
| Python tests (targeted) | 20–35 min |
| Full pytest suite | 45 min |
| Data export / cron batch | 20–30 min |

### Bot / data-only PR short-circuit

For required status checks, add the bot-detection gate so pure-data PRs
(e.g. `bot/run-open-prep-*`) don't burn runner minutes:

```yaml
- name: Determine if heavy steps should run
  id: gate
  run: |
    if [[ "${{ github.event_name }}" == "pull_request" && \
          "${{ github.head_ref }}" == bot/* ]]; then
      echo "run_heavy=false" >> "$GITHUB_OUTPUT"
    else
      echo "run_heavy=true" >> "$GITHUB_OUTPUT"
    fi
```

Then add `if: steps.gate.outputs.run_heavy == 'true'` to every subsequent step.

### Python setup

For hosted-only workflows, use the composite action for a consistent, pinned
Python version:

```yaml
- name: Set up Python
  uses: ./.github/actions/setup-python-pinned
```

For merge-critical routed workflows, split bootstrap by runner environment:

```yaml
- name: Set up pinned Python (GitHub-hosted)
  if: needs.select-runner.outputs.runner_environment == 'github-hosted'
  uses: ./.github/actions/setup-python-pinned

- name: Resolve Python 3.12 interpreter
  run: |
    # export SMC_PYTHON_BIN here; self-hosted Windows falls back to py -3.12
```

The routed worker must export `SMC_PYTHON_BIN` and use that interpreter to
create the venv or invoke standalone scripts. The loud failure message for a
missing self-hosted Python 3.12 interpreter is part of the contract.

Only use raw `actions/setup-python@...` inside the composite action itself.

---

## Code authoring rules

### Testing

- Every new Python module must have a corresponding test file in `tests/`.
- Tests must be deterministic — no live API calls, no network I/O, no `time.sleep`.
- Mark timing-sensitive tests with `@pytest.mark.flaky(reruns=2)`.
- Run the full suite locally with `python -m pytest -n auto --dist=loadfile`
  before opening a PR.

### Imports / layer violations

- Do not import `terminal_*` modules from `smc_integration/`.
- Do not import `smc_integration/` from Pine-adjacent scripts in `scripts/`.
- Verify locally: `python scripts/check_layer_violations.py`.

### Pine scripts

- All Pine files must begin with `//@version=6`.
- Do not add `request.security(syminfo.tickerid, timeframe.period, ...)` — this
  is a redundant no-op caught by the T-3 guard in `fast-gates`.

### Atomic file writes

Use `mkstemp + fdopen + os.replace` for all file writes in `scripts/`. Raw
`open(..., 'w')` calls are guarded by `tests/test_atomic_write_call_sites.py`
and will fail CI.
