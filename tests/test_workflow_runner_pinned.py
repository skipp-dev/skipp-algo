"""Defense ledger: forbid floating ``runs-on: ubuntu-latest`` (or any
``-latest`` runner alias) in .github/workflows/*.yml.

F-V4-H2 (2026-05-01): pinning to a concrete runner image (e.g.
``ubuntu-24.04``) makes CI reproducible, prevents silent breakage when
GitHub flips the meaning of ``-latest``, and gives change-control over
runner-image upgrades.

Allowed shapes:
  - ``runs-on: ubuntu-24.04`` / ``ubuntu-22.04`` / ``ubuntu-20.04``
  - ``runs-on: <self-hosted-label>``
  - matrix-driven runs-on whose values are all pinned
Disallowed:
  - ``runs-on: ubuntu-latest`` / ``windows-latest`` / ``macos-latest``
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

# Match `runs-on: <something>-latest` anywhere in a yml line.
_LATEST_RE = re.compile(
    r"runs-on:\s*['\"]?(?P<image>[A-Za-z0-9_-]+-latest)['\"]?",
)


def test_no_workflow_uses_latest_runner_alias() -> None:
    """No workflow may pin to a floating ``-latest`` runner image."""
    offenders: list[str] = []
    for wf in sorted(WORKFLOWS_DIR.glob("*.yml")):
        for lineno, line in enumerate(
            wf.read_text(encoding="utf-8").splitlines(), start=1
        ):
            m = _LATEST_RE.search(line)
            if m:
                offenders.append(f"{wf.name}:{lineno} {m.group('image')}")
    assert not offenders, (
        "F-V4-H2: floating runner-image aliases found (pin to a concrete "
        "version like ubuntu-24.04):\n  " + "\n  ".join(offenders)
    )
