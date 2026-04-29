"""Mtime-free artifact resolution for production hot paths.

Audit follow-up to system review 2026-04-24 (finding **H-3**).

Why
---
``Path.stat().st_mtime`` is fragile for "pick the newest artifact":

* On a CI runner the order in which two artifacts get touched is racy
  when they're produced in parallel — the workflow author intended the
  one with the later embedded timestamp to win, but mtime can disagree.
* ``rsync``/``cp -p`` preserve mtime; a file copied later may end up
  *older* by mtime than a file written from scratch yesterday.
* On macOS HFS+ the resolution is 1 second; two files in the same
  pipeline tick get equal mtimes and ``sorted()`` falls back to whatever
  order the filesystem returned them in (not name order).
* A clock skew on the writer machine silently swaps "newest" semantics.

The convention across this repo is to embed an ISO-style timestamp in
the filename (``YYYYMMDD_HHMMSSZ`` for backend artifacts,
``YYYY-MM-DDTHH-MM-SS-mmmZ`` for TradingView reports/screenshots).
This module exposes deterministic helpers that key off that filename
token instead of mtime — and fall back to the lexicographic filename
itself, which is stable across runs.

Usage
-----
::

    from scripts.smc_artifact_resolver import latest_by_filename_iso

    manifest = latest_by_filename_iso(
        export_dir.glob("databento_*_manifest.json")
    )
    if manifest is None:
        raise RuntimeError("no manifest found")

::

    from scripts.smc_artifact_resolver import sorted_by_filename_iso

    for candidate in sorted_by_filename_iso(directory.glob(pattern)):
        ...  # newest first, deterministic across runs
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

# Match either ``YYYYMMDD_HHMMSS[Z]`` (backend artifacts) or
# ``YYYY-MM-DDTHH-MM-SS-mmmZ`` (TradingView/automation reports).
_ISO_TOKEN_RE = re.compile(
    r"(\d{8}T\d{6}Z?)"                        # 20260405T080817Z
    r"|(\d{8}_\d{6}Z?)"                       # 20260405_080817 / 20260405_080817Z
    r"|(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}Z)"  # 2026-04-04T05-11-50-564Z
    r"|(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z?)"       # 2026-04-04T05-11-50Z
    r"|(\d{4}-\d{2}-\d{2})",                          # 2026-04-04
)


def _filename_sort_key(path: Path) -> tuple[str, str]:
    """Return ``(iso_token, name)`` — the deterministic sort key.

    ``iso_token`` is the empty string when no recognised timestamp is in
    the filename; this keeps unstamped files stable but ranks them below
    stamped ones under ``reverse=True`` ordering. The token is normalised
    by stripping a trailing ``Z`` so ``20260405_080817`` and
    ``20260405_080817Z`` (which represent the same instant — UTC is
    implied by repo convention) sort as a single equivalence class.
    """
    name = path.name
    match = _ISO_TOKEN_RE.search(name)
    token = match.group(0) if match else ""
    if token.endswith("Z"):
        token = token[:-1]
    return (token, name)


def sorted_by_filename_iso(
    paths: Iterable[Path],
    *,
    reverse: bool = True,
) -> list[Path]:
    """Sort ``paths`` by the ISO timestamp embedded in their filename.

    Newest-first by default (``reverse=True``). Files with no recognised
    timestamp sort *after* stamped ones (i.e. last when reverse=True).
    Ties in the timestamp are broken by ``Path.name``.
    """
    return sorted(paths, key=_filename_sort_key, reverse=reverse)


def latest_by_filename_iso(paths: Iterable[Path]) -> Path | None:
    """Return the newest path by filename ISO timestamp, or ``None``.

    Equivalent to ``next(iter(sorted_by_filename_iso(paths)), None)``
    but slightly faster since it avoids materialising the full list.
    """
    best: Path | None = None
    best_key: tuple[str, str] | None = None
    for path in paths:
        key = _filename_sort_key(path)
        if best_key is None or key > best_key:
            best = path
            best_key = key
    return best
