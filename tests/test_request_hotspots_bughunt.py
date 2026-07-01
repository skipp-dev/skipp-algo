"""Bug-hunt tests for services.live_overlay_daemon.request_hotspots.

These tests probe invariants that the existing suite does not cover:
- boundary behaviour of top_n (top_n=0 contract),
- hot-symbol survival under adversarial insertion order,
- thread-safety under racing record/snapshot/reset,
- fuzzing of record_request inputs,
- property-based invariants with hypothesis.
"""
from __future__ import annotations

import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import services.live_overlay_daemon.request_hotspots as hotspots

# ---------------------------------------------------------------------------
# Boundary / contract tests
# ---------------------------------------------------------------------------

def test_snapshot_top_n_zero_returns_empty_lists() -> None:
    """top_n=0 should return zero top symbols/timeframes.

    The current implementation silently clamps top_n to at least 1, which
    breaks the documented contract. This test documents that bug.
    """
    hotspots.reset()
    hotspots.record_request("A", "5m")
    snap = hotspots.snapshot(top_n=0)
    assert snap["top_symbols"] == []
    assert snap["top_tfs"] == []


def test_snapshot_negative_top_n_is_not_silently_clamped_to_one() -> None:
    """Negative top_n must not silently return results."""
    hotspots.reset()
    hotspots.record_request("A", "5m")
    snap = hotspots.snapshot(top_n=-1)
    # A reasonable contract is empty; current code clamps to 1.
    assert snap["top_symbols"] == []
    assert snap["top_tfs"] == []


# ---------------------------------------------------------------------------
# Adversarial insertion order (metamorphic / differential)
# ---------------------------------------------------------------------------

def test_hot_symbol_inserted_after_probe_flood_may_be_evicted() -> None:
    """A hot symbol added *after* a probe flood can be evicted.

    The PR fix evicts least-frequent keys. When every key has count 1,
    Counter.most_common() tie ordering is insertion-order dependent and not
    guaranteed to keep the newest key. This test demonstrates that the
    "hot symbol survives" invariant is fragile if hotness is established late.
    """
    hotspots.reset()

    # Flood with _MAX_TRACKED_KEYS distinct probes, each count=1.
    for i in range(hotspots._MAX_TRACKED_KEYS):
        hotspots.record_request(f"PRB{i:05d}", "5m")

    # Now a legitimate symbol appears once. It has the same count as every probe.
    hotspots.record_request("NVDA", "5m")

    # Push past the cap to trigger eviction.
    for i in range(hotspots._MAX_TRACKED_KEYS, hotspots._MAX_TRACKED_KEYS + 1024):
        hotspots.record_request(f"PRB{i:05d}", "5m")

    snap = hotspots.snapshot(top_n=hotspots._MAX_TRACKED_KEYS)
    symbols = [s for s, _ in snap["top_symbols"]]

    # The contract from PR #3087 implies hot symbols survive, but NVDA has no
    # higher count than any probe. This assertion documents the failure mode.
    assert "NVDA" in symbols, (
        "late-arriving hot symbol with count=1 was evicted despite being the "
        "most recent legitimate request"
    )


def test_repeated_legitimate_symbol_survives_probe_flood() -> None:
    """If the legitimate symbol builds count before the flood, it survives."""
    hotspots.reset()
    for _ in range(200):
        hotspots.record_request("NVDA", "5m")
    for i in range(hotspots._MAX_TRACKED_KEYS * 2):
        hotspots.record_request(f"PRB{i:06d}"[:10], "5m")
    snap = hotspots.snapshot(top_n=5)
    assert ("NVDA", 200) in snap["top_symbols"]


# ---------------------------------------------------------------------------
# Fuzzing of record_request inputs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "symbol,tf",
    [
        ("", "5m"),  # empty after strip
        ("   ", "5m"),  # whitespace-only
        ("A", ""),  # empty timeframe
        ("A", "   "),  # whitespace-only timeframe
        ("A" * 10, "5m"),  # max length
        ("A" * 100, "5m"),  # over length (still records after strip/upper)
        ("lowercase", "5m"),  # normalization
        ("  nvda  ", " 5m "),  # whitespace normalization
        ("\x00SYM", "5m"),  # null byte
        ("SYM\n", "5m"),  # newline
        ("SYM\t", "5m"),  # tab
        ("ΕΛΛΗΝΙΚΑ", "5m"),  # non-ASCII uppercase
        ("日本語", "5m"),  # CJK
        ("🔥", "5m"),  # emoji
        ("1", "5m"),  # single char
    ],
)
def test_record_request_fuzz_does_not_crash(symbol: str, tf: str) -> None:
    """record_request must tolerate extreme/invalid inputs without crashing."""
    hotspots.reset()
    hotspots.record_request(symbol, tf)
    snap = hotspots.snapshot()
    assert isinstance(snap["symbol_count"], int)
    assert isinstance(snap["tf_count"], int)
    assert snap["symbol_count"] >= 0
    assert snap["tf_count"] >= 0


# ---------------------------------------------------------------------------
# Property-based tests (Hypothesis)
# ---------------------------------------------------------------------------

symbol_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "S")),
    min_size=0,
    max_size=15,
)
tf_strategy = st.sampled_from(["1m", "5m", "15m", "1H", "4H", "1D", "", "  ", "5M"])


