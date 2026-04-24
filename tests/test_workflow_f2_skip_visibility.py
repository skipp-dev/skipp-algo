"""Pin: F2 promotion-gate "skipped" path emits ``::warning`` (not ``::notice``)
so each skipped daily run is visible in the GitHub Actions summary banner.

Audit follow-up to :file:`docs/reviews/2026-04-24-system-review.md` finding
**L-2** (Klasse #24 + #32, "F2 dual-arm wiring gap"): ``status=skipped`` is
the by-design outcome while F2 dual-arm artifacts are still being produced
upstream, but a silent ``::notice`` would let "stuck on skipped for weeks"
drift go unnoticed. Upgrading to ``::warning`` gives reviewers a per-run
yellow banner without needing an external counter ledger.
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "f2-promotion-gate-daily.yml"
_SKIP_STEP_NAME = "Skip — dual-arm artifacts not yet produced"
_WARNING_RE = re.compile(r"::warning\s+title=f2-promotion-gate-daily")


def test_workflow_file_exists() -> None:
    assert _WORKFLOW.is_file(), f"missing pin target: {_WORKFLOW}"


def test_skip_step_uses_warning_annotation() -> None:
    text = _WORKFLOW.read_text(encoding="utf-8")
    assert _SKIP_STEP_NAME in text, (
        f"expected step name {_SKIP_STEP_NAME!r} in {_WORKFLOW.name} — "
        "pin is anchored on the step that handles the skipped path."
    )
    # Find the body of the skip step (from its name down to the next step).
    lines = text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if _SKIP_STEP_NAME in line), None
    )
    assert start is not None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].lstrip().startswith("- name:"):
            end = j
            break
    body = "\n".join(lines[start:end])
    assert _WARNING_RE.search(body), (
        f"step {_SKIP_STEP_NAME!r} in {_WORKFLOW.name} must emit a "
        "GitHub Actions ``::warning`` (not ``::notice``) so each skipped "
        "run is visible in the run-summary banner. Audit finding L-2 "
        "(Klasse #24 + #32)."
    )
    # Inspect only the executable shell content (drop comment-only lines)
    # so the rationale comment can mention "::notice" without tripping
    # the pin.
    exec_lines = [
        line for line in lines[start:end] if not line.lstrip().startswith("#")
    ]
    exec_body = "\n".join(exec_lines)
    assert "::notice" not in exec_body, (
        f"step {_SKIP_STEP_NAME!r} in {_WORKFLOW.name} must NOT emit "
        "``::notice`` for the skipped path — the audit (L-2) requires "
        "``::warning`` so 'stuck on skipped for weeks' drift surfaces."
    )
