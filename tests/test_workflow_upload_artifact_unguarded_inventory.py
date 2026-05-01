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

    The ``if:`` may sit anywhere within the step body at the same indent
    as the ``uses:`` line.
    """
    line = text_lines[uses_idx]
    m_indent = re.match(r"(\s*)", line)
    uses_indent = len(m_indent.group(1)) if m_indent else 0
    step_indent = uses_indent - 2
    step_start = uses_idx
    for j in range(uses_idx - 1, max(-1, uses_idx - 30), -1):
        l2 = text_lines[j]
        if not l2.strip():
            continue
        mi = re.match(r"(\s*)-\s+", l2)
        if mi and len(mi.group(1)) == step_indent:
            step_start = j
            break
    for k in range(step_start, min(len(text_lines), uses_idx + 25)):
        ll = text_lines[k]
        mif = re.match(r"\s+if:\s*(.+?)\s*$", ll)
        if mif and ll.startswith(" " * uses_indent):
            return True
    return False


def test_unguarded_upload_artifacts_match_allowlist() -> None:
    actual_unguarded: set[str] = set()
    for wf in sorted(WORKFLOWS_DIR.glob("*.yml")):
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
