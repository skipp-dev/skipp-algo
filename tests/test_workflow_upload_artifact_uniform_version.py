"""F-V4-B4 (2026-05-01): upload-artifact major-version uniformity ledger.

Every ``uses: actions/upload-artifact@<ref>`` across ``.github/workflows``
must pin to a single major version. Mixed majors mean some jobs run on
the legacy chunked-upload protocol (v4) while others run on the
unique-name-per-run protocol (v5+), which makes ``gh run download``
behavior and artifact-name collisions inconsistent across the fleet.

Frozen target: ``v7`` (corresponds to upload-artifact@v7.0.1, current at
audit time 2026-05-01).

If a future bump is needed, change ``_FROZEN_MAJOR`` in this file in the
SAME PR that updates the workflows. Mixed states are not allowed.

Defense-only — no production behavior change.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"

_FROZEN_MAJOR: str = "v7"

_UPLOAD_RE = re.compile(
    r"uses:\s*actions/upload-artifact@(?P<ref>v\d+(?:\.\d+){0,2})"
)


def _iter_pins() -> list[tuple[Path, int, str]]:
    out: list[tuple[Path, int, str]] = []
    for wf in sorted(WORKFLOWS_DIR.glob("*.yml")):
        for ln, line in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
            m = _UPLOAD_RE.search(line)
            if m:
                out.append((wf, ln, m.group("ref")))
    return out


def test_upload_artifact_pin_is_uniform() -> None:
    pins = _iter_pins()
    assert pins, "expected at least one actions/upload-artifact pin"

    # Each ref should start with the frozen major (allow point releases like v7.0.1).
    bad = [
        f"  {wf.name}:{ln} uses @{ref} (expected @{_FROZEN_MAJOR}*)"
        for wf, ln, ref in pins
        if not (ref == _FROZEN_MAJOR or ref.startswith(f"{_FROZEN_MAJOR}."))
    ]
    assert not bad, (
        f"actions/upload-artifact major-version drift detected. Frozen "
        f"target is @{_FROZEN_MAJOR}. Offending sites:\n"
        + "\n".join(bad)
        + f"\n\nIf the bump is intentional, update _FROZEN_MAJOR in "
        f"tests/test_workflow_upload_artifact_uniform_version.py in the "
        f"same PR."
    )
