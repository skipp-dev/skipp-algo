"""Pin the hybrid runner contract for merge-critical and priority cron workflows.

Hybrid strategy (2026-05-15)
----------------------------
Most workflows stay on the hosted runner expression::

    runs-on: ${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest' }}

The merge-critical workflows (`ci.yml`, `docs-lint.yml`,
`manifest-pytest-poison-scan.yml`, `smc-fast-pr-gates.yml`) and the
priority cron workflows backing Databento / Open Prep / live news refresh
are special:

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
_ROUTED_WORKFLOWS = {
    "ci.yml": {"worker_jobs": {"validate"}},
    "docs-lint.yml": {"worker_jobs": {"inline-backticks"}},
    "manifest-pytest-poison-scan.yml": {"worker_jobs": {"scan"}},
    "ml-family-research.yml": {"worker_jobs": {"research"}},
    "smc-fast-pr-gates.yml": {"worker_jobs": {"fast-gates"}},
    "feature-importance-daily.yml": {"worker_jobs": {"feature-importance-report"}},
    "open-prep-outcome-backfill.yml": {"worker_jobs": {"backfill"}},
    "rl-research-training.yml": {"worker_jobs": {"research"}},
    "run-open-prep-daily.yml": {"worker_jobs": {"run"}},
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
