"""C13/T2 — drift-history panel projection tests."""

from __future__ import annotations

from terminal_tabs.tab_live_incubation import (
    DRIFT_HISTORY_DEFAULT_N,
    build_drift_history_view,
    format_drift_history_row,
)


def _artifact(date: str, variants: list[dict] | None = None) -> dict:
    return {
        "as_of_date": date,
        "computed_at": f"{date}T16:30:00Z",
        "live_window_days": 30,
        "variants": variants if variants is not None else [],
    }


def _v(name: str, verdict: str = "pass", live_sharpe: float = 1.0) -> dict:
    return {
        "variant": name,
        "live_sharpe": live_sharpe,
        "backtest_sharpe": 1.0,
        "n_live_trades": 50,
        "verdict": verdict,
    }


def test_format_drift_history_row_counts_verdicts() -> None:
    art = _artifact(
        "2026-04-28",
        variants=[
            _v("a", "pass"),
            _v("b", "acceptable"),
            _v("c", "concerning"),
            _v("d", "fail"),
            _v("e", "insufficient_sample"),
        ],
    )
    row = format_drift_history_row(art)
    assert row["as_of_date"] == "2026-04-28"
    assert row["computed_at"] == "2026-04-28T16:30:00Z"
    assert row["live_window_days"] == 30
    assert row["n_variants"] == 5
    assert row["n_pass"] == 1
    assert row["n_acceptable"] == 1
    assert row["n_concerning"] == 1
    assert row["n_fail"] == 1
    assert row["n_insufficient_sample"] == 1
    assert row["n_failing"] == 2  # fail + concerning


def test_format_drift_history_row_handles_no_variants() -> None:
    row = format_drift_history_row(_artifact("2026-04-28"))
    assert row["n_variants"] == 0
    assert row["n_failing"] == 0


def test_format_drift_history_row_missing_as_of_date_blank() -> None:
    row = format_drift_history_row({"variants": []})
    assert row["as_of_date"] == ""


def test_format_drift_history_row_ignores_non_mapping_variant() -> None:
    art = {"as_of_date": "2026-04-28", "variants": [_v("a"), "garbage", None, _v("b")]}
    row = format_drift_history_row(art)
    assert row["n_variants"] == 2


def test_build_drift_history_view_empty_returns_awaiting() -> None:
    view = build_drift_history_view(None)
    assert view["status"] == "awaiting_c8"
    assert view["rows"] == []
    assert view["n_requested"] == DRIFT_HISTORY_DEFAULT_N

    view2 = build_drift_history_view([])
    assert view2["status"] == "awaiting_c8"


def test_build_drift_history_view_preserves_order() -> None:
    arts = [
        _artifact("2026-04-28", [_v("a")]),
        _artifact("2026-04-27", [_v("a"), _v("b")]),
        _artifact("2026-04-26", []),
    ]
    view = build_drift_history_view(arts)
    assert view["status"] == "ok"
    assert view["n_rendered"] == 3
    assert [r["as_of_date"] for r in view["rows"]] == [
        "2026-04-28",
        "2026-04-27",
        "2026-04-26",
    ]


def test_build_drift_history_view_truncates_to_n() -> None:
    arts = [_artifact(f"2026-04-{d:02d}", [_v("x")]) for d in range(28, 18, -1)]
    view = build_drift_history_view(arts, n=3)
    assert view["n_rendered"] == 3
    assert [r["as_of_date"] for r in view["rows"]] == [
        "2026-04-28",
        "2026-04-27",
        "2026-04-26",
    ]


def test_build_drift_history_view_default_n_is_seven() -> None:
    arts = [_artifact(f"2026-04-{d:02d}") for d in range(28, 18, -1)]
    view = build_drift_history_view(arts)
    assert view["n_requested"] == 7
    assert view["n_rendered"] == 7


def test_drift_history_default_n_constant() -> None:
    assert DRIFT_HISTORY_DEFAULT_N == 7
