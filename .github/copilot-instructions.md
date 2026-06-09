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

Every workflow must have `defaults: run: shell: bash` before `jobs:`.  Most jobs
run on native GitHub-hosted Linux (`SMC_GH_HOSTED_RUNNER`, currently
`ubuntu-latest`), while a few explicitly routed workloads may run on Windows
self-hosted runners. Without this declaration, any job that does land on
Windows defaults to PowerShell (`pwsh`), which cannot parse bash syntax
(`[[ ]]`, `set -o pipefail`, heredocs, etc.). On `ubuntu-latest` the block is a
no-op.

The `fast-gates` required status check blocks any PR that adds a workflow file
missing this declaration.

### Runner contract

Use one of these patterns:

1. **Hosted/default workflows** keep the direct hosted expression:

```yaml
runs-on: ${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest' }}
```

This includes `ci.yml`. CI validate is intentionally GitHub-hosted; do not route
it through a self-hosted selector.

2. **GitHub Copilot Code Review / Copilot reviewer** is a GitHub-managed
  dynamic workflow named `Copilot`, not a repository-authored workflow file.
  Do **not** create or edit repository workflows to route Copilot review jobs
  to `self-hosted`, and do not document Copilot reviewer as using the local
  Windows runner. The AI reviewer should execute on GitHub-managed
  infrastructure.

3. **Routed workflows that genuinely need local Windows/GPU/cache
  characteristics** may use a hosted `select-runner` control-plane job plus a
  resolved worker runner:

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
Do not add `--inventory-unavailable-fallback required-self-hosted` or
`--no-idle-fallback required-self-hosted` unless the workflow truly cannot run
correctly on GitHub-hosted infrastructure.

Priority cron workflows use `vars.SMC_PRIORITY_CRON_SELF_HOSTED_LABEL`
(target value: `priority-cron`). GPU-backed Open-Prep feature-importance
workflows (`feature-importance-daily.yml`, `open-prep-outcome-backfill.yml`)
prefer `vars.SMC_PRIORITY_CRON_GPU_SELF_HOSTED_LABEL` (target value:
`priority-gpu`) and install `requirements-gpu.txt` on the self-hosted
runner before forcing `OPEN_PREP_FI_BACKEND=gpu`. Keep the generated report
artifact path aligned with `open_prep.feature_importance_report.FI_REPORT_DIR`
(`artifacts/open_prep/feature_importance/`), not the raw sample directory under
`artifacts/open_prep/outcomes/feature_importance/`.

The GPU research workflows follow the same routed-runner contract:

- `ml-family-research.yml` exposes `mode=train|explainability|tune` over the
  synthetic `ml/` dataset scaffold and prefers
  `vars.SMC_PRIORITY_CRON_GPU_SELF_HOSTED_LABEL` whenever `prefer_gpu=true`.
  The workflow must probe the selected backend first and then surface the
  actual `resolved_devices` plus any `device_fallback_reason` values in the
  step summary / artifact contract.
- `rl-research-training.yml` trains the research-only PPO/SAC agents from
  `rl/` against the synthetic execution env and also prefers the GPU label
  when `prefer_gpu=true`.

`rl-research-training.yml` must install `requirements-rl-gpu.txt` on the
self-hosted GPU runner and only set `SKIPP_RL_DEVICE=cuda` after probing
that `torch.cuda.is_available()` is actually true. The generic
`requirements-rl.txt` torch dependency alone is not sufficient on Windows
because the PyPI wheel is CPU-only.

Their entrypoints are `scripts/run_ml_family_training.py`,
`scripts/run_ml_explainability_report.py`, `scripts/run_ml_optuna_tuning.py`,
and `scripts/run_rl_research_training.py`. Keep them synthetic/offline unless
the live dataset swap is implemented deliberately.

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

### Python environment

- For local Python work in VS Code, use a repo-local virtual environment at
  `.venv` so tasks, the Testing panel, and terminal commands share one
  interpreter.
- Bootstrap on Windows with
  `./scripts/bootstrap_venv.ps1 -VenvPath .venv`.
- Bootstrap on macOS/Linux with
  `SKIPP_VENV=.venv ./scripts/bootstrap_venv.sh`.
- The workspace uses `.env` from the repo root for local secrets; never commit
  real credentials.
- Optional local GPU backend for Open Prep feature-importance:
  install `requirements-gpu.txt` into `.venv` and set
  `OPEN_PREP_FI_BACKEND=gpu`. Accepted values are `auto|cpu|gpu`; use
  `OPEN_PREP_FI_GPU_DEVICE=<index>` when the runner has multiple visible GPUs.
- Optional ML research stack: install `requirements-ml.txt` and use
  `SKIPP_ML_DEVICE=auto|cpu|cuda` with the `run_ml_*` scripts. Treat `cuda`
  as a request and inspect `resolved_devices` / `device_fallback_reason`
  instead of assuming the backend really stayed on GPU.
