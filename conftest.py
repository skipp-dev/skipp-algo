"""Root pytest configuration.

This file handles:

1. Platform-specific collection guards that cannot be expressed in
   pyproject.toml addopts (Windows ``fcntl``).
2. The ADR-0012 fast/slow auto-marking (Phase 1): every collected test
   item whose file basename is **not** in
   :mod:`tests._fast_inventory` is marked ``pytest.mark.slow`` at
   collection time. This lets developers run ``pytest -m "not slow"``
   locally to approximate the fast-gates set without maintaining
   per-file decorators across ~1000 test files. NOTE (Phase 1): CI
   selection is unchanged — ``fast-gates`` still runs an explicit file
   list and ``validate`` runs the full suite; the marker does not yet
   drive CI job selection.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# scripts/ib_client_id.py and open_prep/realtime_signals.py import ``fcntl``
# unconditionally at module level. ``fcntl`` is a POSIX-only stdlib module
# and does not exist on Windows.  Without this guard pytest fails the
# *collection* phase on Windows with "ModuleNotFoundError: No module named
# 'fcntl'" before any test can run.
#
# test_smoke_v2_features.py also has a transitive fcntl import chain.
collect_ignore = (
    [
        "tests/test_ib_client_id.py",
        "tests/test_realtime_signals_runtime.py",
        "tests/test_realtime_signals_uplift.py",
        "tests/test_realtime_signals_uplift_b.py",
        "tests/test_smoke_v2_features.py",
        # test_dst_fallback_loudness imports open_prep.realtime_signals which
        # unconditionally imports fcntl (POSIX-only) at module level.
        "tests/test_dst_fallback_loudness.py",
    ]
    if sys.platform == "win32"
    else []
)


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Auto-mark non-fast test files as ``slow`` (ADR-0012 Phase 1).

    Membership is sourced from :mod:`tests._fast_inventory`. Items
    already carrying the ``slow`` marker (explicit ``@pytest.mark.slow``
    or module-level ``pytestmark``) are left untouched.
    """
    try:
        from tests._fast_inventory import is_fast
    except ImportError:
        # If the inventory module fails to import we deliberately do
        # NOT mark anything — surfacing the import error via the
        # bucket-discipline test is preferable to silently shifting
        # the partition. Narrowed to ImportError so genuine bugs in the
        # inventory module (SyntaxError, etc.) crash collection loudly
        # instead of being swallowed here.
        return

    slow_marker = pytest.mark.slow
    for item in items:
        # Only consider items physically located under tests/. Items
        # collected from other paths (e.g. doctest plugins) keep their
        # original marker state.
        item_path = getattr(item, "path", None)
        path = Path(item_path) if item_path is not None else Path(str(item.fspath))
        try:
            rel_parts = path.relative_to(Path(__file__).parent).parts
        except ValueError:
            continue
        if not rel_parts or rel_parts[0] != "tests":
            continue
        basename = path.name
        if is_fast(basename):
            continue
        if "slow" in item.keywords:
            continue
        item.add_marker(slow_marker)

