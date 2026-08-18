"""Tests for ``scripts.ib_client_id`` rotating allocator (C13)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.ib_client_id as ib_client_id

_REQUIRES_FCNTL = pytest.mark.skipif(
    ib_client_id.fcntl is None,
    reason="POSIX registry locking semantics require fcntl; Windows fallback is covered separately.",
)


def test_allocate_returns_value_in_default_range(tmp_path: Path) -> None:
    cid = ib_client_id.allocate_ib_client_id("svc_a", registry_path=tmp_path / "reg.json")
    lo, hi = ib_client_id.DEFAULT_PREFERRED_RANGE
    assert lo <= cid <= hi


@_REQUIRES_FCNTL
def test_allocate_skips_already_registered(tmp_path: Path) -> None:
    reg = tmp_path / "reg.json"
    cid_a = ib_client_id.allocate_ib_client_id("svc_a", registry_path=reg)
    # Same PID + same service → reuse.
    cid_a_again = ib_client_id.allocate_ib_client_id("svc_a", registry_path=reg)
    assert cid_a_again == cid_a
    # Different service but same PID → distinct id.
    cid_b = ib_client_id.allocate_ib_client_id("svc_b", registry_path=reg)
    assert cid_b != cid_a


@_REQUIRES_FCNTL
def test_release_removes_entry(tmp_path: Path) -> None:
    reg = tmp_path / "reg.json"
    cid = ib_client_id.allocate_ib_client_id("svc_x", registry_path=reg)
    assert ib_client_id.release_ib_client_id(cid, registry_path=reg) is True
    data = json.loads(reg.read_text(encoding="utf-8"))
    assert str(cid) not in data


@_REQUIRES_FCNTL
def test_release_nonexistent_id_returns_false(tmp_path: Path) -> None:
    reg = tmp_path / "reg.json"
    ib_client_id.allocate_ib_client_id("svc_y", registry_path=reg)
    assert ib_client_id.release_ib_client_id(99999, registry_path=reg) is False


@_REQUIRES_FCNTL
def test_reaps_stale_entry_with_dead_pid(tmp_path: Path) -> None:
    reg = tmp_path / "reg.json"
    # Pre-seed registry with a stale entry pointing to a clearly-dead PID.
    # PID 1 (init) is always alive; pick a guaranteed-unused high PID.
    reg.write_text(
        json.dumps(
            {
                "40": {
                    "service": "ghost",
                    "pid": 9_999_999,
                    "allocated_at": 0.0,
                    "last_seen": 0.0,
                }
            }
        ),
        encoding="utf-8",
    )
    cid = ib_client_id.allocate_ib_client_id("svc_z", registry_path=reg)
    # The stale slot 40 should have been reaped and reused.
    assert cid == 40


def test_live_pid_keeps_its_lease_despite_stale_last_seen(tmp_path: Path) -> None:
    """2026-08-18 (Grenzgaenger B7): a long-running holder allocates once and
    never refreshes last_seen. The old reaper ANDed liveness with last_seen
    freshness, so after 5 minutes the LIVE holder's entry was deleted and its
    id re-handed — IBKR error 326, the collision the registry exists to
    prevent. A live pid now keeps its lease regardless of last_seen age."""
    import os

    reg = tmp_path / "reg.json"
    reg.write_text(
        json.dumps(
            {
                "40": {
                    "service": "long_running_monitor",
                    "pid": os.getpid(),  # alive for the whole test
                    "allocated_at": 0.0,
                    "last_seen": 0.0,  # ancient — way past any timeout
                }
            }
        ),
        encoding="utf-8",
    )
    cid = ib_client_id.allocate_ib_client_id("svc_new", registry_path=reg)
    assert cid != 40
    registry = json.loads(reg.read_text(encoding="utf-8"))
    assert "40" in registry, "live holder's lease must survive the reap"


def test_entry_without_valid_pid_is_reaped_by_last_seen(tmp_path: Path) -> None:
    """Liveness-unknowable entries (missing/invalid pid) fall back to the
    last_seen timeout — and os.kill(-1, 0) is never consulted (it probes the
    whole process group and used to make such entries look alive)."""
    reg = tmp_path / "reg.json"
    reg.write_text(
        json.dumps(
            {
                "40": {
                    "service": "no_pid_recorded",
                    "allocated_at": 0.0,
                    "last_seen": 0.0,
                }
            }
        ),
        encoding="utf-8",
    )
    cid = ib_client_id.allocate_ib_client_id("svc_new", registry_path=reg)
    assert cid == 40


def test_allocate_falls_back_when_fcntl_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Windows/no-fcntl path should stay importable and non-blocking."""
    monkeypatch.setattr(ib_client_id, "fcntl", None)
    monkeypatch.setattr(ib_client_id.random, "randint", lambda lo, hi: hi)

    reg = tmp_path / "reg.json"
    assert ib_client_id.allocate_ib_client_id("svc_win", registry_path=reg) == 99
    assert not reg.exists(), "no-fcntl fallback must not write an unlocked registry"


def test_release_returns_false_when_fcntl_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ib_client_id, "fcntl", None)

    assert ib_client_id.release_ib_client_id(40, registry_path=tmp_path / "reg.json") is False


def test_candidate_scan_excludes_reserved_execution_id() -> None:
    """71 is the pinned execution/incubation default clientId; the ascending
    scan must skip it so an exhausted 40..70 range never falls through to 71."""
    assert 71 in ib_client_id._RESERVED_CLIENT_IDS
    ids = list(ib_client_id._candidate_ids(ib_client_id.DEFAULT_PREFERRED_RANGE))
    assert 71 not in ids
    # Neighbours stay allocatable — only the reserved id is removed.
    assert 70 in ids and 72 in ids


def test_fallback_allocation_never_returns_reserved_71(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The lock-less fallback must not hand out 71 even when the raw draw lands
    on it — otherwise it collides with the pinned-71 incubation/execution
    session (IBKR error 326), the failure this registry exists to prevent."""
    monkeypatch.setattr(ib_client_id, "fcntl", None)
    monkeypatch.setattr(ib_client_id.random, "randint", lambda lo, hi: 71)

    cid = ib_client_id.allocate_ib_client_id("svc_reserved", registry_path=tmp_path / "reg.json")
    assert cid != 71
    lo, hi = ib_client_id.DEFAULT_PREFERRED_RANGE
    assert lo <= cid <= hi
