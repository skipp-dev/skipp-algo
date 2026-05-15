"""Tests for ``scripts.ib_client_id`` rotating allocator (C13)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.ib_client_id as ib_client_id
from scripts.ib_client_id import (
    DEFAULT_PREFERRED_RANGE,
    allocate_ib_client_id,
    release_ib_client_id,
)

_REQUIRES_FCNTL = pytest.mark.skipif(
    ib_client_id.fcntl is None,
    reason="POSIX registry locking semantics require fcntl; Windows fallback is covered separately.",
)


def test_allocate_returns_value_in_default_range(tmp_path: Path) -> None:
    cid = allocate_ib_client_id("svc_a", registry_path=tmp_path / "reg.json")
    lo, hi = DEFAULT_PREFERRED_RANGE
    assert lo <= cid <= hi


@_REQUIRES_FCNTL
def test_allocate_skips_already_registered(tmp_path: Path) -> None:
    reg = tmp_path / "reg.json"
    cid_a = allocate_ib_client_id("svc_a", registry_path=reg)
    # Same PID + same service → reuse.
    cid_a_again = allocate_ib_client_id("svc_a", registry_path=reg)
    assert cid_a_again == cid_a
    # Different service but same PID → distinct id.
    cid_b = allocate_ib_client_id("svc_b", registry_path=reg)
    assert cid_b != cid_a


@_REQUIRES_FCNTL
def test_release_removes_entry(tmp_path: Path) -> None:
    reg = tmp_path / "reg.json"
    cid = allocate_ib_client_id("svc_x", registry_path=reg)
    assert release_ib_client_id(cid, registry_path=reg) is True
    data = json.loads(reg.read_text(encoding="utf-8"))
    assert str(cid) not in data


@_REQUIRES_FCNTL
def test_release_nonexistent_id_returns_false(tmp_path: Path) -> None:
    reg = tmp_path / "reg.json"
    allocate_ib_client_id("svc_y", registry_path=reg)
    assert release_ib_client_id(99999, registry_path=reg) is False


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
    cid = allocate_ib_client_id("svc_z", registry_path=reg)
    # The stale slot 40 should have been reaped and reused.
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
