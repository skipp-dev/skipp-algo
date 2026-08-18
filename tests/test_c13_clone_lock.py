"""Contract tests for the publishing-clone lock (Grenzgaenger B8, 2026-08-18).

Every C13 launchd driver shares ONE publishing clone whose self-heal path is
``rm -rf``. With the commercial campaign a ~6x/day writer next to the nightly
chain, two concurrent drivers could interleave — one wiping the clone while
the other stages into it. ``lib_c13_data_push.sh`` therefore serialises all
clone access behind a mkdir lock (the atomic primitive available on stock
macOS, which has no flock(1)) with a staleness expiry so a crashed holder can
never deadlock the chain.

The tests drive the shell functions directly via ``bash`` like
``test_c13_launchd_catchup.py`` does for its sibling helper.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB = REPO_ROOT / "automation" / "launchd" / "lib_c13_data_push.sh"


def _run_bash(snippet: str, *, env_prefix: str = "") -> subprocess.CompletedProcess[str]:
    script = f'set -uo pipefail\n{env_prefix}\nsource "{LIB}"\n{snippet}'
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_lib_sources_cleanly() -> None:
    assert _run_bash(":").returncode == 0


def test_lock_acquire_and_release_roundtrip(tmp_path: Path) -> None:
    clone = tmp_path / "clone"
    result = _run_bash(
        "_c13_acquire_clone_lock && test -d \"$(_c13_clone_lock_path)\" "
        "&& _c13_release_clone_lock && test ! -e \"$(_c13_clone_lock_path)\"",
        env_prefix=f'export C13_DATA_CLONE_DIR="{clone}"',
    )
    assert result.returncode == 0, result.stderr


def test_held_lock_times_out_with_degraded_marker(tmp_path: Path) -> None:
    """A concurrently held lock must fail the push FAST with a
    machine-readable degraded marker — never wait forever, never proceed
    into the clone underneath the other driver."""
    clone = tmp_path / "clone"
    lock = tmp_path / "clone.lock"
    lock.mkdir()
    # Fresh holder stamp: NOT stale, so the waiter has to time out.
    (lock / "acquired_at").write_text(
        _run_bash("date +%s").stdout.strip() + "\n"
    )
    marker = tmp_path / ".push_status_2026-08-18"
    result = _run_bash(
        f'push_to_data_branch "subject" "{marker}" "some-file"; echo "rc=$?"',
        env_prefix=(
            f'export C13_DATA_CLONE_DIR="{clone}"\n'
            "export C13_CLONE_LOCK_WAIT_SECS=2"
        ),
    )
    assert result.returncode == 0, result.stderr
    assert "rc=1" in result.stdout
    assert marker.read_text().startswith("degraded:clone-lock-timeout:")


def test_stale_lock_is_broken_and_acquired(tmp_path: Path) -> None:
    """A crashed holder must not deadlock the chain: a lock older than the
    staleness expiry is removed and re-acquired."""
    clone = tmp_path / "clone"
    lock = tmp_path / "clone.lock"
    lock.mkdir()
    (lock / "acquired_at").write_text("100\n")  # epoch 1970 — ancient
    result = _run_bash(
        "_c13_acquire_clone_lock && cat \"$(_c13_clone_lock_path)/holder_pid\"",
        env_prefix=(
            f'export C13_DATA_CLONE_DIR="{clone}"\n'
            "export C13_CLONE_LOCK_WAIT_SECS=5"
        ),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().isdigit()