@given(st.lists(st.tuples(symbol_strategy, tf_strategy), min_size=0, max_size=200))
@settings(max_examples=200, deadline=None)
def test_record_request_count_invariant(records: list[tuple[str, str]]) -> None:
    """Total symbol/timeframe counts are bounded after any input sequence."""
    hotspots.reset()
    for sym, tf in records:
        hotspots.record_request(sym, tf)
    snap = hotspots.snapshot()
    assert snap["symbol_count"] <= hotspots._MAX_TRACKED_KEYS
    assert snap["tf_count"] <= hotspots._MAX_TRACKED_KEYS
    assert all(isinstance(c, int) and c > 0 for _, c in snap["top_symbols"])
    assert all(isinstance(c, int) and c > 0 for _, c in snap["top_tfs"])


@given(st.integers(min_value=-5, max_value=20))
def test_snapshot_top_n_returns_at_most_n_items(top_n: int) -> None:
    """snapshot(top_n) must return at most top_n items when top_n >= 0."""
    hotspots.reset()
    for i in range(10):
        hotspots.record_request(f"S{i}", "5m")
    snap = hotspots.snapshot(top_n=top_n)
    if top_n <= 0:
        assert snap["top_symbols"] == []
        assert snap["top_tfs"] == []
    else:
        assert len(snap["top_symbols"]) <= top_n
        assert len(snap["top_tfs"]) <= top_n


@given(st.lists(st.tuples(symbol_strategy, tf_strategy), min_size=1, max_size=100))
@settings(max_examples=100, deadline=None)
def test_record_request_idempotent_for_same_normalized_input(records: list[tuple[str, str]]) -> None:
    """Recording the same normalized input twice doubles its count but not key count."""
    hotspots.reset()
    for sym, tf in records:
        hotspots.record_request(sym, tf)
    first = hotspots.snapshot(top_n=len(records) + 1)

    for sym, tf in records:
        hotspots.record_request(sym, tf)
    second = hotspots.snapshot(top_n=len(records) + 1)

    assert second["symbol_count"] == first["symbol_count"]
    assert second["tf_count"] == first["tf_count"]

    first_sym_counts = Counter(dict(first["top_symbols"]))
    second_sym_counts = Counter(dict(second["top_symbols"]))
    for sym, count in first_sym_counts.items():
        assert second_sym_counts[sym] == count * 2


# ---------------------------------------------------------------------------
# Race / stress tests
# ---------------------------------------------------------------------------

def test_concurrent_record_and_snapshot_stay_consistent() -> None:
    """Parallel record/snapshot must not crash or return inconsistent counts."""
    hotspots.reset()
    errors: list[BaseException] = []

    def recorder(n: int) -> None:
        try:
            for i in range(n):
                hotspots.record_request(f"T{i % 50}", "5m")
        except BaseException as exc:
            errors.append(exc)

    def snapper(n: int) -> None:
        try:
            for _ in range(n):
                snap = hotspots.snapshot()
                assert snap["symbol_count"] >= 0
                assert snap["tf_count"] >= 0
                assert len(snap["top_symbols"]) <= 5
                assert len(snap["top_tfs"]) <= 5
        except BaseException as exc:
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=6) as pool:
        for _ in range(4):
            pool.submit(recorder, 2000)
        for _ in range(2):
            pool.submit(snapper, 500)

    assert not errors, errors
    snap = hotspots.snapshot()
    assert snap["symbol_count"] <= hotspots._MAX_TRACKED_KEYS
    assert snap["tf_count"] <= 1


def test_concurrent_record_and_reset_does_not_crash() -> None:
    """Racing record and reset must be safe."""
    hotspots.reset()
    errors: list[BaseException] = []

    def recorder() -> None:
        try:
            for i in range(1000):
                hotspots.record_request(f"R{i % 100}", "5m")
        except BaseException as exc:
            errors.append(exc)

    def resetter() -> None:
        try:
            for _ in range(50):
                hotspots.reset()
        except BaseException as exc:
            errors.append(exc)

    t1 = threading.Thread(target=recorder)
    t2 = threading.Thread(target=resetter)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors, errors
    snap = hotspots.snapshot()
    assert snap["symbol_count"] <= hotspots._MAX_TRACKED_KEYS
    assert snap["tf_count"] <= hotspots._MAX_TRACKED_KEYS


# ---------------------------------------------------------------------------
# Stress / determinism
# ---------------------------------------------------------------------------

def test_determinism_for_identical_input_sequence() -> None:
    """Same input sequence must yield the same snapshot (after reset)."""
    sequence = [(f"S{i % 100}", "5m") for i in range(5000)]

    def run() -> dict[str, object]:
        hotspots.reset()
        for sym, tf in sequence:
            hotspots.record_request(sym, tf)
        return hotspots.snapshot(top_n=10)

    first = run()
    second = run()
    assert first == second


def test_distinct_symbol_flood_never_exceeds_max_tracked_keys() -> None:
    """Direct reproduction of the resource-leak bug from PR #3087."""
    hotspots.reset()
    for i in range(50_000):
        hotspots.record_request(f"PRB{i:06d}"[:10], "5m")
    snap = hotspots.snapshot()
    assert snap["symbol_count"] <= hotspots._MAX_TRACKED_KEYS
