"""Resolve a Pine file by bare basename across canonical search dirs.

Implements **ADR-0003** (Option B — resolver shim). Lets consumers keep
their bare-basename lookup convention while LEGACY files physically
live under ``pine/legacy/``.

Search order (first hit wins):

1. Repo root (active SMC suite, test fixtures).
2. ``pine/legacy/`` (LEGACY files moved by D-1 v2).

A basename appearing in **both** locations is a configuration error —
resolution raises ``CollisionError`` rather than silently picking one.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# Single source of truth for the LEGACY pine directory location (H-8,
# system review 2026-04-24). All non-test code that needs to address
# this directory MUST import :data:`PINE_LEGACY_DIR` rather than
# rebuilding ``"pine/legacy"`` as a string literal.
PINE_LEGACY_DIR: Path = REPO_ROOT / "pine" / "legacy"
SEARCH_DIRS: tuple[Path, ...] = (REPO_ROOT, PINE_LEGACY_DIR)


class CollisionError(RuntimeError):
    """Raised when the same basename exists in more than one search dir."""


def resolve_pine_file(
    basename: str,
    search_dirs: Sequence[Path] = SEARCH_DIRS,
) -> Path:
    """Return the absolute path of ``basename`` from the first search dir.

    Raises ``FileNotFoundError`` if no search dir contains the file, and
    ``CollisionError`` if more than one search dir contains it.
    """
    if "/" in basename or "\\" in basename:
        raise ValueError(
            f"resolve_pine_file expects a bare basename, got {basename!r}"
        )
    hits = [d / basename for d in search_dirs if (d / basename).is_file()]
    if not hits:
        searched = ", ".join(str(d) for d in search_dirs)
        raise FileNotFoundError(
            f"Pine file {basename!r} not found in any of: {searched}"
        )
    if len(hits) > 1:
        locations = ", ".join(str(p) for p in hits)
        raise CollisionError(
            f"Pine file {basename!r} exists in multiple search dirs: {locations}. "
            "Move or delete the duplicate."
        )
    return hits[0]


def find_collisions(
    search_dirs: Sequence[Path] = SEARCH_DIRS,
) -> dict[str, list[Path]]:
    """Return ``{basename: [paths]}`` for every basename present in >1 dir."""
    by_name: dict[str, list[Path]] = {}
    for d in search_dirs:
        if not d.is_dir():
            continue
        for p in d.glob("*.pine"):
            if p.is_file():
                by_name.setdefault(p.name, []).append(p)
    return {name: paths for name, paths in by_name.items() if len(paths) > 1}
