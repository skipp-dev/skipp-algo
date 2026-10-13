"""F-V7-P1 (2026-05-02) — direct-invoke workflows MUST set PYTHONPATH.

Background — V7 audit finding F-07: 395 ``scripts/*.py`` files (mostly
``plan_2_8_*``) execute ``from scripts.smc_atomic_write import ...`` BEFORE
any ``sys.path.insert(0, REPO_ROOT)``. They work in CI only because every
workflow that direct-invokes them (``python scripts/X.py``, no ``-m``)
declares ``PYTHONPATH: ${{ github.workspace }}`` at workflow / job / step
level.

This pin guarantees that any new workflow which direct-invokes a script
under ``scripts/`` MUST also export ``PYTHONPATH``. Without this guard a
fresh workflow author can ship a green PR (the script's import works
locally because the test harness sets ``PYTHONPATH``) and only discover
the breakage when the cron fires in production.

Repro for the underlying drift:
    unset PYTHONPATH && python scripts/plan_2_8_runcard_index.py --help
    # ModuleNotFoundError: No module named 'scripts'
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = ROOT / ".github" / "workflows"

# Match `python scripts/X.py` but NOT `python -m scripts.X`. Allow optional
# `python3` and intermediate flags (``python -u scripts/X.py``).
_DIRECT_INVOKE_RE = re.compile(
    r"\bpython3?\b(?:\s+-[A-Za-z]+)*\s+scripts/[A-Za-z0-9_]+\.py\b"
)


def _iter_workflow_files() -> list[Path]:
    # F1 (audit 2026-05-02): also match `.yaml` so future renames don't silently bypass this guard.
    return sorted(
        p
        for p in (set(WORKFLOWS_DIR.glob("*.yml")) | set(WORKFLOWS_DIR.glob("*.yaml")))
        if p.is_file()
    )


def _has_pythonpath(env: object) -> bool:
    """Return True if a YAML ``env:`` mapping exports PYTHONPATH (any value)."""
    if not isinstance(env, dict):
        return False
    return any(str(k) == "PYTHONPATH" for k in env)


def _step_exports_pythonpath(step: object) -> bool:
    if not isinstance(step, dict):
        return False
    return _has_pythonpath(step.get("env"))


def _job_exports_pythonpath(job: object) -> bool:
    if not isinstance(job, dict):
        return False
    return _has_pythonpath(job.get("env"))


def _workflow_exports_pythonpath(doc: object) -> bool:
    if not isinstance(doc, dict):
        return False
    return _has_pythonpath(doc.get("env"))


@pytest.mark.parametrize("wf_path", _iter_workflow_files(), ids=lambda p: p.name)
def test_direct_invoke_workflow_sets_pythonpath(wf_path: Path) -> None:
    """Each workflow that direct-invokes ``python scripts/X.py`` exports PYTHONPATH.

    A workflow passes if PYTHONPATH is exported at any of:
    - top-level ``env:`` (workflow scope), OR
    - job-level ``env:`` for the job containing the direct-invoke step, OR
    - step-level ``env:`` for the step itself.

    A workflow that contains zero direct-invoke calls is skipped.
    """
    raw = wf_path.read_text(encoding="utf-8")
    if not _DIRECT_INVOKE_RE.search(raw):
        pytest.skip("no `python scripts/X.py` direct-invoke in this workflow")

    try:
        doc = yaml.safe_load(raw)
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        pytest.fail(f"{wf_path.name}: invalid YAML: {exc}")

    if _workflow_exports_pythonpath(doc):
        return

    jobs = (doc or {}).get("jobs") or {}
    if not isinstance(jobs, dict):
        pytest.fail(f"{wf_path.name}: jobs section is not a mapping")

    offenders: list[str] = []
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps") or []
        if not isinstance(steps, list):
            continue
        # Find every step in this job that contains a direct-invoke run line.
        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            run = step.get("run")
            if not isinstance(run, str) or not _DIRECT_INVOKE_RE.search(run):
                continue
            if _job_exports_pythonpath(job) or _step_exports_pythonpath(step):
                continue
            label = step.get("name") or step.get("id") or f"step[{idx}]"
            offenders.append(f"{job_name}::{label}")

    if offenders:
        joined = "\n  - ".join(offenders)
        pytest.fail(
            f"{wf_path.name}: direct-invoke step(s) without PYTHONPATH "
            f"(workflow / job / step env all missing it):\n  - {joined}\n"
            "Add `PYTHONPATH: ${{ github.workspace }}` to one of those scopes "
            "or invoke the script via `python -m scripts.<module>` instead."
        )
