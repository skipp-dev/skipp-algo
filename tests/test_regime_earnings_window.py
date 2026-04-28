"""C13/T7.3 — earnings-window regime bucket tagging tests."""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import pytest

from scripts.regime_earnings_window import (
    DEFAULT_POST_WINDOW_DAYS,
    DEFAULT_PRE_WINDOW_DAYS,
    EARNINGS_WINDOW_LABEL,
    assign_earnings_window_bucket,
    earnings_window_share,
    is_in_earnings_window,
    load_earnings_events,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _trade(symbol: str, date: str, regime: str = "RISK_ON", pnl: float = 0.0) -> dict:
    return {
        "symbol": symbol,
        "trade_date": date,
        "regime_at_entry": regime,
        "pnl": pnl,
    }


# ---------------------------------------------------------------------------
# load_earnings_events
# ---------------------------------------------------------------------------


def test_load_earnings_events_indexes_by_symbol(tmp_path: Path) -> None:
    p = tmp_path / "wsh.jsonl"
    _write_jsonl(
        p,
        [
            {"symbol": "aapl", "event_date": "2026-04-30", "event_type": "Earnings"},
            {"symbol": "AAPL", "event_date": "2026-07-30", "event_type": "EarningsAnnouncement"},
            {"symbol": "TSLA", "event_date": "2026-04-22", "event_type": "Earnings"},
            # Non-earnings types are skipped.
            {"symbol": "AAPL", "event_date": "2026-05-15", "event_type": "Dividend"},
        ],
    )
    idx = load_earnings_events(p)
    assert set(idx) == {"AAPL", "TSLA"}
    assert idx["AAPL"] == [_dt.date(2026, 4, 30), _dt.date(2026, 7, 30)]
    assert idx["TSLA"] == [_dt.date(2026, 4, 22)]


def test_load_earnings_events_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_earnings_events(tmp_path / "nope.jsonl") == {}


def test_load_earnings_events_skips_malformed_lines(tmp_path: Path) -> None:
    p = tmp_path / "wsh.jsonl"
    p.write_text(
        '{"symbol":"AAPL","event_date":"2026-04-30","event_type":"Earnings"}\n'
        "this is not json\n"
        '{"symbol":"AAPL","event_date":"bogus","event_type":"Earnings"}\n',
        encoding="utf-8",
    )
    idx = load_earnings_events(p)
    assert idx == {"AAPL": [_dt.date(2026, 4, 30)]}


def test_load_earnings_events_unreadable_file_returns_empty(tmp_path: Path) -> None:
    # Directory in place of a file → OSError on open().
    p = tmp_path / "dir-not-file"
    p.mkdir()
    assert load_earnings_events(p) == {}


# ---------------------------------------------------------------------------
# is_in_earnings_window
# ---------------------------------------------------------------------------


def test_is_in_earnings_window_inside_default_window() -> None:
    idx = {"AAPL": [_dt.date(2026, 4, 30)]}
    # Default ±2 calendar days
    for d in ("2026-04-28", "2026-04-29", "2026-04-30", "2026-05-01", "2026-05-02"):
        assert is_in_earnings_window(symbol="AAPL", trade_date=d, events_index=idx) is True


def test_is_in_earnings_window_outside_default_window() -> None:
    idx = {"AAPL": [_dt.date(2026, 4, 30)]}
    for d in ("2026-04-27", "2026-05-03", "2026-01-01"):
        assert is_in_earnings_window(symbol="AAPL", trade_date=d, events_index=idx) is False


def test_is_in_earnings_window_unknown_symbol_returns_false() -> None:
    idx = {"AAPL": [_dt.date(2026, 4, 30)]}
    assert is_in_earnings_window(symbol="NVDA", trade_date="2026-04-30", events_index=idx) is False


def test_is_in_earnings_window_case_insensitive_symbol() -> None:
    idx = {"AAPL": [_dt.date(2026, 4, 30)]}
    assert is_in_earnings_window(symbol="aapl", trade_date="2026-04-30", events_index=idx) is True


def test_is_in_earnings_window_rejects_negative_window() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        is_in_earnings_window(
            symbol="AAPL",
            trade_date="2026-04-30",
            events_index={"AAPL": [_dt.date(2026, 4, 30)]},
            pre_window_days=-1,
        )


def test_is_in_earnings_window_accepts_date_object() -> None:
    idx = {"AAPL": [_dt.date(2026, 4, 30)]}
    assert is_in_earnings_window(symbol="AAPL", trade_date=_dt.date(2026, 4, 30), events_index=idx) is True


# ---------------------------------------------------------------------------
# assign_earnings_window_bucket
# ---------------------------------------------------------------------------


def test_assign_retags_inside_window_preserves_original() -> None:
    idx = {"AAPL": [_dt.date(2026, 4, 30)]}
    trades = [
        _trade("AAPL", "2026-04-29", regime="RISK_ON"),  # in window
        _trade("AAPL", "2026-05-15", regime="RISK_ON"),  # out
        _trade("TSLA", "2026-04-30", regime="RISK_OFF"),  # unknown symbol
    ]
    out = assign_earnings_window_bucket(trades, events_index=idx)
    assert [t["regime_at_entry"] for t in out] == [
        EARNINGS_WINDOW_LABEL,
        "RISK_ON",
        "RISK_OFF",
    ]
    assert out[0]["regime_original"] == "RISK_ON"
    assert "regime_original" not in out[1]
    assert "regime_original" not in out[2]


def test_assign_does_not_mutate_input() -> None:
    idx = {"AAPL": [_dt.date(2026, 4, 30)]}
    trades = [_trade("AAPL", "2026-04-29")]
    snapshot = [dict(t) for t in trades]
    assign_earnings_window_bucket(trades, events_index=idx)
    assert trades == snapshot


def test_assign_empty_index_returns_copies_unchanged() -> None:
    trades = [_trade("AAPL", "2026-04-29")]
    out = assign_earnings_window_bucket(trades, events_index={})
    assert out[0]["regime_at_entry"] == "RISK_ON"
    assert "regime_original" not in out[0]
    assert out[0] is not trades[0]  # shallow copy


def test_assign_no_data_source_is_passthrough() -> None:
    trades = [_trade("AAPL", "2026-04-29")]
    out = assign_earnings_window_bucket(trades)
    assert out[0]["regime_at_entry"] == "RISK_ON"


def test_assign_loads_jsonl_when_index_not_given(tmp_path: Path) -> None:
    p = tmp_path / "wsh.jsonl"
    _write_jsonl(p, [{"symbol": "AAPL", "event_date": "2026-04-30", "event_type": "Earnings"}])
    trades = [_trade("AAPL", "2026-04-29"), _trade("AAPL", "2026-12-01")]
    out = assign_earnings_window_bucket(trades, events_jsonl=p)
    assert out[0]["regime_at_entry"] == EARNINGS_WINDOW_LABEL
    assert out[1]["regime_at_entry"] == "RISK_ON"


def test_assign_missing_jsonl_fails_open(tmp_path: Path) -> None:
    trades = [_trade("AAPL", "2026-04-29")]
    out = assign_earnings_window_bucket(trades, events_jsonl=tmp_path / "nope.jsonl")
    assert out[0]["regime_at_entry"] == "RISK_ON"
    assert "regime_original" not in out[0]


def test_assign_skips_trade_with_missing_fields() -> None:
    idx = {"AAPL": [_dt.date(2026, 4, 30)]}
    trades = [
        {"regime_at_entry": "RISK_ON", "pnl": 0.0},  # no symbol/date
        {"symbol": "AAPL", "regime_at_entry": "RISK_ON", "pnl": 0.0},  # no date
        {"symbol": "AAPL", "trade_date": "", "regime_at_entry": "RISK_ON"},  # blank date
    ]
    out = assign_earnings_window_bucket(trades, events_index=idx)
    assert all(t["regime_at_entry"] == "RISK_ON" for t in out)
    assert all("regime_original" not in t for t in out)


def test_assign_skips_unparseable_trade_date() -> None:
    idx = {"AAPL": [_dt.date(2026, 4, 30)]}
    trades = [{"symbol": "AAPL", "trade_date": "not-a-date", "regime_at_entry": "RISK_ON"}]
    out = assign_earnings_window_bucket(trades, events_index=idx)
    assert out[0]["regime_at_entry"] == "RISK_ON"


def test_assign_custom_regime_col() -> None:
    idx = {"AAPL": [_dt.date(2026, 4, 30)]}
    trades = [{"symbol": "AAPL", "trade_date": "2026-04-29", "vol_regime": "LOW_VOL"}]
    out = assign_earnings_window_bucket(trades, events_index=idx, regime_col="vol_regime")
    assert out[0]["vol_regime"] == EARNINGS_WINDOW_LABEL
    assert out[0]["regime_original"] == "LOW_VOL"


def test_assign_rejects_negative_window() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        assign_earnings_window_bucket([_trade("AAPL", "2026-04-30")], post_window_days=-1)


def test_assign_empty_input_returns_empty_list() -> None:
    assert assign_earnings_window_bucket([], events_index={"AAPL": [_dt.date(2026, 4, 30)]}) == []


# ---------------------------------------------------------------------------
# earnings_window_share
# ---------------------------------------------------------------------------


def test_earnings_window_share_reports_correct_fraction() -> None:
    idx = {"AAPL": [_dt.date(2026, 4, 30)]}
    trades = [
        _trade("AAPL", "2026-04-29"),  # in
        _trade("AAPL", "2026-04-30"),  # in
        _trade("AAPL", "2026-12-01"),  # out
        _trade("TSLA", "2026-04-30"),  # unknown
    ]
    out = assign_earnings_window_bucket(trades, events_index=idx)
    assert earnings_window_share(trades, out) == pytest.approx(0.5)


def test_earnings_window_share_empty_returns_zero() -> None:
    assert earnings_window_share([], []) == 0.0


# ---------------------------------------------------------------------------
# Defaults sanity
# ---------------------------------------------------------------------------


def test_default_window_is_wider_than_pretrade_block() -> None:
    # T7.2 hard-blocks at ±1 day; T7.3 stratifies a wider ±2 by default
    # so trades that just escaped the block still get bucketed.
    assert DEFAULT_PRE_WINDOW_DAYS >= 1
    assert DEFAULT_POST_WINDOW_DAYS >= 1
