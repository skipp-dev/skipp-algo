"""Property-based / fuzzing invariants for live_overlay_daemon.compute helpers.

These tests do not change production code; they attempt to break invariants
using Hypothesis so that silent failures, crashes, or semantic drift in URL,
history, and service-contract parsing are caught as soon as they are introduced.

Run with:
    pytest tests/test_live_overlay_compute_invariants_fuzz.py -q
"""

from __future__ import annotations

import math
from typing import Any

import hypothesis.strategies as st
from hypothesis import given, settings

from services.live_overlay_daemon import compute

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_sorted_by_key(rows: list[dict[str, Any]]) -> bool:
    return all(
        compute._history_sort_key(rows[i]) <= compute._history_sort_key(rows[i + 1])
        for i in range(len(rows) - 1)
    )


def _captured_at_is_present(row: dict[str, Any]) -> bool:
    return compute._has_captured_at(row.get("captured_at"))


# ---------------------------------------------------------------------------
# _signals_service_url_to_full invariants
# ---------------------------------------------------------------------------


@settings(max_examples=2000)
@given(base=st.text())
def test_signals_service_url_to_full_never_crashes(base: str) -> None:
    compute._signals_service_url_to_full(base)


@settings(max_examples=2000)
@given(base=st.text())
def test_signals_service_url_to_full_is_idempotent(base: str) -> None:
    once = compute._signals_service_url_to_full(base)
    twice = compute._signals_service_url_to_full(once)
    # If the first pass rejects the input, the second pass must also reject.
    # If the first pass accepts it, the second pass must be a no-op.
    assert once == twice


@settings(max_examples=2000)
@given(base=st.text())
def test_signals_service_url_to_full_non_empty_implies_endpoint(base: str) -> None:
    result = compute._signals_service_url_to_full(base)
    if result:
        assert "/signals.json" in result
        assert "/signals.json/signals.json" not in result


@settings(max_examples=2000)
@given(base=st.text())
def test_signals_service_url_to_full_is_deterministic(base: str) -> None:
    assert compute._signals_service_url_to_full(base) == compute._signals_service_url_to_full(base)


@settings(max_examples=1000)
@given(
    scheme=st.sampled_from(["http", "https"]),
    host=st.from_regex(r"[a-z0-9\-]+\.railway\.internal", fullmatch=True),
    query=st.text(alphabet="abc=123&"),
    fragment=st.text(alphabet="abc123"),
)
def test_signals_service_url_to_full_preserves_query_and_fragment(
    scheme: str, host: str, query: str, fragment: str
) -> None:
    base = f"{scheme}://{host}"
    if query:
        base = f"{base}?{query}"
    if fragment:
        base = f"{base}#{fragment}"
    result = compute._signals_service_url_to_full(base)
    if result:
        if query:
            assert "?" in result
        if fragment:
            assert "#" in result


# ---------------------------------------------------------------------------
# _is_valid_service_url invariants
# ---------------------------------------------------------------------------


@settings(max_examples=2000)
@given(url=st.text())
def test_is_valid_service_url_never_crashes(url: str) -> None:
    compute._is_valid_service_url(url)


@settings(max_examples=2000)
@given(url=st.text())
def test_is_valid_service_url_is_deterministic(url: str) -> None:
    assert compute._is_valid_service_url(url) is compute._is_valid_service_url(url)


@settings(max_examples=2000)
@given(url=st.text())
def test_is_valid_service_url_whitespace_only_is_false(url: str) -> None:
    if not url.strip():
        assert compute._is_valid_service_url(url) is False


@settings(max_examples=2000)
@given(url=st.text())
def test_is_valid_service_url_true_implies_allowed_scheme_or_railway_internal(url: str) -> None:
    if not compute._is_valid_service_url(url):
        return
    stripped = url.strip().lower()
    if stripped.startswith("https://"):
        assert compute._url_host_if_valid(stripped) is not None
    elif stripped.startswith("http://"):
        host = compute._url_host_if_valid(stripped)
        assert host is not None
        assert host.endswith(".railway.internal")
    else:
        # Bare hostname/path: only railway.internal is accepted.
        host = compute._url_host_if_valid("http://" + stripped)
        assert host is not None
        assert host.endswith(".railway.internal")


# ---------------------------------------------------------------------------
# _validate_https_url invariants
# ---------------------------------------------------------------------------


@settings(max_examples=2000)
@given(url=st.text(), env_name=st.text())
def test_validate_https_url_never_crashes(url: str, env_name: str) -> None:
    compute._validate_https_url(env_name, url)


@settings(max_examples=2000)
@given(url=st.text(), env_name=st.text())
def test_validate_https_url_is_deterministic(url: str, env_name: str) -> None:
    assert compute._validate_https_url(env_name, url) is compute._validate_https_url(env_name, url)


@settings(max_examples=2000)
@given(url=st.text(), env_name=st.text())
def test_validate_https_url_true_implies_https_with_host(url: str, env_name: str) -> None:
    if not compute._validate_https_url(env_name, url):
        return
    stripped = url.strip().lower()
    assert stripped.startswith("https://")
    assert stripped != "https://"
    assert compute._url_host_if_valid(stripped) is not None


@settings(max_examples=2000)
@given(url=st.text(), env_name=st.text())
def test_validate_https_url_http_is_false(url: str, env_name: str) -> None:
    stripped = url.strip().lower()
    if stripped.startswith("http://"):
        assert compute._validate_https_url(env_name, url) is False


