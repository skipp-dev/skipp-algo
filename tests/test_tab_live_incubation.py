"""Tests for terminal_tabs.tab_live_incubation (C7/T6)."""

from __future__ import annotations

from terminal_tabs.tab_live_incubation import (
    VERDICT_BADGE,
    build_live_view,
    format_live_row,
)


def test_verdict_badge_pinned() -> None:
    # Locked vocabulary so C8 cannot drift the schema silently.
    assert set(VERDICT_BADGE) == {
        "pass",
        "acceptable",
        "concerning",
        "fail",
        "insufficient_sample",
    }


def test_build_live_view_none_payload_awaits_c8() -> None:
    out = build_live_view(None)
    assert out["status"] == "awaiting_c8"
    assert "Live-Inkubation startet in Sprint C8" in out["notice"]
    assert out["rows"] == []


def test_build_live_view_no_variants_awaits_c8() -> None:
    out = build_live_view({"variants": []})
    assert out["status"] == "awaiting_c8"


def test_build_live_view_with_variants_returns_ok() -> None:
    payload = {
        "computed_at": "2026-04-26T13:30:00+00:00",
        "live_window_days": 90,
        "variants": [
            {
                "variant": "v1",
                "live_sharpe": 0.71,
                "backtest_sharpe": 0.93,
                "n_live_trades": 24,
                "verdict": "acceptable",
            },
        ],
    }
    out = build_live_view(payload)
    assert out["status"] == "ok"
    assert out["live_window_days"] == 90
    assert out["totals"]["acceptable"] == 1
    assert out["totals"]["total"] == 1
    assert out["rows"][0]["variant"] == "v1"
    assert out["rows"][0]["drift_pp"] == 0.71 - 0.93


def test_format_live_row_drift_pp_none_when_either_missing() -> None:
    row = format_live_row({"variant": "v1", "live_sharpe": 0.5})
    assert row["drift_pp"] is None
    row = format_live_row({"variant": "v1", "backtest_sharpe": 0.5})
    assert row["drift_pp"] is None


def test_format_live_row_default_verdict_when_missing() -> None:
    row = format_live_row({"variant": "v1"})
    assert row["verdict"] == "insufficient_sample"


def test_format_live_row_unknown_verdict_buckets_insufficient() -> None:
    payload = {
        "variants": [{"variant": "v", "verdict": "weird_value"}],
    }
    out = build_live_view(payload)
    assert out["totals"]["insufficient_sample"] == 1


def test_build_live_view_is_deterministic() -> None:
    payload = {
        "variants": [
            {"variant": "v", "live_sharpe": 0.5, "backtest_sharpe": 0.6, "verdict": "pass"},
        ],
    }
    a = build_live_view(payload)
    b = build_live_view(payload)
    assert a == b
