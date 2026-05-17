#!/usr/bin/env python3
"""Fail-fast lint: every ``.github/workflows/*.{yml,yaml}`` must set ``PYTHONUNBUFFERED``.

Without ``PYTHONUNBUFFERED=1`` Python stdout/stderr is line-buffered when
attached to a non-tty (the GHA log is one); a long-running pipeline can
run for an hour with **no visible progress** before runner eviction. This
defeats live progress tracking and obscures the root cause when a job
times out.

Accepted shapes:
* top-level ``env: { PYTHONUNBUFFERED: ... }`` (preferred — covers every job)
* every job under ``jobs:`` declares ``env: { PYTHONUNBUFFERED: ... }``

Audit marker: F-V5-A2 / F-CI-O1. OWASP-adjacent (operational visibility).

Exit code 0 on success, 1 on at least one offending workflow. Emits one
``::error file=<path>::`` annotation per failure. Replaces
``tests/test_workflow_pythonunbuffered.py`` with a YAML-aware structural
check (the previous substring scan accepted the string inside any comment).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

_ENV_KEY = "PYTHONUNBUFFERED"


def _env_has_key(env: object) -> bool:
    return isinstance(env, dict) and _ENV_KEY in env


def _top_level_env_has_key(workflow: dict[str, Any]) -> bool:
    return _env_has_key(workflow.get("env"))


def _every_job_env_has_key(workflow: dict[str, Any]) -> tuple[bool, list[str]]:
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        return False, []
    missing = [
        job_id
        for job_id, job in jobs.items()
        if not (isinstance(job, dict) and _env_has_key(job.get("env")))
    ]
    return (not missing), missing


def _check_one(path: Path) -> str | None:
    rel = path.relative_to(REPO_ROOT).as_posix()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return f"::error file={rel}::YAML parse error: {exc}"
    if not isinstance(data, dict):
        return f"::error file={rel}::workflow does not parse as a mapping"
    if _top_level_env_has_key(data):
        return None
    ok, missing = _every_job_env_has_key(data)
    if ok:
        return None
    if not missing:
        return (
            f"::error file={rel}::missing top-level `env.{_ENV_KEY}` and "
            "no jobs found to fall back on"
        )
    return (
        f"::error file={rel}::missing top-level `env.{_ENV_KEY}` and these "
        f"jobs do not declare it: {missing}"
    )


def main() -> int:
    if not WORKFLOWS_DIR.is_dir():
        print(f"::error::workflows directory not found: {WORKFLOWS_DIR}", file=sys.stderr)
        return 1

    files = sorted(WORKFLOWS_DIR.glob("*.yml")) + sorted(WORKFLOWS_DIR.glob("*.yaml"))
    failures = 0
    for path in files:
        msg = _check_one(path)
        if msg is not None:
            print(msg)
            failures += 1

    if failures:
        print(
            f"\nlint_workflow_pythonunbuffered: {failures} workflow(s) without "
            f"explicit `env.{_ENV_KEY}` declaration.",
            file=sys.stderr,
        )
        return 1

    print(f"OK: {len(files)} workflow(s) declare `env.{_ENV_KEY}`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
