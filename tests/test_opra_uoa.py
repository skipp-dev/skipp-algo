"""Unit tests for the OPRA.PILLAR-backed UOA detector.

All fixtures are pure Python dicts to keep the detector test surface
zero-dependency (no pandas, no network, no databento package).
"""

from __future__ import annotations

import pytest

from newsstack_fmp.opra_uoa import (
    OpraDefinitionRecord,
    detect_unusual_options_activity,
)


# ── Helpers ────────────────────────────────────────────────────────────


def _trade(
    *,
    instrument_id: int,
    ts_ms: int,
    price: float,
    size: int,
    side: str,
    publisher_id: int = 1,
) -> dict:
    """Build a synthetic OPRA trades row at ``ts_ms`` (ns conversion done here)."""
    return {
        "instrument_id": instrument_id,
        "ts_event": int(ts_ms) * 1_000_000,
        "price": price,
        "size": size,
        "side": side,
        "publisher_id": publisher_id,
    }


def _defn(
    *,
    instrument_id: int,
    underlying: str,
    strike: float,
    expiration: str,
    option_type: str,  # "C" or "P"
    raw_symbol: str | None = None,
) -> dict:
    return {
        "instrument_id": instrument_id,
        "underlying": underlying,
        "strike_price": strike,
        "expiration": expiration,
        "instrument_class": option_type,
        "raw_symbol": raw_symbol or f"{underlying}_{strike}{option_type}",
    }


# ── Premium gate ───────────────────────────────────────────────────────


def test_premium_gate_filters_small_prints():
    """A 1-lot at $0.50 = $50 notional — below the default $25k gate."""
    defs = [_defn(instrument_id=1, underlying="AAPL", strike=200, expiration="2026-06-21", option_type="C")]
    trades = [_trade(instrument_id=1, ts_ms=1_700_000_000_000, price=0.50, size=1, side="A")]
    out = detect_unusual_options_activity(trades, defs)
    assert out == [], "below-gate trade must be filtered"


def test_premium_gate_admits_large_block():
    """A 1000-lot at $5.00 = $500k notional — well above the default gate."""
    defs = [_defn(instrument_id=1, underlying="AAPL", strike=200, expiration="2026-06-21", option_type="C")]
    trades = [_trade(instrument_id=1, ts_ms=1_700_000_000_000, price=5.0, size=1000, side="A")]
    out = detect_unusual_options_activity(trades, defs)
    assert len(out) == 1
    rec = out[0]
    assert rec["ticker"] == "AAPL"
    assert rec["option_activity_type"] == "CALL"
    assert rec["cost_basis"] == pytest.approx(500_000.0)
    assert rec["sentiment"] == "BULLISH"
    assert rec["aggressor_ind"] == "A"


def test_premium_gate_custom_value():
    """A $10k gate accepts a $12k print that the $25k default would reject."""
    defs = [_defn(instrument_id=1, underlying="AAPL", strike=200, expiration="2026-06-21", option_type="C")]
    trades = [_trade(instrument_id=1, ts_ms=1_700_000_000_000, price=2.4, size=50, side="A")]
    # premium = 2.4 * 50 * 100 = 12,000
    assert detect_unusual_options_activity(trades, defs) == []  # default $25k gate
    out = detect_unusual_options_activity(trades, defs, min_premium=10_000.0)
    assert len(out) == 1
    assert out[0]["cost_basis"] == pytest.approx(12_000.0)


# ── Sweep detection ────────────────────────────────────────────────────


def test_sweep_detected_when_three_exchanges_fire_in_window():
    """Three prints inside the 500 ms bucket on three exchanges = sweep."""
    defs = [_defn(instrument_id=1, underlying="NVDA", strike=900, expiration="2026-06-21", option_type="C")]
    base_ts = 1_700_000_000_000
    trades = [
        _trade(instrument_id=1, ts_ms=base_ts + i * 100, price=4.0, size=200, side="A", publisher_id=pid)
        for i, pid in enumerate([10, 20, 30])
    ]
    out = detect_unusual_options_activity(trades, defs)
    assert len(out) == 3
    assert all(r["uw_is_sweep"] is True for r in out)
    assert all(r["uw_alert_rule"] == "opra_sweep" for r in out)


