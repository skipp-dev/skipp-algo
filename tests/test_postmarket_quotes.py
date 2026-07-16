"""Contracts for fail-closed FMP postmarket quote normalization."""

from __future__ import annotations

from open_prep.postmarket_quotes import build_postmarket_quotes

NOW = 1_784_222_000.0


def _reference(*, price: float = 99.0, volume: float = 1_000_000.0):
    return [{
        "symbol": "AAPL",
        "price": price,
        "previousClose": 100.0,
        "volume": volume,
        "timestamp": NOW - 3600,
    }]


def _quote(*, bid: float = 100.0, ask: float = 102.0, volume: float = 1_100_000.0, age: float = 10.0):
    return [{
        "symbol": "AAPL",
        "bidPrice": bid,
        "askPrice": ask,
        "volume": volume,
        "timestamp": (NOW - age) * 1000,
    }]


def _trade(*, price: float = 101.5, age: float = 5.0):
    return [{"symbol": "AAPL", "price": price, "timestamp": (NOW - age) * 1000}]


def _build(**overrides):
    inputs = {
        "reference_rows": _reference(),
        "quote_rows": _quote(),
        "trade_rows": _trade(),
        "close_volume_by_symbol": {"AAPL": 1_000_000.0},
        "baseline_session_date": "2026-07-16",
        "current_session_date": "2026-07-16",
        "now_epoch": NOW,
    }
    inputs.update(overrides)
    return build_postmarket_quotes(**inputs)


def test_fresh_trade_wins_and_regular_price_is_never_used() -> None:
    result = _build(reference_rows=_reference(price=12.34))
    row = result.quotes["AAPL"]

    assert row["price"] == 101.5
    assert row["extended_price_source"] == "aftermarket_trade"
    assert row["reference_price_ignored"] == 12.34
    assert row["volume"] == 100_000.0
    assert row["postmarket_volume_ready"] is True
    assert result.stats["signal_ready_rows"] == 1


def test_fresh_midpoint_is_fallback_when_trade_is_stale() -> None:
    result = _build(trade_rows=_trade(age=301.0))
    row = result.quotes["AAPL"]

    assert row["price"] == 101.0
    assert row["extended_price_source"] == "aftermarket_midpoint"
    assert result.stats["midpoint_price_rows"] == 1


def test_stale_trade_and_quote_fail_closed() -> None:
    result = _build(trade_rows=_trade(age=301.0), quote_rows=_quote(age=301.0))

    assert result.quotes == {}
    assert result.stats["rejected_no_fresh_price"] == 1


def test_crossed_quote_cannot_supply_midpoint() -> None:
    result = _build(trade_rows=[], quote_rows=_quote(bid=103.0, ask=102.0))

    assert result.quotes == {}
    assert result.stats["rejected_crossed_quote"] == 1


def test_missing_or_prior_day_baseline_keeps_price_but_blocks_signal() -> None:
    result = _build(baseline_session_date="2026-07-15")
    row = result.quotes["AAPL"]

    assert row["price"] == 101.5
    assert row["postmarket_volume_ready"] is False
    assert row["volume"] == 0.0
    assert result.stats["price_ready_rows"] == 1
    assert result.stats["signal_ready_rows"] == 0


def test_cumulative_volume_regression_blocks_signal() -> None:
    result = _build(quote_rows=_quote(volume=900_000.0))

    assert result.quotes["AAPL"]["postmarket_volume_ready"] is False
    assert result.stats["rejected_volume_regression"] == 1
