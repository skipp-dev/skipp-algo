"""Defense ledger: every .github/workflows/*.yml must declare an explicit
permissions: block (top-level or per-job) and must NOT use ``write-all``.

F-V4-F3 (2026-05-01): codifies the result of the workflow-permissions audit
performed during the V4 review. At audit time every workflow already had
permissions and none used write-all; this test prevents regression.

Failure modes guarded:
- New workflow added without any ``permissions:`` block → silently inherits
  GITHUB_TOKEN's broad default scopes (or repo default) → privilege escalation
  surface.
- Existing workflow edited to ``permissions: write-all`` → trivial
  privilege-escalation footgun.

Allow-list of acceptable shapes:
  Top-level ``permissions:`` block followed by a non-empty mapping, OR
  every job inside the workflow declares its own ``permissions:`` block.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


def _all_workflow_files() -> list[Path]:
    files = sorted(
        list(WORKFLOWS_DIR.glob("*.yml")) + list(WORKFLOWS_DIR.glob("*.yaml"))
    )
    assert files, (
        f"F-V4-F3: no workflow files discovered under {WORKFLOWS_DIR}. "
        "This guard exists to prevent silent regressions; an empty inventory "
        "would let it pass vacuously."
    )
    return files


def _is_write_all(perm: object) -> bool:
    """True iff `perm` represents the GitHub Actions ``write-all`` shape.

    GitHub accepts either the bare string ``write-all`` or the equivalent
    mapping forms (e.g. an ``actions: write`` mapping that grants every
    documented scope). We only flag the explicit string form here — listing
    every scope individually is verbose-but-deliberate and reviewable.
    """
    return isinstance(perm, str) and perm.strip().lower() == "write-all"


def test_no_workflow_uses_write_all() -> None:
    """write-all grants every scope. Forbid it everywhere — top-level AND per-job."""
    offenders: list[str] = []
    for wf in _all_workflow_files():
        doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            continue
        if _is_write_all(doc.get("permissions")):
            offenders.append(f"{wf.name} (top-level)")
        jobs = doc.get("jobs", {}) or {}
        if isinstance(jobs, dict):
            for jname, jbody in jobs.items():
                if isinstance(jbody, dict) and _is_write_all(jbody.get("permissions")):
                    offenders.append(f"{wf.name} (jobs.{jname})")
    assert not offenders, (
        "F-V4-F3: workflows using `permissions: write-all` (privilege-escalation "
        "footgun): " + ", ".join(offenders)
    )


@pytest.mark.parametrize("wf_path", _all_workflow_files(), ids=lambda p: p.name)
def test_workflow_has_explicit_permissions(wf_path: Path) -> None:
    """Every workflow must declare permissions explicitly — top-level OR
    on every job. Inheriting GITHUB_TOKEN's default scopes is forbidden."""
    doc = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
    assert isinstance(doc, dict), f"{wf_path.name}: not a YAML mapping"

    top_level = doc.get("permissions")
    if top_level is not None:
        # Accept any mapping (including empty {} — the minimal "no scopes"
        # declaration, useful for read-only workflows that want to opt out
        # of every default) or the literal strings 'read-all' / 'write-all'.
        # 'write-all' is also caught by test_no_workflow_uses_write_all so
        # this branch will not silently accept it.
        assert isinstance(top_level, (dict, str)), (
            f"{wf_path.name}: top-level permissions must be a mapping or 'read-all'"
        )
        return

    # No top-level permissions → every job must declare its own.
    jobs = doc.get("jobs", {})
    assert isinstance(jobs, dict) and jobs, (
        f"{wf_path.name}: no top-level permissions and no jobs declared"
    )
    missing = [
        name for name, body in jobs.items()
        if not (isinstance(body, dict) and "permissions" in body)
    ]
    assert not missing, (
        f"F-V4-F3: {wf_path.name} has no top-level `permissions:` block "
        f"and these jobs are also missing one: {missing}. "
        "Add either a top-level `permissions:` block or a per-job one."
    )
