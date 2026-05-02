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
  Top-level ``permissions:`` followed by EITHER a mapping (possibly empty
  ``{}`` for the explicit "no scopes" declaration) OR one of the GitHub
  Actions string literals ``read-all`` / ``write-all`` (``write-all`` is
  separately rejected by ``test_no_workflow_uses_write_all``), OR every
  job inside the workflow declares its own ``permissions:`` block whose
  value is itself a mapping or one of the same string literals.

Arbitrary string values (e.g. typos like ``read``) are rejected — they
would otherwise pass this guard and only fail at workflow-run time.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

# GitHub Actions only accepts these two string literals as permissions values.
# Any other string (typo, partial value) is invalid YAML for the actions schema
# and would fail at workflow-run time. We reject them here at lint time.
_ALLOWED_PERMISSION_STRINGS = frozenset({"read-all", "write-all"})


def _is_valid_permissions_value(perm: object) -> bool:
    """True iff ``perm`` is a shape GitHub Actions accepts for ``permissions:``.

    Accepts: any mapping (including ``{}``), or one of the string literals
    ``read-all`` / ``write-all``. Rejects: ``None``, arbitrary strings, lists,
    numbers — all of which the Actions runtime would reject.
    """
    if isinstance(perm, dict):
        return True
    if isinstance(perm, str):
        return perm.strip().lower() in _ALLOWED_PERMISSION_STRINGS
    return False


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
        # this branch will not silently accept it. Arbitrary strings like
        # 'read' (a common typo for 'read-all') are rejected here so they
        # don't slip through and only fail at workflow-run time.
        assert _is_valid_permissions_value(top_level), (
            f"F-V4-F3: {wf_path.name} top-level `permissions:` value "
            f"{top_level!r} is invalid. Must be a mapping (possibly `{{}}`) "
            f"or one of {sorted(_ALLOWED_PERMISSION_STRINGS)!r}."
        )
        return

    # No top-level permissions → every job must declare its own AND each
    # per-job value must itself be a valid permissions shape (a bare
    # `permissions:` with a null value would pass a presence-only check
    # but is invalid for the Actions runtime).
    jobs = doc.get("jobs", {})
    assert isinstance(jobs, dict) and jobs, (
        f"{wf_path.name}: no top-level permissions and no jobs declared"
    )
    missing: list[str] = []
    invalid: list[str] = []
    for name, body in jobs.items():
        if not (isinstance(body, dict) and "permissions" in body):
            missing.append(name)
            continue
        if not _is_valid_permissions_value(body["permissions"]):
            invalid.append(f"{name}={body['permissions']!r}")
    assert not missing, (
        f"F-V4-F3: {wf_path.name} has no top-level `permissions:` block "
        f"and these jobs are also missing one: {missing}. "
        "Add either a top-level `permissions:` block or a per-job one."
    )
    assert not invalid, (
        f"F-V4-F3: {wf_path.name} per-job `permissions:` value(s) invalid: "
        f"{invalid}. Must be a mapping (possibly `{{}}`) or one of "
        f"{sorted(_ALLOWED_PERMISSION_STRINGS)!r}."
    )
