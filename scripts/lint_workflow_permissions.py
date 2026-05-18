#!/usr/bin/env python3
"""Fail-fast lint: every ``.github/workflows/*.{yml,yaml}`` must declare ``permissions``.

GitHub Actions defaults ``GITHUB_TOKEN`` to **write** permissions on
``contents``, ``issues``, ``pull-requests``, ``checks`` etc. when the repo
setting "Workflow permissions" is left at the permissive default. A
compromised dependency action can then push code, delete branches, or
dismiss reviews. Defense: every workflow opts into least-privilege via a
``permissions:`` block — either at the **top level** (preferred) or on
**every job** (acceptable for jobs needing different scopes).

OWASP A05 (Security Misconfiguration) + supply-chain hardening.

Exit code 0 on success, 1 on at least one offending workflow. Emits one
``::error file=<path>::`` annotation per failure so GitHub surfaces them
inline. Replaces ``tests/test_workflow_permissions_pin.py`` with a
YAML-aware structural check that runs in the fast-PR-gates job (sub-second).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


def _has_permissions(node: object) -> bool:
    return isinstance(node, dict) and "permissions" in node


def _every_job_has_permissions(workflow: dict[str, Any]) -> tuple[bool, list[str]]:
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        return False, []
    missing = [
        job_id
        for job_id, job in jobs.items()
        if not (isinstance(job, dict) and "permissions" in job)
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
    if _has_permissions(data):
        return None
    ok, missing = _every_job_has_permissions(data)
    if ok:
        return None
    if not missing:
        return (
            f"::error file={rel}::missing top-level `permissions:` block and "
            "no jobs found to fall back on"
        )
    return (
        f"::error file={rel}::missing top-level `permissions:` and these "
        f"jobs do not declare their own: {missing}"
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
            f"\nlint_workflow_permissions: {failures} workflow(s) without "
            "explicit `permissions:` declaration.",
            file=sys.stderr,
        )
        return 1

    print(f"OK: {len(files)} workflow(s) declare explicit `permissions:`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
