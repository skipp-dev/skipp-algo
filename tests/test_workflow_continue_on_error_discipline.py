"""Pin: every ``continue-on-error: true`` step must declare intent.

Audit follow-up to :file:`docs/reviews/2026-04-24-system-review.md` finding
**M-1** (Klasse #24, "``continue-on-error`` als pass"): silent skip wirkt wie
pass, wenn kein nachgelagerter Erfolgs-Check existiert. Statt für jeden Step
einen externen Check zu erzwingen (manche sind legitime best-effort
notifications, optionale artifact downloads, advisory measurement runs)
fordert dieser Pin nur **eine sichtbare Begründung** im YAML — das macht
neue silent-skip-Hinzufügungen reviewer-zwingend.

Konvention: innerhalb von ±5 Zeilen über/unter ``continue-on-error: true``
muss ein Kommentar der Form

    # CONTINUE-ON-ERROR-INTENTIONAL: <Begründung>

stehen. Die Begründung ist freier Text (mindestens ein non-whitespace token).
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW_DIR = _REPO_ROOT / ".github" / "workflows"

# Marker comment that flags an intentional silent-skip. Format must match the
# convention in the module docstring above. The trailing ``\S`` ensures we
# don't accept an empty marker.
_MARKER_RE = re.compile(r"#\s*CONTINUE-ON-ERROR-INTENTIONAL:\s*\S")
_PROXIMITY_LINES = 5


def _iter_workflow_files() -> list[Path]:
    return sorted(
        list(_WORKFLOW_DIR.glob("*.yml")) + list(_WORKFLOW_DIR.glob("*.yaml"))
    )


def test_every_continue_on_error_has_intent_marker() -> None:
    violations: list[str] = []
    for path in _iter_workflow_files():
        lines = path.read_text(encoding="utf-8").splitlines()
        for idx, line in enumerate(lines):
            if "continue-on-error: true" not in line:
                continue
            stripped = line.lstrip()
            # Skip occurrences inside YAML comments (rare but possible in
            # commented-out templates).
            if stripped.startswith("#"):
                continue
            lo = max(0, idx - _PROXIMITY_LINES)
            hi = min(len(lines), idx + _PROXIMITY_LINES + 1)
            window = lines[lo:hi]
            if not any(_MARKER_RE.search(w) for w in window):
                violations.append(f"{path.name}:{idx + 1}")
    assert not violations, (
        "Each `continue-on-error: true` step must have an inline marker "
        "`# CONTINUE-ON-ERROR-INTENTIONAL: <reason>` within ±"
        f"{_PROXIMITY_LINES} lines so reviewers know the silent skip is "
        "by design (audit finding M-1, Klasse #24).\n"
        "Violations:\n  " + "\n  ".join(violations)
    )


def test_workflows_dir_has_files_to_scan() -> None:
    # Sanity: avoid silently passing if the workflow dir disappears.
    assert _iter_workflow_files(), (
        f"No workflow files found under {_WORKFLOW_DIR} — pin would silently "
        "pass."
    )