def test_no_sweep_when_only_two_exchanges():
    """Same window but only 2 distinct publisher_ids = block, not sweep."""
    defs = [_defn(instrument_id=1, underlying="NVDA", strike=900, expiration="2026-06-21", option_type="C")]
    base_ts = 1_700_000_000_000
    trades = [
        _trade(instrument_id=1, ts_ms=base_ts + i * 100, price=4.0, size=200, side="A", publisher_id=pid)
        for i, pid in enumerate([10, 20])
    ]
    out = detect_unusual_options_activity(trades, defs)
    assert len(out) == 2
    assert all(r["uw_is_sweep"] is False for r in out)
    assert all(r["uw_alert_rule"] == "opra_block" for r in out)


def test_sweep_window_does_not_cross_boundary():
    """Trades spread >500 ms apart land in different buckets -> no sweep."""
    defs = [_defn(instrument_id=1, underlying="NVDA", strike=900, expiration="2026-06-21", option_type="C")]
    base_ts = 1_700_000_000_000
    trades = [
        _trade(instrument_id=1, ts_ms=base_ts, price=4.0, size=200, side="A", publisher_id=10),
        _trade(instrument_id=1, ts_ms=base_ts + 600, price=4.0, size=200, side="A", publisher_id=20),
        _trade(instrument_id=1, ts_ms=base_ts + 1200, price=4.0, size=200, side="A", publisher_id=30),
    ]
    out = detect_unusual_options_activity(trades, defs)
    assert len(out) == 3
    assert all(r["uw_is_sweep"] is False for r in out)


# ── Multi-leg detection ────────────────────────────────────────────────


def test_multileg_flag_set_for_call_and_put_in_same_bucket():
    defs = [
        _defn(instrument_id=1, underlying="SPY", strike=600, expiration="2026-06-21", option_type="C"),
        _defn(instrument_id=2, underlying="SPY", strike=600, expiration="2026-06-21", option_type="P"),
    ]
    base_ts = 1_700_000_000_000
    trades = [
        _trade(instrument_id=1, ts_ms=base_ts, price=3.0, size=300, side="A", publisher_id=10),
        _trade(instrument_id=2, ts_ms=base_ts + 50, price=2.5, size=400, side="B", publisher_id=20),
    ]
    out = detect_unusual_options_activity(trades, defs)
    assert len(out) == 2
    assert all(r["uw_multileg"] is True for r in out)


def test_no_multileg_when_only_calls():
    defs = [
        _defn(instrument_id=1, underlying="SPY", strike=600, expiration="2026-06-21", option_type="C"),
        _defn(instrument_id=2, underlying="SPY", strike=605, expiration="2026-06-21", option_type="C"),
    ]
    base_ts = 1_700_000_000_000
    trades = [
        _trade(instrument_id=1, ts_ms=base_ts, price=3.0, size=300, side="A"),
        _trade(instrument_id=2, ts_ms=base_ts + 50, price=2.5, size=400, side="A"),
    ]
    out = detect_unusual_options_activity(trades, defs)
    assert len(out) == 2
    assert all(r["uw_multileg"] is False for r in out)


# ── Aggressor mapping ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "side,expect_aggr,expect_sentiment",
    [
        ("A", "A", "BULLISH"),
        ("B", "B", "BEARISH"),
        ("N", "N", "NEUTRAL"),
        ("", "N", "NEUTRAL"),
        ("?", "N", "NEUTRAL"),
        (None, "N", "NEUTRAL"),
    ],
)
def test_aggressor_classification(side, expect_aggr, expect_sentiment):
    defs = [_defn(instrument_id=1, underlying="AAPL", strike=200, expiration="2026-06-21", option_type="C")]
    trades = [_trade(instrument_id=1, ts_ms=1_700_000_000_000, price=5.0, size=1000, side=side or "")]
    out = detect_unusual_options_activity(trades, defs)
    assert len(out) == 1
    assert out[0]["aggressor_ind"] == expect_aggr
    assert out[0]["sentiment"] == expect_sentiment


