"""Pin the hybrid runner contract for merge-critical and priority cron workflows.

Hybrid strategy (2026-05-15)
----------------------------
Most workflows stay on the hosted runner expression::

    runs-on: ${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest' }}

CI (`ci.yml`) is intentionally GitHub-hosted. The remaining merge-critical
quick gates (`docs-lint.yml`, `manifest-pytest-poison-scan.yml`,
`smc-fast-pr-gates.yml`) and the priority cron workflows backing Databento /
Open Prep / live news refresh / measurement benchmarks are special:

* a small hosted `select-runner` control-plane job decides whether a matching
  self-hosted Windows runner is online and idle;
* the worker job then uses `fromJson(needs.select-runner.outputs.runs_on_json)`
  so it can prefer self-hosted when available and fall back cleanly to hosted
  when not.

This test prevents regressions back to the old stale `ubuntu-latest-l` lore and
ensures the selector pattern only appears where intended.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOWS_DIR = _REPO_ROOT / ".github" / "workflows"

_HOSTED_RUNS_ON = "${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest' }}"
_RESOLVED_RUNS_ON = "${{ fromJson(needs.select-runner.outputs.runs_on_json) }}"
_HEAVY_CI_CUSTOM_LABEL_EXPR = "${{ vars.SMC_CI_SELF_HOSTED_LABEL || vars.SMC_PRIORITY_CRON_SELF_HOSTED_LABEL || '' }}"
_FAST_GATES_CUSTOM_LABEL_EXPR = "${{ vars.SMC_CI_SELF_HOSTED_LABEL || '' }}"
_PRIORITY_CRON_CUSTOM_LABEL_EXPR = "${{ vars.SMC_PRIORITY_CRON_SELF_HOSTED_LABEL || vars.SMC_SELF_HOSTED_LABEL }}"
_ROUTED_WORKFLOWS = {
    "docs-lint.yml": {"worker_jobs": {"inline-backticks"}},
    "manifest-pytest-poison-scan.yml": {"worker_jobs": {"scan"}},
    "ml-family-research.yml": {"worker_jobs": {"research"}},
    "smc-fast-pr-gates.yml": {"worker_jobs": {"fast-gates"}},
    "smc-release-gates.yml": {"worker_jobs": {"release-gates"}},
    "feature-importance-daily.yml": {"worker_jobs": {"feature-importance-report"}},
    "open-prep-outcome-backfill.yml": {"worker_jobs": {"backfill"}},
    "rl-research-training.yml": {"worker_jobs": {"research"}},
    "run-open-prep-daily.yml": {"worker_jobs": {"run"}},
    "smc-library-refresh.yml": {"worker_jobs": {"refresh"}},
    "smc-measurement-benchmark.yml": {"worker_jobs": {"measurement-benchmark"}},
    "smc-measurement-benchmark-rolling.yml": {"worker_jobs": {"rolling-benchmark"}},
    "smc-databento-production-export.yml": {"worker_jobs": {"export"}},
    "smc-live-newsapi-refresh.yml": {"worker_jobs": {"refresh"}},
}


def _workflow_files() -> list[Path]:
    files = sorted(_WORKFLOWS_DIR.glob("*.yml")) + sorted(_WORKFLOWS_DIR.glob("*.yaml"))
    assert files, f"no workflow files found under {_WORKFLOWS_DIR}"
    return files


def _jobs(workflow: dict) -> dict[str, dict]:
    return {
        job_id: job
        for job_id, job in (workflow.get("jobs") or {}).items()
        if isinstance(job, dict)
    }


def _needs_list(job: dict) -> list[str]:
    needs = job.get("needs")
    if needs is None:
        return []
    if isinstance(needs, str):
        return [needs]
    if isinstance(needs, list):
        return [item for item in needs if isinstance(item, str)]
    return []


def _step_run(job: dict, step_name: str) -> str:
    for step in job.get("steps") or []:
        if not isinstance(step, dict):
            continue
        if step.get("name") != step_name:
            continue
        run = step.get("run")
        assert isinstance(run, str), f"{step_name!r} must define a run script"
        return run
    raise AssertionError(f"job is missing step {step_name!r}")


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_workflow_runs_on_contract(path: Path) -> None:
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    jobs = _jobs(workflow)

    if path.name in _ROUTED_WORKFLOWS:
        routed = _ROUTED_WORKFLOWS[path.name]
        assert "select-runner" in jobs, f"{path.name} must define a select-runner job"
        assert jobs["select-runner"].get("runs-on") == _HOSTED_RUNS_ON, (
            f"{path.name}:select-runner must stay on hosted control-plane runner {_HOSTED_RUNS_ON!r}"
        )
        for worker_job in routed["worker_jobs"]:
            assert worker_job in jobs, f"{path.name} missing worker job {worker_job!r}"
            job = jobs[worker_job]
            assert job.get("runs-on") == _RESOLVED_RUNS_ON, (
                f"{path.name}:{worker_job} must use resolved runs-on {_RESOLVED_RUNS_ON!r}"
            )
            assert "select-runner" in _needs_list(job), (
                f"{path.name}:{worker_job} must depend on select-runner"
            )
        return

    offenders: list[str] = []
    for job_id, job in jobs.items():
        if job.get("runs-on") != _HOSTED_RUNS_ON:
            offenders.append(f"  {job_id}: runs-on = {job.get('runs-on')!r}")
    assert not offenders, (
        f"{path.name} has jobs with non-pinned hosted runs-on:\n"
        + "\n".join(offenders)
        + f"\n\nExpected exactly: {_HOSTED_RUNS_ON!r}"
    )


def test_no_stale_ubuntu_latest_tier_literals() -> None:
    offenders: list[str] = []
    for path in _workflow_files():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "ubuntu-latest-l" in line or "ubuntu-latest-m" in line:
                offenders.append(f"  {path.name}:{lineno}: {line.strip()}")
    assert not offenders, (
        "Found retired hosted-runner tier literal(s):\n" + "\n".join(offenders)
    )


def test_no_bare_ubuntu_latest_runs_on() -> None:
    offenders: list[str] = []
    for path in _workflow_files():
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_id, job in _jobs(workflow).items():
            if job.get("runs-on") == "ubuntu-latest":
                offenders.append(f"  {path.name}:{job_id}")
    assert not offenders, (
        "Found bare ``runs-on: ubuntu-latest`` (no operator override or selector hook):\n"
        + "\n".join(offenders)
    )


def test_fast_gates_prefers_github_hosted_selector() -> None:
    # fast-gates is merge-critical: it must NOT fall back to priority-cron.
    # A dead self-hosted runner keeps the merge queue blocked for up to 6h
    # because timeout-minutes is only enforced by the runner itself.
    workflow = yaml.safe_load((_WORKFLOWS_DIR / "smc-fast-pr-gates.yml").read_text(encoding="utf-8"))
    resolve_script = _step_run(_jobs(workflow)["select-runner"], "Resolve worker runner")

    assert f'--custom-label "{_FAST_GATES_CUSTOM_LABEL_EXPR}"' in resolve_script
    assert "SMC_PRIORITY_CRON_SELF_HOSTED_LABEL" not in resolve_script
    assert '--custom-label "${{ vars.SMC_SELF_HOSTED_LABEL }}"' not in resolve_script


@pytest.mark.parametrize("workflow_name", ["smc-release-gates.yml"])
def test_heavy_ci_workflows_prefer_ci_specific_self_hosted_selector(workflow_name: str) -> None:
    workflow = yaml.safe_load((_WORKFLOWS_DIR / workflow_name).read_text(encoding="utf-8"))
    resolve_script = _step_run(_jobs(workflow)["select-runner"], "Resolve worker runner")

    assert f'--custom-label "{_HEAVY_CI_CUSTOM_LABEL_EXPR}"' in resolve_script
    assert '--custom-label "${{ vars.SMC_SELF_HOSTED_LABEL }}"' not in resolve_script


def test_ci_validate_runs_on_github_hosted_without_self_hosted_selector() -> None:
    workflow = yaml.safe_load((_WORKFLOWS_DIR / "ci.yml").read_text(encoding="utf-8"))
    jobs = _jobs(workflow)
    assert set(jobs) == {"validate"}
    validate = jobs["validate"]
    assert validate.get("runs-on") == _HOSTED_RUNS_ON
    assert "needs" not in validate
    text = (_WORKFLOWS_DIR / "ci.yml").read_text(encoding="utf-8")
    assert "required-self-hosted" not in text
    assert "needs.select-runner" not in text
    assert "runner-environment: github-hosted" in text


@pytest.mark.parametrize("workflow_name", ["run-open-prep-daily.yml", "smc-library-refresh.yml", "smc-measurement-benchmark.yml", "smc-measurement-benchmark-rolling.yml", "smc-databento-production-export.yml"])
def test_priority_cron_workflows_prefer_priority_cron_self_hosted_selector(workflow_name: str) -> None:
    workflow = yaml.safe_load((_WORKFLOWS_DIR / workflow_name).read_text(encoding="utf-8"))
    resolve_script = _step_run(_jobs(workflow)["select-runner"], "Resolve worker runner")

    assert f'--custom-label "{_PRIORITY_CRON_CUSTOM_LABEL_EXPR}"' in resolve_script


# F2.1 — pin the GPU-priority custom-label expression for the GPU-routed family.
_GPU_CRON_CUSTOM_LABEL_EXPR = (
    "${{ vars.SMC_PRIORITY_CRON_GPU_SELF_HOSTED_LABEL || "
    "vars.SMC_PRIORITY_CRON_SELF_HOSTED_LABEL || "
    "vars.SMC_SELF_HOSTED_LABEL }}"
)


@pytest.mark.parametrize(
    "workflow_name", ["feature-importance-daily.yml", "open-prep-outcome-backfill.yml"]
)
def test_gpu_priority_cron_workflows_prefer_gpu_self_hosted_selector(workflow_name: str) -> None:
    workflow = yaml.safe_load((_WORKFLOWS_DIR / workflow_name).read_text(encoding="utf-8"))
    resolve_script = _step_run(_jobs(workflow)["select-runner"], "Resolve worker runner")

    assert f'--custom-label "{_GPU_CRON_CUSTOM_LABEL_EXPR}"' in resolve_script


@pytest.mark.parametrize(
    "workflow_name", ["ml-family-research.yml", "rl-research-training.yml"]
)
def test_research_workflows_route_gpu_modes_to_gpu_label(workflow_name: str) -> None:
    # These workflows pick the GPU label conditionally inside a shell `if`
    # branch (mode == 'train' / GPU runs) and otherwise fall back to the
    # priority-cron label, so we pin the GPU branch as a substring rather than
    # the whole `--custom-label` line.
    text = (_WORKFLOWS_DIR / workflow_name).read_text(encoding="utf-8")
    assert f'CUSTOM_LABEL="{_GPU_CRON_CUSTOM_LABEL_EXPR}"' in text, (
        f"{workflow_name} must wire the GPU custom-label branch to "
        f"SMC_PRIORITY_CRON_GPU_SELF_HOSTED_LABEL with cron+generic fallbacks"
    )
    assert '--custom-label "$CUSTOM_LABEL"' in text


# F1.1 — every routed workflow's `select-runner` job should keep a minimal,
# valid permissions block (`contents: read`) and must never declare
# unsupported permission keys (for example `administration`, which is not a
# valid GitHub Actions workflow-permissions key and causes workflow-file
# validation failure before any job starts).
@pytest.mark.parametrize("workflow_name", sorted(_ROUTED_WORKFLOWS))
def test_select_runner_job_permissions_are_valid(workflow_name: str) -> None:
    workflow = yaml.safe_load((_WORKFLOWS_DIR / workflow_name).read_text(encoding="utf-8"))
    select_runner = _jobs(workflow)["select-runner"]
    perms = select_runner.get("permissions")
    assert isinstance(perms, dict), (
        f"{workflow_name}:select-runner must declare an explicit permissions block"
    )
    assert perms.get("contents") == "read", (
        f"{workflow_name}:select-runner must grant `contents: read` for checkout"
    )
    assert "administration" not in perms, (
        f"{workflow_name}:select-runner must not declare `permissions.administration` "
        f"(unsupported key; breaks workflow-file validation)"
    )


# F2.2 — workflows that route to self-hosted and use the portable Python
# bootstrap pattern must gate the `actions/setup-python` action on
# `runner_environment == 'github-hosted'`. Otherwise the hosted-only
# setup-python step would also execute on self-hosted runners and silently
# bypass the `Resolve Python 3.12 interpreter` portable-bootstrap path that
# self-hosted depends on.
_PORTABLE_PYTHON_BOOTSTRAP_WORKFLOWS = (
    "smc-release-gates.yml",
    "smc-library-refresh.yml",
    "smc-databento-production-export.yml",
    "smc-measurement-benchmark.yml",
    "smc-measurement-benchmark-rolling.yml",
)


@pytest.mark.parametrize("workflow_name", _PORTABLE_PYTHON_BOOTSTRAP_WORKFLOWS)
def test_hosted_only_setup_python_step_is_gated_to_github_hosted(workflow_name: str) -> None:
    workflow = yaml.safe_load((_WORKFLOWS_DIR / workflow_name).read_text(encoding="utf-8"))
    jobs = _jobs(workflow)
    routed = _ROUTED_WORKFLOWS[workflow_name]
    found_gated_hosted_step = False
    found_portable_resolver_step = False
    for worker_job_name in routed["worker_jobs"]:
        job = jobs[worker_job_name]
        for step in job.get("steps") or []:
            if not isinstance(step, dict):
                continue
            name = step.get("name") or ""
            uses = step.get("uses") or ""
            cond = step.get("if") or ""
            if name == "Set up pinned Python (GitHub-hosted)":
                assert uses == "./.github/actions/setup-python-pinned", (
                    f"{workflow_name}:{worker_job_name} hosted setup-python must use "
                    f"the pinned composite action"
                )
                assert "needs.select-runner.outputs.runner_environment == 'github-hosted'" in cond, (
                    f"{workflow_name}:{worker_job_name} hosted setup-python is missing "
                    f"the runner_environment guard; got if={cond!r}"
                )
                found_gated_hosted_step = True
            if name == "Resolve Python 3.12 interpreter":
                found_portable_resolver_step = True
    assert found_gated_hosted_step, (
        f"{workflow_name} is missing the gated 'Set up pinned Python (GitHub-hosted)' step"
    )
    assert found_portable_resolver_step, (
        f"{workflow_name} is missing the 'Resolve Python 3.12 interpreter' portable bootstrap step"
    )


def test_ci_validate_coverage_scope_matches_documented_policy() -> None:
    workflow = yaml.safe_load((_WORKFLOWS_DIR / "ci.yml").read_text(encoding="utf-8"))
    validate_steps = _jobs(workflow)["validate"].get("steps") or []

    no_coverage = next(
        step for step in validate_steps
        if step.get("name") == "Run Python tests (PR / non-main push — no coverage)"
    )
    main_coverage = next(
        step for step in validate_steps
        if step.get("name") == "Run Python tests (main push — with coverage)"
    )

    # The PR / non-main `no_coverage` step runs only when the testmon
    # PR-lane is NOT enabled. When `vars.SMC_TESTMON_PR_LANE == 'true'`,
    # the parallel testmon-flavoured step (cached `.testmondata`,
    # different coverage stance) owns the same gate. Without the
    # `!= 'true'` clause both steps would execute the test run twice on
    # every PR.
    assert no_coverage.get("if") == (
        "steps.gate.outputs.run_heavy == 'true' && "
        "(github.event_name == 'pull_request' || github.ref != 'refs/heads/main') && "
        "vars.SMC_TESTMON_PR_LANE != 'true'"
    )
    assert main_coverage.get("if") == (
        "steps.gate.outputs.run_heavy == 'true' && "
        "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    )
