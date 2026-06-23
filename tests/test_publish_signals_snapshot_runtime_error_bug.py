"""Regression test for RuntimeError handling in publish_signals_snapshot.

publish() now catches RuntimeError from _git_diff_has_changes and returns
exit code 2 instead of leaking the exception.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts import publish_signals_snapshot as mod


def test_git_diff_runtime_error_returns_exit_code_2(tmp_path: Path) -> None:
    """RuntimeError from _git_diff_has_changes yields exit code 2."""
    input_path = tmp_path / "latest_realtime_signals.json"
    input_path.write_text("{}", encoding="utf-8")

    def fake_diff(_cwd: Path) -> bool:
        raise RuntimeError("git diff --cached failed (rc=128): simulated")

    with patch.object(mod, "_git_diff_has_changes", side_effect=fake_diff):
        rc = mod.publish(
            input_path, "bot/live-signals-snapshot", "skippALGO/skipp-algo", "tok"
        )
    assert rc == 2
