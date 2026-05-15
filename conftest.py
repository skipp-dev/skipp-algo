"""Root pytest configuration.

This file is intentionally minimal — it only handles platform-specific
collection guards that cannot be expressed in pyproject.toml addopts.
"""

from __future__ import annotations

import sys

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
