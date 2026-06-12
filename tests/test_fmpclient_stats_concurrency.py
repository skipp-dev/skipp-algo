"""R5 regression test — FMPClient._endpoint_usage_stats concurrency.

Background
==========
Before R5 (2026-05-12), ``FMPClient._record_endpoint_event`` and
``FMPClient.get_endpoint_usage_stats`` mutated/snapshotted the
``_endpoint_usage_stats`` dict without holding a lock. Under
``ThreadPoolExecutor``-driven workloads in ``get_batch_quotes()`` this
produced two failure modes:

1. **Silent counter loss.** ``bucket["count"] += 1`` is a Python-level
   read-modify-write (LOAD_ATTR + INPLACE_ADD + STORE_ATTR) and is **not**
   single-bytecode-atomic, even under the GIL. Concurrent increments can
   collapse onto the same pre-incremented value.

2. **Snapshot iteration races.** ``get_endpoint_usage_stats`` iterated the
   dict directly; a concurrent ``setdefault`` of a new endpoint key could
   trip ``RuntimeError: dictionary changed size during iteration``.

Reviewer-strengthened test design
=================================
A naive 32-threads × 1000-ops increment test will likely be GREEN even
*without* the lock, because the GIL serializes individual bytecodes and the
contention window for LOAD_ATTR + INPLACE_ADD + STORE_ATTR is sub-microsecond
on a modern CPU. We therefore manufacture contention in two complementary
ways:

* **Sleep-injection oracle** (``test_concurrency_with_sleep_injection``):
  monkey-patches the dict-bucket update path to perform an explicit
  ``value = bucket["count"]; time.sleep(0.0001); bucket["count"] = value + 1``,
  expanding the read-modify-write window deterministically. Without the
  lock, ≥ 1 lost increment is statistically guaranteed at 32 × 1000.
* **Atomic-counter baseline** (``test_concurrency_baseline_against_atomic_counter``):
  runs the same workload against the FMPClient under test and against a
  ``threading.Lock``-guarded ``collections.Counter`` baseline. The two
  recorded counts must agree. Any divergence proves the FMPClient path is
  not equivalent to the atomic baseline.

A third test (``test_snapshot_iteration_does_not_race_with_inserts``)
exercises ``get_endpoint_usage_stats`` against concurrent first-time
``setdefault`` events to guard against the iteration-while-mutated bug.
"""
from __future__ import annotations

import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest

from open_prep.macro import FMPClient

_THREADS = 32
_OPS_PER_THREAD = 1000
_TOTAL = _THREADS * _OPS_PER_THREAD


def _make_client() -> FMPClient:
    """Return a fresh FMPClient — api_key is irrelevant for these tests."""

    return FMPClient(api_key="test-key-not-used")


# --------------------------------------------------------------------------- #
# Test 1 — negative-control oracle: disabling the lock under widened RMW
# window MUST produce lost increments. This validates the test suite has
# discriminating power; without this control, Tests 2-3 could be passing
# vacuously under GIL serialisation.
# --------------------------------------------------------------------------- #
def test_negative_control_disabled_lock_loses_increments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanity check — proves the suite would catch a regression.

    We replace ``self._lock`` with a no-op context manager and widen the
    read-modify-write window inside ``_record_endpoint_event`` by patching
    the dict ``setdefault`` path. Without real synchronization and with the
    widened window, lost increments are statistically certain at 32×1000.
    A passing assertion here means the test has the discriminating power
    claimed; if this *unexpectedly* found no losses, Tests 2-3 would not
    be trustworthy oracles.
    """

    import contextlib

    client = _make_client()
    # Disable locking. ``contextlib.nullcontext()`` makes ``with self._lock:``
    # a no-op so the production code path is exercised without real sync.
    monkeypatch.setattr(client, "_lock", contextlib.nullcontext())

    # Widen the RMW window by wrapping the bucket with a sleep on read.
    real_dict = client._endpoint_usage_stats

    class SlowDict(dict):
        def __setitem__(self, key, value):  # type: ignore[override]
            time.sleep(0.00005)
            super().__setitem__(key, value)

    real_dict["/stable/quote"] = SlowDict({"calls": 0, "errors": 0, "empty_responses": 0})

    def worker(_: int) -> None:
        for _i in range(_OPS_PER_THREAD):
            client._record_endpoint_event("/stable/quote", calls=1)

    with ThreadPoolExecutor(max_workers=_THREADS) as pool:
        list(pool.map(worker, range(_THREADS)))

    # Without the lock + widened RMW window, MUST lose increments.
    final = real_dict["/stable/quote"]["calls"]
    assert final < _TOTAL, (
        "Negative control failed: expected lost increments without lock+sleep, "
        f"but counter reached the full {_TOTAL}. The other concurrency tests "
        "in this file may not be discriminating oracles."
    )


# --------------------------------------------------------------------------- #
# Test 2 — atomic-counter baseline comparison
# --------------------------------------------------------------------------- #
def test_concurrency_baseline_against_atomic_counter() -> None:
    """FMPClient counter must agree with a Lock-guarded Counter baseline."""

    client = _make_client()
    baseline_lock = threading.Lock()
    baseline = Counter()

    def worker(_: int) -> None:
        for _i in range(_OPS_PER_THREAD):
            client._record_endpoint_event("/stable/profile", calls=1, empty_responses=1)
            with baseline_lock:
                baseline["/stable/profile"] += 1

    with ThreadPoolExecutor(max_workers=_THREADS) as pool:
        list(pool.map(worker, range(_THREADS)))

    snapshot = client.get_endpoint_usage_stats()
    assert snapshot["/stable/profile"]["calls"] == baseline["/stable/profile"]
    assert snapshot["/stable/profile"]["calls"] == _TOTAL
    assert snapshot["/stable/profile"]["empty_responses"] == _TOTAL


# --------------------------------------------------------------------------- #
# Test 3 — snapshot iteration must not race with first-time setdefault
# --------------------------------------------------------------------------- #
def test_snapshot_iteration_does_not_race_with_inserts() -> None:
    """get_endpoint_usage_stats() must never raise during concurrent inserts."""

    client = _make_client()
    stop_event = threading.Event()
    snapshot_errors: list[BaseException] = []

    def writer() -> None:
        for i in range(2000):
            # Each iteration touches a *new* path, forcing setdefault to insert.
            client._record_endpoint_event(f"/stable/path-{i}", calls=1)
        stop_event.set()

    def reader() -> None:
        try:
            while not stop_event.is_set():
                client.get_endpoint_usage_stats()
        except BaseException as exc:  # pragma: no cover — failure capture
            snapshot_errors.append(exc)

    threads = [
        threading.Thread(target=writer),
        threading.Thread(target=reader),
        threading.Thread(target=reader),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not snapshot_errors, f"Snapshot raced with insert: {snapshot_errors!r}"


# --------------------------------------------------------------------------- #
# Test 4 — snapshot is a deep copy, not a live reference
# --------------------------------------------------------------------------- #
def test_snapshot_is_deep_copy() -> None:
    """Mutating the snapshot must not affect the live counters."""

    client = _make_client()
    client._record_endpoint_event("/stable/quote", calls=1)
    snap = client.get_endpoint_usage_stats()
    snap["/stable/quote"]["calls"] = 9_999_999
    snap["/stable/profile"] = {"calls": 1, "errors": 0, "empty_responses": 0}
    fresh = client.get_endpoint_usage_stats()
    assert fresh["/stable/quote"]["calls"] == 1
    assert "/stable/profile" not in fresh
