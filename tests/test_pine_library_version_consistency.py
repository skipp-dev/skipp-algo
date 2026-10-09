"""Pine library version-skew gate.

Phase-6 / Bug-Class #16 from ``smc-system-review-2026-04-24.md``:
``import preuss_steffen/<lib>/<N>`` declarations across all ``*.pine``
files must agree on the major version ``N`` per library. A skew (e.g.
half the consumers on ``smc_utils/1`` and the other half on
``smc_utils/2``) ships silently and produces inconsistent on-chart
behaviour because TradingView resolves each script independently.

The current repo is **clean** (every active library is at major ``/1``).
This test locks that invariant in so the next library bump must update
ALL consumers in the same PR.

Scope:
* ``*.pine`` files anywhere in the repo, **except** ``pine/legacy/``
  (legacy scripts may import older majors by design — see ADR-0003 /
  PINE_LEGACY.md) and test fixtures under ``tests/fixtures/``.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# ``import preuss_steffen/smc_utils/1 as u``
# ``import preuss_steffen/smc_utils/1       as u``
_IMPORT_RE = re.compile(
    r"^\s*import\s+(?P<owner>[A-Za-z0-9_]+)/"
    r"(?P<lib>[A-Za-z0-9_]+)/(?P<ver>\d+)\s+as\s+\w+",
    re.MULTILINE,
)

_SKIP_PATH_PARTS = frozenset({"legacy", "fixtures"})


def _iter_pine_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*.pine"):
        rel_parts = path.relative_to(REPO_ROOT).parts
        if any(part in _SKIP_PATH_PARTS for part in rel_parts):
            continue
        if ".venv" in rel_parts or "node_modules" in rel_parts:
            continue
        files.append(path)
    return files


def _collect_imports() -> dict[tuple[str, str], dict[str, list[str]]]:
    """Returns {(owner, lib): {version: [file_posix, ...]}}."""
    imports: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for path in _iter_pine_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        for m in _IMPORT_RE.finditer(text):
            key = (m.group("owner"), m.group("lib"))
            imports[key][m.group("ver")].append(rel)
    return imports


def test_pine_library_imports_agree_on_major_version() -> None:
    """Pin: every (owner, library) pair has exactly one major version
    across all active ``*.pine`` files.
    """
    imports = _collect_imports()
    skews: list[str] = []
    for (owner, lib), version_map in sorted(imports.items()):
        if len(version_map) <= 1:
            continue
        details = "; ".join(
            f"v{v}: {len(files)} consumer(s) ({', '.join(sorted(files)[:3])}"
            f"{'...' if len(files) > 3 else ''})"
            for v, files in sorted(version_map.items())
        )
        skews.append(f"{owner}/{lib} → {details}")
    assert not skews, (
        "Pine library version-skew detected (Phase-6 / Bug-Class #16):\n"
        + "\n".join(f"  {s}" for s in skews)
        + "\n\nFix: bump ALL consumers in the same PR via "
        "``scripts/bump_pine_library_import.sh`` so the major version "
        "stays consistent across the chart workspace."
    )


def test_sweep_finds_known_imports() -> None:
    """Sanity: at least one known library import is enumerated, so a
    refactor that breaks ``_iter_pine_files`` cannot silently turn this
    suite into a no-op.
    """
    imports = _collect_imports()
    assert imports, (
        "Pine library import sweep returned empty — _iter_pine_files "
        "may be excluding too much, or the regex no longer matches the "
        "active import syntax."
    )
    keys = set(imports.keys())
    expected_at_least_one = {
        ("preuss_steffen", "smc_utils"),
        ("preuss_steffen", "smc_micro_profiles_generated"),
        ("preuss_steffen", "skipp_math"),
    }
    assert keys & expected_at_least_one, (
        f"Pine import sweep enumerated {sorted(keys)} but none of the "
        f"known library names {sorted(expected_at_least_one)} appear. "
        "Has the import syntax changed (owner namespace, version slot)?"
    )