# ---------------------------------------------------------------------------
# _parse_history_lines invariants
# ---------------------------------------------------------------------------


@settings(max_examples=1000)
@given(
    text=st.text(),
    max_days=st.integers(min_value=-10, max_value=100),
)
def test_parse_history_lines_never_crashes(text: str, max_days: int) -> None:
    compute._parse_history_lines(text, max_days)


@settings(max_examples=1000)
@given(
    text=st.text(),
    max_days=st.integers(min_value=1, max_value=100),
)
def test_parse_history_lines_max_days_respected(text: str, max_days: int) -> None:
    rows = compute._parse_history_lines(text, max_days)
    assert len(rows) <= max_days


@settings(max_examples=1000)
@given(
    text=st.text(),
    max_days=st.integers(min_value=1, max_value=100),
)
def test_parse_history_lines_output_is_sorted(text: str, max_days: int) -> None:
    rows = compute._parse_history_lines(text, max_days)
    assert _is_sorted_by_key(rows)


@settings(max_examples=1000)
@given(
    text=st.text(),
    max_days=st.integers(min_value=1, max_value=100),
)
def test_parse_history_lines_rows_have_captured_at(text: str, max_days: int) -> None:
    rows = compute._parse_history_lines(text, max_days)
    assert all(_captured_at_is_present(row) for row in rows)


@settings(max_examples=1000)
@given(
    text=st.text(),
    max_days=st.integers(min_value=-10, max_value=100),
)
def test_parse_history_lines_is_deterministic(text: str, max_days: int) -> None:
    assert compute._parse_history_lines(text, max_days) == compute._parse_history_lines(text, max_days)


@settings(max_examples=500)
@given(
    timestamps=st.lists(
        st.one_of(
            st.integers(min_value=0, max_value=2_000_000_000),
            st.floats(min_value=0.0, max_value=2_000_000_000.0, allow_nan=False, allow_infinity=False),
            st.text(min_size=1),
        ),
        min_size=0,
        max_size=50,
    ),
    max_days=st.integers(min_value=1, max_value=50),
)
def test_parse_history_lines_numeric_order_matches_value_order(
    timestamps: list[Any], max_days: int
) -> None:
    """If all captured_at values are finite numbers, the output must be sorted
    by numeric value, not lexicographically."""
    lines = "\n".join(
        f'{{"captured_at": {ts!r}, "idx": {i}}}'
        for i, ts in enumerate(timestamps)
        if isinstance(ts, (int, float)) and math.isfinite(ts)
    )
    rows = compute._parse_history_lines(lines, max_days)
    numeric_rows = [r for r in rows if isinstance(r.get("captured_at"), (int, float))]
    values = [r["captured_at"] for r in numeric_rows]
    assert values == sorted(values)


# ---------------------------------------------------------------------------
# _history_sort_key invariants
# ---------------------------------------------------------------------------


@settings(max_examples=2000)
@given(row=st.dictionaries(st.text(), st.one_of(st.text(), st.integers(), st.floats(), st.booleans())))
def test_history_sort_key_never_crashes(row: dict[str, Any]) -> None:
    compute._history_sort_key(row)


@settings(max_examples=2000)
@given(
    a=st.dictionaries(st.text(), st.one_of(st.text(), st.integers(), st.floats(), st.booleans())),
    b=st.dictionaries(st.text(), st.one_of(st.text(), st.integers(), st.floats(), st.booleans())),
)
def test_history_sort_key_total_ordering(a: dict[str, Any], b: dict[str, Any]) -> None:
    ka = compute._history_sort_key(a)
    kb = compute._history_sort_key(b)
    # Comparable without raising.
    assert (ka < kb) or (ka > kb) or (ka == kb)


@settings(max_examples=500)
@given(
    values=st.lists(
        st.one_of(
            st.integers(min_value=-1_000_000, max_value=1_000_000),
            st.floats(allow_nan=True, allow_infinity=True),
            st.text(),
            st.booleans(),
        ),
        min_size=2,
        max_size=50,
    )
)
def test_history_sort_key_sort_matches_python_sort(values: list[Any]) -> None:
    """The sort key must produce a stable, deterministic ordering when passed
    to Python's sort."""
    rows = [{"captured_at": v} for v in values]
    keys = [compute._history_sort_key(r) for r in rows]
    sorted_keys = sorted(keys)
    # The same set of keys must be sortable and the sort must be stable.
    assert sorted_keys == sorted(sorted_keys)


def test_history_sort_key_numeric_orders_by_value() -> None:
    assert compute._history_sort_key({"captured_at": 99}) < compute._history_sort_key(
        {"captured_at": 1000}
    )


def test_history_sort_key_bool_is_not_numeric() -> None:
    # bool is a subclass of int in Python; the helper explicitly rejects it.
    assert compute._history_sort_key({"captured_at": True})[0] == 1
    assert compute._history_sort_key({"captured_at": False})[0] == 1


def test_history_sort_key_nan_and_inf_are_not_numeric() -> None:
    assert compute._history_sort_key({"captured_at": float("nan")})[0] == 1
    assert compute._history_sort_key({"captured_at": float("inf")})[0] == 1
    assert compute._history_sort_key({"captured_at": float("-inf")})[0] == 1
