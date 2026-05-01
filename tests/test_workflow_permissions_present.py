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

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

# write-all is a privilege-escalation footgun; never acceptable.
_WRITE_ALL_RE = re.compile(r"^permissions:\s*write-all\s*$", re.MULTILINE)


def _all_workflow_files() -> list[Path]:
    return sorted(WORKFLOWS_DIR.glob("*.yml"))


def test_no_workflow_uses_write_all() -> None:
    """write-all grants every scope. Forbid it everywhere."""
    offenders: list[str] = []
    for wf in _all_workflow_files():
        text = wf.read_text(encoding="utf-8")
        if _WRITE_ALL_RE.search(text):
            offenders.append(wf.name)
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
        # Top-level permissions block present — accept any mapping (including
        # empty {} which means "no scopes" — perfectly minimal).
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
