"""F-V4-D2 (2026-05-01): upload-artifact failure-resilience inventory.

Every ``actions/upload-artifact`` step should either:
  - have ``if: always()`` (or another explicit ``if:`` guard) so artifacts
    survive partial failures and aid postmortem debugging, OR
  - be explicitly listed in :data:`ALLOWED_UNGUARDED` below with rationale
    (typical: published/release artifacts that would mislead consumers
    if uploaded on partial output).

Defense-only: no production behaviour change. Catches new unguarded
upload-artifact sites slipping into the fleet.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"

# Allow-list: workflows whose upload-artifact intentionally relies on
# the default ``if: success()``. Each entry must have a corresponding
# F-V4-D2 intent comment in the workflow itself (grep for F-V4-D2).
ALLOWED_UNGUARDED: frozenset[str] = frozenset({
    "fvg-context-pine-refresh.yml",     # published Pine snippet
    "public-calibration-dashboard.yml", # published calibration report
})


def _has_guard(text_lines: list[str], uses_idx: int) -> bool:
    """Return True iff the upload-artifact step at ``uses_idx`` has an ``if:``.

    The scan is bounded to a single step body: it walks backward to the
    nearest ``- name:`` (or ``- uses:``) at the step indent to find the
    step start, and forward only until the next sibling step opener.
    Spanning past the next step would let a sibling step's ``if:`` mask
    a missing guard on this one.
    """
    line = text_lines[uses_idx]
    m_indent = re.match(r"(\s*)", line)
    uses_indent = len(m_indent.group(1)) if m_indent else 0
    step_indent = uses_indent - 2
    step_opener_re = re.compile(r"^" + (" " * step_indent) + r"-\s+")

    step_start = uses_idx
    for j in range(uses_idx - 1, max(-1, uses_idx - 30), -1):
        l2 = text_lines[j]
        if not l2.strip():
            continue
        if step_opener_re.match(l2):
            step_start = j
            break

    for k in range(step_start, min(len(text_lines), uses_idx + 25)):
        ll = text_lines[k]
        # Stop at next sibling step opener (do NOT span into siblings).
        if k != step_start and step_opener_re.match(ll):
            return False
        mif = re.match(r"\s+if:\s*(.+?)\s*$", ll)
        if mif and ll.startswith(" " * uses_indent):
            return True
    return False


def test_unguarded_upload_artifacts_match_allowlist() -> None:
    workflows = sorted(
        list(WORKFLOWS_DIR.glob("*.yml")) + list(WORKFLOWS_DIR.glob("*.yaml"))
    )
    assert workflows, f"No workflow files discovered under {WORKFLOWS_DIR}"

    actual_unguarded: set[str] = set()
    for wf in workflows:
        text = wf.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(text):
            if not re.search(r"uses:\s*actions/upload-artifact@", line):
                continue
            if not _has_guard(text, i):
                actual_unguarded.add(wf.name)
                break

    extra = actual_unguarded - ALLOWED_UNGUARDED
    missing = ALLOWED_UNGUARDED - actual_unguarded

    assert not extra, (
        "New upload-artifact step(s) missing `if:` guard in: "
        f"{sorted(extra)}. Either add `if: always()` (preferred for "
        "diagnostic artifacts) or add an F-V4-D2 intent comment AND "
        "list the workflow filename in ALLOWED_UNGUARDED in this file "
        "with rationale."
    )
    assert not missing, (
        "ALLOWED_UNGUARDED contains workflows that now HAVE guards: "
        f"{sorted(missing)}. Remove them from the allow-list — it must "
        "stay tight."
    )


def test_allowed_unguarded_workflows_carry_fv4d2_marker() -> None:
    """Each ALLOWED_UNGUARDED entry must include an F-V4-D2 intent
    comment in the workflow file so the rationale travels with the code.
    """
    missing_marker: list[str] = []
    for name in sorted(ALLOWED_UNGUARDED):
        for ext in (".yml", ".yaml"):
            wf = WORKFLOWS_DIR / (name if name.endswith(ext) else name)
            if wf.exists():
                break
        else:
            wf = WORKFLOWS_DIR / name
        assert wf.exists(), f"ALLOWED_UNGUARDED entry not found on disk: {name}"
        if "F-V4-D2" not in wf.read_text(encoding="utf-8"):
            missing_marker.append(name)
    assert not missing_marker, (
        "ALLOWED_UNGUARDED workflow(s) missing the `F-V4-D2` intent "
        f"comment in-file: {missing_marker}. Add a short comment near "
        "the upload-artifact step explaining why the default "
        "`if: success()` is intentional."
    )
