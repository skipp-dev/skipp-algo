"""Unit tests for the shadow-latency analyzer's pure aggregation core.

The Databento intraday fetch is an I/O shim; here the price-fetch is injected
as a fake so latency + edge summaries are tested deterministically.
"""

from __future__ import annotations

from scripts.analyze_bz_ws_latency import (
    attach_price_moves,
    select_catalyst_windows,
    summarize_edge,
    summarize_latency,
)


def _rec(**kw):
    base = {
        "item_id": "x", "headline": "h", "tickers": ["AAPL"], "catalyst_score": 0.0,
        "t_published": None, "t_ws": None, "t_rest": None, "t_x": None,
        "ws_rest_delta_s": None, "pub_ws_delta_s": None, "pub_rest_delta_s": None,
    }
    base.update(kw)
    return base


def test_summarize_latency_counts_ws_advantage() -> None:
    records = [
        _rec(item_id="a", t_ws=100.0, t_rest=130.0, ws_rest_delta_s=30.0),
        _rec(item_id="b", t_ws=200.0, t_rest=205.0, ws_rest_delta_s=5.0),
        _rec(item_id="c", t_ws=300.0, t_rest=299.0, ws_rest_delta_s=-1.0),  # REST won
        _rec(item_id="d", t_ws=400.0),  # rest never seen → excluded
    ]
    s = summarize_latency(records)
    assert s["records_total"] == 4
    assert s["records_ws_and_rest"] == 3
    assert s["ws_earlier_count"] == 2
    assert abs(s["ws_earlier_share"] - 2 / 3) < 1e-9
    assert s["ws_rest_delta_s"]["median"] == 5.0
    # no TV matched here → tv summary is empty but present
    assert s["records_with_tv"] == 0
    assert s["tv_matched_share"] == 0.0
    assert s["ws_tv_delta_s"]["n"] == 0


def test_summarize_latency_includes_tv_deltas() -> None:
    records = [
        # TV matched: arrived before both WS and REST
        _rec(item_id="a", t_ws=100.0, t_rest=130.0, t_tv=90.0,
             ws_rest_delta_s=30.0, ws_tv_delta_s=100.0 - 90.0,
             rest_tv_delta_s=130.0 - 90.0),
        # TV matched: arrived after REST
        _rec(item_id="b", t_ws=200.0, t_rest=205.0, t_tv=210.0,
             ws_rest_delta_s=5.0, ws_tv_delta_s=200.0 - 210.0,
             rest_tv_delta_s=205.0 - 210.0),
        # no TV
        _rec(item_id="c", t_ws=300.0, t_rest=330.0, ws_rest_delta_s=30.0),
    ]
    s = summarize_latency(records)
    assert s["records_with_tv"] == 2
    assert abs(s["tv_matched_share"] - 2 / 3) < 1e-9
    assert s["rest_tv_delta_s"]["n"] == 2
    # rest_tv deltas are {40, -5}: positive means REST earlier than TV
    assert s["rest_tv_delta_s"]["max"] == 40.0
    assert s["rest_tv_delta_s"]["min"] == -5.0


def test_select_catalyst_windows_filters() -> None:
    records = [
        # eligible: catalyst + ws advantage + tickers
        _rec(item_id="a", catalyst_score=0.5, t_ws=100.0, t_rest=130.0,
             ws_rest_delta_s=30.0, tickers=["AAPL"]),
        # below catalyst threshold
        _rec(item_id="b", catalyst_score=0.1, t_ws=100.0, t_rest=130.0,
             ws_rest_delta_s=30.0, tickers=["MSFT"]),
        # REST won → no WS advantage
        _rec(item_id="c", catalyst_score=0.9, t_ws=100.0, t_rest=90.0,
             ws_rest_delta_s=-10.0, tickers=["TSLA"]),
        # no tickers
        _rec(item_id="d", catalyst_score=0.9, t_ws=100.0, t_rest=130.0,
             ws_rest_delta_s=30.0, tickers=[]),
    ]
    sel = select_catalyst_windows(records, min_catalyst=0.33)
    assert [r["item_id"] for r in sel] == ["a"]


def test_attach_price_moves_uses_injected_fetch_and_first_ticker() -> None:
    windows = [_rec(item_id="a", t_ws=100.0, t_rest=130.0, tickers=["AAPL", "MSFT"])]

    seen = {}

    def fake_fetch(symbol, t0, t1):
        seen["args"] = (symbol, t0, t1)
        return 0.012

    enriched = attach_price_moves(windows, fake_fetch)
    assert seen["args"] == ("AAPL", 100.0, 130.0)  # first ticker, WS→REST window
    assert enriched[0]["window_move_pct"] == 0.012
    assert enriched[0]["edge_symbol"] == "AAPL"


def test_summarize_edge_handles_missing_prices() -> None:
    windows = [
        {"window_move_pct": 0.02},
        {"window_move_pct": -0.03},
        {"window_move_pct": None},  # no intraday coverage
    ]
    e = summarize_edge(windows)
    assert e["catalyst_windows"] == 3
    assert e["windows_with_price"] == 2
    assert e["abs_move_pct"]["median"] in (0.02, 0.03)
