"""Root pytest configuration.

This file is intentionally minimal — it only handles platform-specific
collection guards that cannot be expressed in pyproject.toml addopts.
"""

from __future__ import annotations

import sys

# scripts/ib_client_id.py imports ``fcntl`` unconditionally at module level.
# ``fcntl`` is a POSIX-only stdlib module and does not exist on Windows.
# Without this guard pytest fails the *collection* phase on Windows with
# "ModuleNotFoundError: No module named 'fcntl'" before any test can run.
collect_ignore = (
    ["tests/test_ib_client_id.py"] if sys.platform == "win32" else []
)
