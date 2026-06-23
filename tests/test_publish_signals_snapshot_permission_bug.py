"""Regression test for PermissionError handling in publish_signals_snapshot.

publish() now catches PermissionError when reading an unreadable input file
and returns exit code 1 instead of leaking the exception.
"""

from __future__ import annotations

import os
from pathlib import Path

from scripts import publish_signals_snapshot as mod


def test_publish_unreadable_input_returns_exit_code_1(tmp_path: Path) -> None:
    """PermissionError is caught and converted to exit code 1."""
    input_path = tmp_path / "latest_realtime_signals.json"
    input_path.write_text("{}", encoding="utf-8")
    os.chmod(input_path, 0o000)
    try:
        rc = mod.publish(
            input_path, "bot/live-signals-snapshot", "skippALGO/skipp-algo", "tok"
        )
        assert rc == 1
    finally:
        os.chmod(input_path, 0o644)
