"""Regression coverage for ATR scale safety and volume-source contracts."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pandas as pd

from open_prep import run_open_prep
from open_prep.a0_parity import ShadowDecision, build_engine_parity_report
from open_prep.atr_quality import (
    actionable_atr_pct,
    atr_pct_from_price_units,
    homogeneous_price_history,
)
from open_prep.outcome_backfill import compute_pnl_from_bars
from open_prep.realtime_signals import _watchlist_average_volume
from open_prep.run_open_prep import _calculate_atr14_from_eod
from open_prep.scorer import filter_candidate
from open_prep.trade_context import trade_context
from open_prep.volume_source_audit import (
    build_multi_session_summary,
    build_volume_measurement,
)
from scripts.apply_fmp_adv_reference import apply_fmp_adv_reference


def _split_history(
    *, post_split_bars: int, post_split_price: float = 5.0,
) -> tuple[list[dict[str, object]], date]:
    start = date(2026, 5, 1)
    rows: list[dict[str, object]] = []
    for index in range(20):
        day = start + timedelta(days=index)
        rows.append({"date": day.isoformat(), "high": 102.0, "low": 98.0, "close": 100.0})
    split_day = start + timedelta(days=20)
    for index in range(post_split_bars):
        day = split_day + timedelta(days=index)
        rows.append({
            "date": day.isoformat(),
            "high": post_split_price * 1.02,
            "low": post_split_price * 0.98,
            "close": post_split_price,
        })
    return rows, split_day


def test_known_split_resets_wilder_state_to_post_split_scale() -> None:
    rows, split_day = _split_history(post_split_bars=16, post_split_price=50.0)
    contaminated = _calculate_atr14_from_eod(rows, period=14)
    reset = _calculate_atr14_from_eod(rows, period=14, split_dates={split_day})
    assert contaminated > 1.0
    assert reset == 2.0


def test_extreme_unmapped_scale_break_fails_closed_until_history_rebuilds() -> None:
    rows, _ = _split_history(post_split_bars=10)
    assert _calculate_atr14_from_eod(rows, period=14) == 0.0


def test_every_historical_feature_receives_only_the_post_split_segment() -> None:
    rows, split_day = _split_history(post_split_bars=16, post_split_price=50.0)
    segment, reason = homogeneous_price_history(rows, split_dates={split_day})
    assert reason == "corporate_action"
    assert len(segment) == 16
    assert {float(row["close"]) for row in segment} == {50.0}


def test_relative_wilder_state_does_not_preserve_an_old_price_level() -> None:
    rows = []
    for index in range(40):
        close = 100.0 * (0.98 ** index)
        rows.append({
            "date": (date(2026, 5, 1) + timedelta(days=index)).isoformat(),
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
        })
    latest_close = float(rows[-1]["close"])
    atr_pct = _calculate_atr14_from_eod(rows, period=14) / latest_close * 100.0
    assert 2.0 < atr_pct < 4.0


def test_pre_hardening_atr_cache_is_rejected(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(run_open_prep, "ATR_CACHE_DIR", tmp_path)
    cache = tmp_path / "2026-07-28_p14.json"
    cache.write_text(json.dumps({
        "as_of": "2026-07-28",
        "atr_period": 14,
        "atr14_by_symbol": {"INLF": 33.409},
        "momentum_z_by_symbol": {"INLF": 0.0},
        "prev_close_by_symbol": {"INLF": 5.0},
    }), encoding="utf-8")
    assert run_open_prep._load_atr_cache(date(2026, 7, 28), 14) == ({}, {}, {})


def test_implausible_atr_is_not_actionable_anywhere() -> None:
    assert actionable_atr_pct(668.18) is None
    assert atr_pct_from_price_units(33.409, 5.0) is None
    assert trade_context(5.0, 668.18, "LONG") is None


def test_outcome_barrier_falls_back_when_atr_is_implausible() -> None:
    run_date = date(2026, 7, 28)
    rows = []
    for minute in range(31):
        stamp = datetime(2026, 7, 28, 13, 30, tzinfo=UTC) + timedelta(minutes=minute)
        rows.append({
            "symbol": "INLF",
            "ts_event": stamp,
            "open": 5.0,
            "high": 5.01,
            "low": 4.99,
            "close": 5.0,
            "volume": 1000,
        })
    result = compute_pnl_from_bars(
        pd.DataFrame(rows),
        "INLF",
        run_date,
        atr_pct=668.18,
    )
    assert result is not None
    assert result["tb_barrier_source"] == "atr_invalid"
    assert result["label_tb"] is None
    assert result["profitable_tb"] is None


def test_rejected_corporate_action_atr_hard_blocks_scoring() -> None:
    result = filter_candidate({
        "symbol": "INLF",
        "price": 5.0,
        "previousClose": 5.0,
        "gap_pct": 3.0,
        "gap_available": True,
        "volume": 1_000_000,
        "avgVolume": 500_000,
        "atr": 0.0,
        "atr_data_quality": "rejected_corporate_action_history",
        "rsi": 50.0,
    }, bias=0.0)
    assert result.passed is False
    assert "atr_implausible_or_split" in result.filter_reasons


def _decision(source: str) -> ShadowDecision:
    return ShadowDecision(
        decision_id=f"{source}-1",
        symbol="NVDA",
        direction="LONG",
        level="A0",
        decision_at=100.0,
        source=source,
        reason_codes=("core_a0_thresholds",),
        normalized_volume_pace=4.0,
        change_pct=3.0,
        effective_a0_volume_threshold=3.0,
        effective_a0_price_threshold=2.0,
        core_level="A0",
    )


def test_engine_parity_replays_each_source_independently() -> None:
    report = build_engine_parity_report([_decision("fmp"), _decision("databento")])
    assert report["parity_rate"] == 1.0
    assert report["per_source"] == {
        "databento": {"match": 1},
        "fmp": {"match": 1},
    }

    mismatch = replace(_decision("fmp"), normalized_volume_pace=1.0)
    report = build_engine_parity_report([mismatch])
    assert report["mismatching_snapshots"] == 1


def test_fmp_reference_is_explicit_and_missing_values_do_not_profile_fallback() -> None:
    snapshot = {
        "ranked_v2": [
            {"symbol": "AAPL", "avg_volume": 90_000_000},
            {"symbol": "MISSING", "avg_volume": 5_000_000},
        ],
        "filtered_out_v2": [],
        "enriched_quotes": [],
    }
    reference = {
        "AAPL": {
            "average_daily_volume": 55_000_000,
            "as_of_session": "2026-07-27",
            "source": "fmp:adjusted-eod",
        },
    }
    stats = apply_fmp_adv_reference(snapshot, reference)
    aapl, missing = snapshot["ranked_v2"]
    assert stats == {"symbols_seen": 2, "symbols_covered": 1, "symbols_missing": 1}
    assert _watchlist_average_volume(aapl) == 55_000_000
    assert missing["avg_volume_15_session"] is None
    assert _watchlist_average_volume(missing) == 0.0
    assert _watchlist_average_volume({"avg_volume": 1234}) == 1234


def test_volume_basis_measurement_and_five_session_decision() -> None:
    minute_rows = [
        {
            "date": f"2026-07-2{day} 09:{30 + minute:02d}:00",
            "volume": 100,
        }
        for day in [8]
        for minute in range(10)
    ]
    measurement = build_volume_measurement(
        symbol="AAPL",
        session_date="2026-07-28",
        quote_row={"volume": 1000},
        minute_rows=minute_rows,
        eod_response=[{"date": "2026-07-28", "volume": 1300}],
    )
    assert measurement["quote_to_minute_full_ratio"] == 1.0
    assert measurement["eod_to_minute_full_ratio"] == 1.3

    history = []
    for offset in range(5):
        history.append({
            **measurement,
            "session_date": (date(2026, 7, 20) + timedelta(days=offset)).isoformat(),
        })
    summary = build_multi_session_summary(history, minimum_sessions=5)
    assert summary["ready_for_decision"] is True
    assert summary["verdict"] == "confirmed_basis_mismatch"
    assert summary["recommended_next_step"] == (
        "replace FMP ADV with the same intraday aggregation basis"
    )
