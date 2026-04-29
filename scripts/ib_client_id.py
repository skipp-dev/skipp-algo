"""C13 — Rotating IB client-id allocator (cooperative file registry).

Mirrors the proven pattern from ``~/IB_mon/IB_monitoring/client_id_manager.py``
(in-house IB monitoring service) so this repo's ad-hoc IBKR scripts
(``collect_opening_imbalances``, ``wsh_earnings_calendar`` and any
future C13 jobs) cannot collide with each other or with the long-lived
monitoring service when they share a single TWS / IB Gateway socket.

Key invariants:

* Allocation is **cooperative** via a shared JSON registry file
  (``~/client_id_registry.json``) protected by an exclusive ``flock``.
* Stale entries (PID dead OR last-seen older than ``process_timeout``)
  are reaped on every allocation.
* Default range is ``[40, 99]`` — high enough to dodge the
  monitoring-service ranges (6-15, 25-35, 100-130) but still inside
  the standard IB clientId range.
* Allocation **never blocks** the caller for more than a handful of
  syscalls; if the lock cannot be acquired we fall back to a random
  pick within the preferred range.

Usage::

    from scripts.ib_client_id import allocate_ib_client_id
    cid = allocate_ib_client_id("c13_imbalance")
    ib.connect("127.0.0.1", 7497, clientId=cid)
    try:
        ...
    finally:
        ib.disconnect()
        # Best-effort release; the entry will also be reaped after
        # ``process_timeout`` if we crash before getting here.
        from scripts.ib_client_id import release_ib_client_id
        release_ib_client_id(cid)
"""

from __future__ import annotations

import fcntl
import json
import os
import random
import time
from collections.abc import Iterable
from pathlib import Path
import contextlib

DEFAULT_REGISTRY_PATH = Path.home() / "client_id_registry.json"
DEFAULT_PROCESS_TIMEOUT_SECONDS = 300

# Safe range for ad-hoc C13 jobs; intentionally disjoint from the
# in-house IB monitoring service (uses 6-15, 25-35, 100-130) and from
# the live-execution default (71).
DEFAULT_PREFERRED_RANGE = (40, 99)


def _registry_path() -> Path:
    override = os.environ.get("IB_CLIENT_ID_REGISTRY")
    return Path(override) if override else DEFAULT_REGISTRY_PATH


def _process_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    return True


def _load(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save(path: Path, registry: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        # ATOMIC-WRITE-EXEMPT: tmp+os.replace pattern (lease registry, small dict).
        json.dump(registry, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _reap_stale(
    registry: dict[str, dict], *, timeout_seconds: int
) -> dict[str, dict]:
    now = time.time()
    return {
        cid: info
        for cid, info in registry.items()
        if isinstance(info, dict)
        and _process_alive(info.get("pid", -1))
        and (now - float(info.get("last_seen", 0))) <= timeout_seconds
    }


def _candidate_ids(preferred_range: tuple[int, int]) -> Iterable[int]:
    start, end = preferred_range
    return range(start, end + 1)


def allocate_ib_client_id(
    service_name: str,
    *,
    preferred_range: tuple[int, int] = DEFAULT_PREFERRED_RANGE,
    registry_path: Path | None = None,
    process_timeout_seconds: int = DEFAULT_PROCESS_TIMEOUT_SECONDS,
) -> int:
    """Allocate a unique IB clientId for ``service_name``.

    Returns an int in ``preferred_range``. Falls back to a random pick
    inside the range if the registry file cannot be locked / written.
    """
    path = registry_path or _registry_path()
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        lock_fd = open(lock_path, "w")
    except OSError:
        return random.randint(*preferred_range)

    try:
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return random.randint(*preferred_range)

        registry = _reap_stale(
            _load(path), timeout_seconds=process_timeout_seconds
        )
        pid = os.getpid()

        # Reuse if this PID already holds an entry for the same service.
        for cid_str, info in registry.items():
            if info.get("service") == service_name and info.get("pid") == pid:
                info["last_seen"] = time.time()
                _save(path, registry)
                return int(cid_str)

        for cid in _candidate_ids(preferred_range):
            cid_str = str(cid)
            if cid_str in registry:
                continue
            registry[cid_str] = {
                "service": service_name,
                "pid": pid,
                "allocated_at": time.time(),
                "last_seen": time.time(),
            }
            _save(path, registry)
            return cid

        # All slots taken — reap-then-overwrite the oldest entry.
        oldest_cid_str = min(
            registry,
            key=lambda c: float(registry[c].get("last_seen", 0)),
        )
        registry[oldest_cid_str] = {
            "service": service_name,
            "pid": pid,
            "allocated_at": time.time(),
            "last_seen": time.time(),
        }
        _save(path, registry)
        return int(oldest_cid_str)
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        lock_fd.close()


def release_ib_client_id(
    client_id: int, *, registry_path: Path | None = None
) -> bool:
    """Best-effort release of ``client_id`` from the registry."""
    path = registry_path or _registry_path()
    if not path.exists():
        return False
    lock_path = path.with_suffix(path.suffix + ".lock")
    try:
        lock_fd = open(lock_path, "w")
    except OSError:
        return False
    try:
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        registry = _load(path)
        cid_str = str(client_id)
        if cid_str in registry:
            del registry[cid_str]
            _save(path, registry)
            return True
        return False
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        lock_fd.close()


__all__ = [
    "DEFAULT_PREFERRED_RANGE",
    "allocate_ib_client_id",
    "release_ib_client_id",
]
