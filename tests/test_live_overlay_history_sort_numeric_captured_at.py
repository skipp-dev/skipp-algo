"""Regression tests: `_parse_history_lines` sorts numeric `captured_at` chronologically.

Bug-hunt finding on the merged experiment-history path: `_parse_history_lines`
sorted rows with `key=lambda r: str(r.get("captured_at", ""))`. A numeric Unix
timestamp `captured_at` — which the parser tolerates and which the consumer
`_experiment_history_run_date` already handles — was therefore ordered
LEXICALLY (`"1000"` sorts before `"99"`). Mixed-magnitude numeric timestamps
then rendered out of order in Grafana and the `max_days` tail-slice retained the
wrong rows. ISO-8601 strings (the normal Plan 2.8 archive format) are unaffected
because they already sort chronologically as text.
"""
from __future__ import annotations

import json

import services.live_overlay_daemon.compute as compute


def _body(captured_ats: list[object]) -> str:
    return "\n".join(json.dumps({"captured_at": c}) for c in captured_ats)


def test_parse_history_lines_sorts_numeric_captured_at_chronologically() -> None:
    rows = compute._parse_history_lines(_body([100, 99, 1000]), max_days=10)
    assert [r["captured_at"] for r in rows] == [99, 100, 1000]


def test_parse_history_lines_max_days_keeps_newest_after_numeric_sort() -> None:
    # Buggy lexical sort kept ["1000", "99"] → [1000, 99]; correct is [100, 1000].
    rows = compute._parse_history_lines(_body([100, 99, 1000]), max_days=2)
    assert [r["captured_at"] for r in rows] == [100, 1000]


def test_parse_history_lines_sorts_realistic_unix_seconds() -> None:
    # Same-magnitude timestamps sorted right even lexically; lock in the behaviour.
    rows = compute._parse_history_lines(
        _body([1700000200, 1700000000, 1700000100]), max_days=10
    )
    assert [r["captured_at"] for r in rows] == [1700000000, 1700000100, 1700000200]


def test_parse_history_lines_sorts_iso_strings_chronologically() -> None:
    rows = compute._parse_history_lines(
        _body(["2026-04-21T00:00:00Z", "2026-04-19T00:00:00Z", "2026-04-20T00:00:00Z"]),
        max_days=10,
    )
    assert [r["captured_at"] for r in rows] == [
        "2026-04-19T00:00:00Z",
        "2026-04-20T00:00:00Z",
        "2026-04-21T00:00:00Z",
    ]


def test_history_sort_key_numeric_orders_by_value_not_lexically() -> None:
    assert compute._history_sort_key({"captured_at": 99}) < compute._history_sort_key(
        {"captured_at": 1000}
    )
    # bool is not treated as a numeric timestamp; non-finite falls back to text.
    assert compute._history_sort_key({"captured_at": True})[0] == 1
    assert compute._history_sort_key({"captured_at": float("inf")})[0] == 1
    # Missing captured_at never raises.
    assert compute._history_sort_key({})[0] == 1
