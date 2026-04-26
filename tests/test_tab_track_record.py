"""Tests for terminal_tabs.tab_track_record (C7/T3)."""

from __future__ import annotations

from terminal_tabs.tab_track_record import (
    GATE_BADGE,
    build_summary,
    format_variant_row,
)


def test_gate_badge_pinned_emojis() -> None:
    # Downstream consumers (and screenshots) depend on these — pin.
    assert GATE_BADGE == {
        "green": "🟢",
        "amber": "🟡",
        "red": "🔴",
        "unknown": "⚪",
    }


def test_build_summary_empty_payload_returns_empty_block() -> None:
    out = build_summary(None)
    assert out["status"] == "empty"
    assert out["rows"] == []
    assert out["totals"]["total"] == 0


def test_build_summary_no_variants_returns_empty_block() -> None:
    out = build_summary({"variants": [], "as_of_date": "2026-04-26"})
    assert out["status"] == "empty"
    assert out["as_of_date"] == "2026-04-26"


def test_build_summary_three_variants_counts_gates() -> None:
    payload = {
        "as_of_date": "2026-04-26",
        "variants": [
            {"variant": "a", "gate_status": "green", "n_trades": 100, "sharpe": 1.5},
            {"variant": "b", "gate_status": "amber", "n_trades": 50, "sharpe": 0.7},
            {"variant": "c", "gate_status": "red", "n_trades": 20, "sharpe": -0.3},
        ],
    }
    out = build_summary(payload)
    assert out["status"] == "ok"
    assert out["as_of_date"] == "2026-04-26"
    assert out["totals"] == {
        "green": 1, "amber": 1, "red": 1, "unknown": 0, "total": 3,
    }
    assert len(out["rows"]) == 3


def test_build_summary_unknown_status_buckets_unknown() -> None:
    payload = {
        "variants": [
            {"variant": "x", "gate_status": "weird"},
            {"variant": "y"},  # missing gate_status entirely
        ],
    }
    out = build_summary(payload)
    assert out["totals"]["unknown"] == 2
    assert out["totals"]["total"] == 2


def test_build_summary_red_failures_surfaced() -> None:
    payload = {
        "variants": [
            {
                "variant": "a",
                "gate_status": "red",
                "gate_failures": ["sharpe_below_min", "n_below_min"],
            },
            {"variant": "b", "gate_status": "green"},
        ],
    }
    out = build_summary(payload)
    assert out["red_failures"] == [
        {"variant": "a", "failures": ["sharpe_below_min", "n_below_min"]},
    ]


def test_build_summary_warnings_pass_through() -> None:
    payload = {"variants": [], "warnings": ["missing: psr_mintrl"]}
    out = build_summary(payload)
    assert out["warnings"] == ["missing: psr_mintrl"]


def test_format_variant_row_handles_missing_fields() -> None:
    row = format_variant_row({"variant": "a"})
    assert row["variant"] == "a"
    assert row["n"] is None
    assert row["sharpe"] is None
    assert row["gate_status"] == "unknown"


def test_format_variant_row_coerces_numeric_strings() -> None:
    row = format_variant_row(
        {
            "variant": "a",
            "n_trades": "120",
            "sharpe": "1.42",
            "permutation_p_value": "0.018",
        },
    )
    assert row["n"] == 120
    assert row["sharpe"] == 1.42
    assert row["permutation_p"] == 0.018


def test_format_variant_row_filters_nan() -> None:
    row = format_variant_row({"variant": "a", "sharpe": float("nan")})
    assert row["sharpe"] is None


def test_build_summary_is_deterministic() -> None:
    payload = {
        "variants": [
            {"variant": "a", "gate_status": "green", "sharpe": 1.0, "n_trades": 50},
        ],
    }
    a = build_summary(payload)
    b = build_summary(payload)
    assert a == b
