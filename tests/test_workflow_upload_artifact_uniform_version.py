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

# Match every actions/upload-artifact reference, whatever the ref shape
# (vN, vN.M, vN.M.P, branch, or 40-char SHA pin). The previous regex
# silently skipped SHA-pinned references and let drift through.
_UPLOAD_RE = re.compile(
    r"uses:\s*actions/upload-artifact@(?P<ref>[A-Za-z0-9._\-]+)"
)
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _iter_workflow_files() -> list[Path]:
    if not WORKFLOWS_DIR.is_dir():
        return []
    # Mirror tests/test_gha_action_allowlist.py: include both .yml and .yaml.
    return sorted(
        p for p in WORKFLOWS_DIR.iterdir()
        if p.is_file() and p.suffix in (".yml", ".yaml")
    )


def _iter_pins() -> list[tuple[Path, int, str]]:
    out: list[tuple[Path, int, str]] = []
    for wf in _iter_workflow_files():
        for ln, line in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
            m = _UPLOAD_RE.search(line)
            if m:
                out.append((wf, ln, m.group("ref")))
    return out


def _ref_is_on_frozen_major(ref: str) -> bool:
    if ref == _FROZEN_MAJOR or ref.startswith(f"{_FROZEN_MAJOR}."):
        return True
    # SHA pins are intentionally rejected here: a SHA hides which major
    # the action resolves to, defeating the point of this ledger. If a
    # SHA pin is ever required (e.g. for a security advisory), update
    # this test in the SAME PR with an explicit allow-list mapping
    # SHA -> major and assert membership.
    return False


def test_upload_artifact_pin_is_uniform() -> None:
    pins = _iter_pins()
    assert pins, "expected at least one actions/upload-artifact pin"

    bad = []
    for wf, ln, ref in pins:
        if _ref_is_on_frozen_major(ref):
            continue
        if _SHA_RE.match(ref):
            bad.append(
                f"  {wf.name}:{ln} uses @{ref} (SHA pin — explicit allow-list "
                f"required in this test before merging)"
            )
        else:
            bad.append(
                f"  {wf.name}:{ln} uses @{ref} (expected @{_FROZEN_MAJOR}*)"
            )

    assert not bad, (
        f"actions/upload-artifact major-version drift detected. Frozen "
        f"target is @{_FROZEN_MAJOR}. Offending sites:\n"
        + "\n".join(bad)
        + f"\n\nIf the bump is intentional, update _FROZEN_MAJOR in "
        f"tests/test_workflow_upload_artifact_uniform_version.py in the "
        f"same PR."
    )