# ── Ticker filter ──────────────────────────────────────────────────────


def test_ticker_filter_drops_non_whitelisted():
    defs = [
        _defn(instrument_id=1, underlying="AAPL", strike=200, expiration="2026-06-21", option_type="C"),
        _defn(instrument_id=2, underlying="TSLA", strike=300, expiration="2026-06-21", option_type="C"),
    ]
    trades = [
        _trade(instrument_id=1, ts_ms=1_700_000_000_000, price=5.0, size=1000, side="A"),
        _trade(instrument_id=2, ts_ms=1_700_000_000_000, price=5.0, size=1000, side="A"),
    ]
    out = detect_unusual_options_activity(trades, defs, tickers=["AAPL"])
    assert len(out) == 1
    assert out[0]["ticker"] == "AAPL"


def test_ticker_filter_case_insensitive():
    defs = [_defn(instrument_id=1, underlying="AAPL", strike=200, expiration="2026-06-21", option_type="C")]
    trades = [_trade(instrument_id=1, ts_ms=1_700_000_000_000, price=5.0, size=1000, side="A")]
    out = detect_unusual_options_activity(trades, defs, tickers=["aapl"])
    assert len(out) == 1


# ── Output schema parity with UW ───────────────────────────────────────


_REQUIRED_KEYS = {
    "ticker", "date", "time", "sentiment", "aggressor_ind",
    "option_activity_type", "option_symbol", "underlying_price",
    "strike_price", "date_expiration", "size", "volume",
    "open_interest", "cost_basis", "price",
    "uw_alert_rule", "uw_is_sweep", "uw_has_floor", "uw_multileg",
    "_source", "_opra_raw",
}


def test_output_schema_has_all_uw_compat_keys():
    defs = [_defn(instrument_id=1, underlying="AAPL", strike=200, expiration="2026-06-21", option_type="C")]
    trades = [_trade(instrument_id=1, ts_ms=1_700_000_000_000, price=5.0, size=1000, side="A")]
    out = detect_unusual_options_activity(trades, defs)
    assert len(out) == 1
    missing = _REQUIRED_KEYS - set(out[0].keys())
    assert missing == set(), f"missing UW-compat keys: {missing}"
    assert out[0]["_source"] == "databento_opra"
    assert isinstance(out[0]["_opra_raw"], dict)


def test_unknown_instrument_id_dropped_not_emitted():
    """Trade with no matching definition -> skipped (no malformed record)."""
    defs = [_defn(instrument_id=1, underlying="AAPL", strike=200, expiration="2026-06-21", option_type="C")]
    trades = [
        _trade(instrument_id=999, ts_ms=1_700_000_000_000, price=5.0, size=1000, side="A"),
        _trade(instrument_id=1, ts_ms=1_700_000_000_000, price=5.0, size=1000, side="A"),
    ]
    out = detect_unusual_options_activity(trades, defs)
    assert len(out) == 1
    assert out[0]["ticker"] == "AAPL"


def test_definition_record_from_row_handles_call_put():
    rec_c = OpraDefinitionRecord.from_row(
        {"instrument_id": 1, "underlying": "AAPL", "strike_price": 200,
         "expiration": "2026-06-21", "instrument_class": "C"}
    )
    assert rec_c.option_type == "CALL"
    rec_p = OpraDefinitionRecord.from_row(
        {"instrument_id": 2, "underlying": "AAPL", "strike_price": 200,
         "expiration": "2026-06-21", "instrument_class": "P"}
    )
    assert rec_p.option_type == "PUT"
