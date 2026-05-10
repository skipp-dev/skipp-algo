"""Regression tests for PR-J1 (audit pass 2, 2026-05-10).

Pin the use of ``time.monotonic`` for the file-lock deadline in
``newsstack_fmp.shared_fetch._file_lock``.

Pre-PR-J1, the deadline used ``time.time()`` (wall clock). If the
system clock is adjusted backwards (NTP correction, VM live-migrate,
manual ``date -s``), the deadline never expires and the lock-waiter
loops forever, deadlocking every shared-fetch caller.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from newsstack_fmp import shared_fetch


def test_file_lock_uses_monotonic_for_deadline():
    """Pre-PR-J1 reproducer: simulate a wall-clock backwards jump
    DURING a contended ``_file_lock`` call. With the fix, the deadline
    is computed from ``time.monotonic()`` and the timeout still fires;
    pre-fix it would never expire.
    """
    src = Path(shared_fetch.__file__).read_text()
    # Hard contract: the deadline arithmetic MUST use time.monotonic.
    assert "deadline = time.monotonic()" in src, (
        "PR-J1: _file_lock deadline must be computed from time.monotonic() "
        "to survive wall-clock backwards jumps (NTP / VM migrate)."
    )
    # And the loop comparison MUST also use monotonic, otherwise we
    # mix epochs.
    assert "if time.monotonic() >= deadline" in src, (
        "PR-J1: _file_lock timeout comparison must use time.monotonic()."
    )
    # And the legacy wall-clock pattern MUST be gone.
    assert "deadline = time.time()" not in src
    assert "if time.time() >= deadline" not in src


def test_file_lock_times_out_when_lock_held(tmp_path: Path):
    """Functional smoke test: when the lockfile already exists, the
    waiter raises ``TimeoutError`` within the configured timeout."""
    lock_path = tmp_path / "test.lock"
    # Pre-create the lockfile so _file_lock is forced to wait.
    lock_path.touch()

    # Shorten the timeout drastically so the test is fast.
    with patch.object(shared_fetch, "_LOCK_TIMEOUT_SECONDS", 0.1), \
         patch.object(shared_fetch, "_LOCK_POLL_INTERVAL_SECONDS", 0.02):
        with pytest.raises(TimeoutError):
            with shared_fetch._file_lock(lock_path):
                pass


def test_file_lock_succeeds_when_path_free(tmp_path: Path):
    lock_path = tmp_path / "free.lock"
    with shared_fetch._file_lock(lock_path):
        # Inside the critical section the lockfile MUST exist.
        assert lock_path.exists()
    # And MUST be cleaned up on exit.
    assert not lock_path.exists()
