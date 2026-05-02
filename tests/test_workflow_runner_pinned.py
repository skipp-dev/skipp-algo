"""Pin: every workflow runs on the unified ``SMC_GH_HOSTED_RUNNER`` expression.

V8 audit follow-up (2026-05-02) — F-V8-C3.1 PR C / runner-tier maximization.

Background
----------
GitHub-hosted ``ubuntu-latest-m`` (4 vCPU / 16 GB) is eviction-prone and
caused 12 consecutive Databento producer timeouts. ``ubuntu-latest-l``
(8 vCPU / 32 GB) is the next tier and the new default.

GitHub composite actions cannot abstract ``runs-on:`` (it is a job-level
key, not a step-level key). The closest single-source-of-truth mechanism
GitHub Actions provides is a repo-scoped variable plus a literal fallback.
This test pins **all** workflow jobs to the exact expression::

    runs-on: ${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest-l' }}

so that:

* a future "harmless" `runs-on: ubuntu-latest` (or `-m`) cannot silently
  regress the runner tier or fork the source of truth;
* operators retain a 1-click rollback by setting
  ``vars.SMC_GH_HOSTED_RUNNER`` in repo Settings without touching code;
* a future bump (e.g. ``-xl``) is a single ``sed`` away.

If a workflow legitimately needs a different runner (self-hosted, macOS,
windows, GPU), add it to ``_ALLOWED_OVERRIDES`` with a justification.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOWS_DIR = _REPO_ROOT / ".github" / "workflows"

# The single authoritative ``runs-on:`` expression every job must use.
_PINNED_RUNS_ON = "${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest-l' }}"

# Jobs allowed to opt out of the pinned expression. Map of
# ``workflow_filename -> {job_id: justification}``.
_ALLOWED_OVERRIDES: dict[str, dict[str, str]] = {}


def _workflow_files() -> list[Path]:
    files = sorted(_WORKFLOWS_DIR.glob("*.yml")) + sorted(
        _WORKFLOWS_DIR.glob("*.yaml")
    )
    assert files, f"no workflow files found under {_WORKFLOWS_DIR}"
    return files


def _jobs(workflow: dict) -> dict[str, dict]:
    return {
        job_id: job
        for job_id, job in (workflow.get("jobs") or {}).items()
        if isinstance(job, dict)
    }


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_workflow_runs_on_is_pinned(path: Path) -> None:
    """Every job must use the unified ``runs-on:`` expression."""
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    overrides = _ALLOWED_OVERRIDES.get(path.name, {})
    offenders: list[str] = []
    for job_id, job in _jobs(workflow).items():
        runs_on = job.get("runs-on")
        if job_id in overrides:
            continue
        if runs_on != _PINNED_RUNS_ON:
            offenders.append(f"  {job_id}: runs-on = {runs_on!r}")
    assert not offenders, (
        f"{path.name} has jobs with non-pinned runs-on:\n"
        + "\n".join(offenders)
        + f"\n\nExpected exactly: {_PINNED_RUNS_ON!r}\n"
        "If a different runner is required, add the job to "
        "_ALLOWED_OVERRIDES with a justification."
    )


def test_no_raw_ubuntu_latest_m_literal() -> None:
    """No workflow may pin ``ubuntu-latest-m`` as a literal fallback.

    The audit raised the default to ``ubuntu-latest-l`` after eviction
    incidents. Re-introducing ``-m`` as a literal would silently
    downgrade the tier whenever ``vars.SMC_GH_HOSTED_RUNNER`` is unset.
    """
    offenders: list[str] = []
    for path in _workflow_files():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "ubuntu-latest-m" in line:
                offenders.append(f"  {path.name}:{lineno}: {line.strip()}")
    assert not offenders, (
        "Found ``ubuntu-latest-m`` literal(s) — eviction-prone tier "
        "must not be the default after the V8 audit:\n" + "\n".join(offenders)
    )


def test_no_bare_ubuntu_latest_runs_on() -> None:
    """No job may declare ``runs-on: ubuntu-latest`` (literal).

    Bare ``ubuntu-latest`` bypasses the ``vars.SMC_GH_HOSTED_RUNNER``
    operator override, fragmenting the source of truth.
    """
    offenders: list[str] = []
    for path in _workflow_files():
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        overrides = _ALLOWED_OVERRIDES.get(path.name, {})
        for job_id, job in _jobs(workflow).items():
            if job_id in overrides:
                continue
            if job.get("runs-on") == "ubuntu-latest":
                offenders.append(f"  {path.name}:{job_id}")
    assert not offenders, (
        "Found bare ``runs-on: ubuntu-latest`` (no operator override "
        "hook):\n" + "\n".join(offenders)
    )