- Optional RL research stack: install `requirements-rl.txt` and use
  `SKIPP_RL_DEVICE=auto|cpu|cuda` with `scripts/run_rl_research_training.py`.
- For CUDA-enabled RL locally or on the self-hosted runner, install
  `requirements-rl-gpu.txt` after `requirements-rl.txt` with
  `python -m pip install --force-reinstall -r requirements-rl-gpu.txt`.

### Testing

- Every new Python module must have a corresponding test file in `tests/`.
- Tests must be deterministic — no live API calls, no network I/O, no `time.sleep`.
- Mark timing-sensitive tests with `@pytest.mark.flaky(reruns=2)`.
- Focused suite / current file / VS Code Testing panel: run serial
  (`python -m pytest -q <file>`). Do not add xdist for single-file or debug
  runs.
- Debug current file with `python -m pytest -vv -s --maxfail=1 <file>`.
- Local fast sweep: `python -m pytest -q --maxfail=1 -n 8 --dist=worksteal tests`.
- CI parity (PR-like local run):
  `python -m pytest -q --maxfail=1 -n auto --dist=worksteal tests`.
- Push-like local coverage run:
  `python -m pytest -q --maxfail=1 -n auto --dist=worksteal --cov --cov-report=term-missing:skip-covered tests`.
- Prefer the matching VS Code tasks when available:
  `python: bootstrap repo .venv`, `pytest: focused current file`,
  `pytest: debug current file`, `pytest: local fast (8 workers)`,
  `pytest: CI parity (PR)`, `pytest: push-like coverage`.
- Do not reintroduce a global xdist default in `pyproject.toml`; focused runs
  are intentionally serial because the repo has many very large test files.

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

## Token-efficiency rules

### Terminal output size

When running commands that produce large output (CI logs, workflow runs,
grep over big files), always pipe through `| head -N` or `| tail -N`
(default N ≤ 20) to keep terminal-notification payloads small. Never dump
full `gh run view --log` output unfiltered — always combine with `grep` AND
a `head`/`tail` cap.

### Subagent delegation

Use the `Explore` subagent (or `search_subagent`) for exploratory reads:
"find all files matching X", "how does module Y work", "locate references
to Z". The subagent runs in its own context and returns only a compact
summary — its file-read tokens do not accumulate in the main session.

### Compaction reminder

After completing a multi-step task (todo list fully done, PR merged, or
major milestone reached), remind the user to run `/compact` if the
conversation has been going for a while. Keep the reminder to one short
line, e.g.: "💡 Guter Zeitpunkt für `/compact` — Session ist lang."

## Kommunikationsregeln

- Antworte IMMER auf Deutsch, es sei denn der User schreibt explizit auf
  Englisch.
- Erkläre fachliche Ergebnisse nutzerfreundlich — keine reinen
  PR-/Commit-Referenzen als Antwort. Wenn der User nach dem Stand fragt,
  liefere Klartext-Zusammenfassung, nicht nur Nummern.
- Git-Commits, PR-Titel und Code-Kommentare bleiben auf Englisch
  (Repo-Konvention).

## PR-Housekeeping

Wenn der User "merge", "mergeable machen" oder "Konflikte lösen" sagt:

1. `gh pr list --state open --json number,title,mergeable,headRefName | head -20`
2. Für jeden MERGEABLE PR: `gh pr checks <N>` — nur mergen wenn alle
   required checks grün.
3. Für CONFLICTING PRs: rebase auf main, Konflikte lösen, force-push.
4. Copilot-Review-Comments prüfen (inline + threads via API, nicht nur
   `gh pr view`).
5. Ergebnis als kompakte Tabelle ausgeben: `PR# | Status | Aktion`.

## Env-Var-Disziplin

- NIEMALS eine bestehende Env-Var umbenennen ohne explizite User-Freigabe.
- Vor jeder Env-Var-Änderung:
  `grep -rn "ENV_VAR_NAME" --include="*.py" --include="*.yml"` um ALLE
  Consumers zu identifizieren.
- Wenn Python-Code und Workflow unterschiedliche Namen verwenden: den
  Python-Namen als kanonisch behandeln, Workflow anpassen.

## Proaktive Status-Updates

- Nach Abschluss eines mehrstufigen Tasks: automatisch eine 3–5 Zeilen
  Status-Zusammenfassung geben (was erledigt, was offen, was blockiert).
- Bei "was ist der Stand" / "nächste Schritte": Session-Memory und
  Todo-Liste prüfen, dann kompakte Tabelle ausgeben.
- Keine Filler-Texte — direkt die Fakten.

## Session-Start

- Beim ersten Turn einer neuen Session: prüfe ob ein Handover-Dokument
  (z. B. `spec/agent_handover.md`) auf main existiert. Falls ja: lesen und
  als Arbeitskontext übernehmen, aktuellen Stand kurz bestätigen.
- Frage nicht nach — einfach lesen und loslegen.
