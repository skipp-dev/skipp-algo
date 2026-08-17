"""EV-13 wrapper tests: real Databento OHLCV -> run_edge_pipeline input.

The credential-bound ``fetch_ohlcv_frame`` is intentionally NOT exercised here
(no live API in CI). These tests cover the pure transform contract: timestamp
normalization, the load-bearing bars/structure anchor consistency, and the
honest-empty refusals.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts import pull_databento_edge_input as wrapper
from scripts.pull_databento_edge_input import (
    _quote_rule_opra_aggressor,
    aggregate_signed_uoa_notional,
    aggregate_signed_volume,
    normalize_ohlcv_frame,
    normalize_opra_trades_frame,
    normalize_trades_frame,
    structure_and_bars_to_pipeline_input,
)

_T0 = 1_700_000_000  # 2023-11-14T22:13:20Z, an arbitrary fixed epoch second.


def _raw_minute_frame(n: int = 180, *, symbol: str = "AAPL") -> pd.DataFrame:
    """A synthetic 1-minute OHLCV frame on a DatetimeIndex (Databento shape)."""
    index = pd.to_datetime(
        [(_T0 + i * 60) * 1_000_000_000 for i in range(n)], utc=True
    )
    base = 100.0 + np.linspace(0.0, 5.0, n)
    return pd.DataFrame(
        {
            "open": base,
            "high": base + 0.3,
            "low": base - 0.3,
            "close": base + 0.1,
            "volume": np.full(n, 1_000.0),
            "symbol": symbol,
        },
        index=pd.DatetimeIndex(index, name="ts_event"),
    )


def test_normalize_from_datetime_index_yields_epoch_seconds() -> None:
    raw = _raw_minute_frame(n=3)
    out = normalize_ohlcv_frame(raw, symbol="AAPL")

    assert list(out.columns) == [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "symbol",
        "volume",
    ]
    # First timestamp is exactly the fixed epoch SECOND (not ns).
    assert int(out["timestamp"].iloc[0]) == _T0
    assert int(out["timestamp"].iloc[1]) == _T0 + 60
    assert (out["symbol"] == "AAPL").all()


def test_normalize_from_ts_event_column() -> None:
    raw = _raw_minute_frame(n=2).reset_index()  # ts_event becomes a column
    out = normalize_ohlcv_frame(raw, symbol="aapl")
    assert int(out["timestamp"].iloc[0]) == _T0
    assert (out["symbol"] == "AAPL").all()


def test_normalize_fills_symbol_and_volume_when_absent() -> None:
    raw = _raw_minute_frame(n=2).drop(columns=["symbol", "volume"])
    out = normalize_ohlcv_frame(raw, symbol="msft")
    assert (out["symbol"] == "MSFT").all()
    assert (out["volume"] == 0.0).all()


def test_normalize_rejects_missing_ohlcv_columns() -> None:
    raw = _raw_minute_frame(n=2).drop(columns=["high"])
    with pytest.raises(ValueError, match="missing required OHLCV"):
        normalize_ohlcv_frame(raw, symbol="AAPL")


def test_normalize_rejects_empty_frame() -> None:
    with pytest.raises(ValueError, match="empty"):
        normalize_ohlcv_frame(pd.DataFrame(), symbol="AAPL")


def test_bars_match_resampled_structure_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    """LOAD-BEARING: emitted bars are the SAME resampled frame structure anchors on.

    Detection is stubbed (tested elsewhere); we assert the wrapper's bars list is
    byte-aligned with ``_prepare_symbol_resampled_bars`` so the pipeline's anchor
    and forward-window arithmetic cannot drift from what the detector indexed.
    """
    df = normalize_ohlcv_frame(_raw_minute_frame(n=180), symbol="AAPL")

    canned = {"bos": [{"id": "b1", "time": _T0 + 30 * 60, "price": 102.0, "dir": "UP"}]}
    monkeypatch.setattr(wrapper, "build_explicit_structure_from_bars", lambda *a, **k: canned)

    payload = structure_and_bars_to_pipeline_input(df, symbol="AAPL", timeframe="15m")

    resampled, _tf = wrapper._prepare_symbol_resampled_bars(df, "AAPL", "15m")
    expected_ts = [float(t) for t in resampled["timestamp"].tolist()]
    assert [b["timestamp"] for b in payload["bars"]] == expected_ts
    # Full OHLCV bar: open + volume are carried so the ADR-0019 order-flow
    # candidates (relative_volume / Amihud) have a point-in-time input.
    assert all(
        set(b) == {"timestamp", "open", "high", "low", "close", "volume"}
        for b in payload["bars"]
    )
    expected_vol = [float(v) for v in resampled["volume"].tolist()]
    assert [b["volume"] for b in payload["bars"]] == expected_vol
    expected_open = [float(o) for o in resampled["open"].tolist()]
    assert [b["open"] for b in payload["bars"]] == expected_open
    # as_of defaults to the last resampled bar so the EV-04 guard is always armed.
    assert payload["as_of"] == payload["bars"][-1]["timestamp"]
    assert payload["provenance"]["symbol"] == "AAPL"
    assert payload["structure"]["bos"] == canned["bos"]


def test_provenance_threads_fetch_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fetch window/dataset/schema land in provenance so archives are auditable."""
    df = normalize_ohlcv_frame(_raw_minute_frame(n=180), symbol="AAPL")
    monkeypatch.setattr(
        wrapper,
        "build_explicit_structure_from_bars",
        lambda *a, **k: {"bos": [{"id": "b1", "time": _T0, "price": 100.0, "dir": "UP"}]},
    )
    payload = structure_and_bars_to_pipeline_input(
        df,
        symbol="aapl",
        timeframe="15m",
        dataset="XNAS.ITCH",
        schema="ohlcv-1m",
        start="2023-12-01",
        end="2023-12-31",
    )
    prov = payload["provenance"]
    assert prov["symbol"] == "AAPL"
    assert prov["dataset"] == "XNAS.ITCH"
    assert prov["schema"] == "ohlcv-1m"
    assert prov["window"] == {"start": "2023-12-01", "end": "2023-12-31"}


def test_provenance_fetch_context_defaults_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-CLI callers that omit the window get explicit ``None`` placeholders."""
    df = normalize_ohlcv_frame(_raw_minute_frame(n=180), symbol="AAPL")
    monkeypatch.setattr(
        wrapper,
        "build_explicit_structure_from_bars",
        lambda *a, **k: {"bos": [{"id": "b1", "time": _T0, "price": 100.0, "dir": "UP"}]},
    )
    payload = structure_and_bars_to_pipeline_input(df, symbol="AAPL", timeframe="15m")
    prov = payload["provenance"]
    assert prov["dataset"] is None
    assert prov["schema"] is None
    assert prov["window"] == {"start": None, "end": None}


def test_explicit_as_of_is_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    df = normalize_ohlcv_frame(_raw_minute_frame(n=180), symbol="AAPL")
    monkeypatch.setattr(
        wrapper,
        "build_explicit_structure_from_bars",
        lambda *a, **k: {"fvg": [{"id": "f1", "time": _T0, "low": 99.0, "high": 101.0, "dir": "BULL"}]},
    )
    payload = structure_and_bars_to_pipeline_input(
        df, symbol="AAPL", timeframe="15m", as_of="2023-12-31T00:00:00"
    )
    assert payload["as_of"] == "2023-12-31T00:00:00"


def test_refuses_when_no_structure_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    df = normalize_ohlcv_frame(_raw_minute_frame(n=180), symbol="AAPL")
    monkeypatch.setattr(
        wrapper,
        "build_explicit_structure_from_bars",
        lambda *a, **k: {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []},
    )
    with pytest.raises(ValueError, match="no detected SMC structure"):
        structure_and_bars_to_pipeline_input(df, symbol="AAPL", timeframe="15m")


def test_refuses_when_symbol_absent_from_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    df = normalize_ohlcv_frame(_raw_minute_frame(n=180, symbol="AAPL"), symbol="AAPL")
    monkeypatch.setattr(
        wrapper,
        "build_explicit_structure_from_bars",
        lambda *a, **k: {"bos": [{"id": "b1", "time": _T0, "price": 100.0, "dir": "UP"}]},
    )
    # No resampled bars for an unseen symbol -> honest refusal, not empty payload.
    with pytest.raises(ValueError, match="no resampled"):
        structure_and_bars_to_pipeline_input(df, symbol="ZZZZ", timeframe="15m")


# --- ADR-0016 aggressor-signed trades data path --------------------------------


def _raw_trades_frame(
    offsets_seconds: list[int],
    sizes: list[float],
    sides: list[str],
    *,
    symbol: str = "AAPL",
) -> pd.DataFrame:
    """A synthetic Databento ``trades`` frame on a DatetimeIndex."""
    index = pd.to_datetime(
        [(_T0 + s) * 1_000_000_000 for s in offsets_seconds], utc=True
    )
    return pd.DataFrame(
        {
            "price": np.full(len(offsets_seconds), 100.0),
            "size": sizes,
            "side": sides,
            "symbol": symbol,
        },
        index=pd.DatetimeIndex(index, name="ts_event"),
    )


def test_normalize_trades_frame_from_datetime_index() -> None:
    raw = _raw_trades_frame([0, 30, 90], [10.0, 5.0, 2.0], ["B", "a", "n"])
    out = normalize_trades_frame(raw, symbol="aapl")

    assert list(out.columns) == ["timestamp", "price", "size", "side", "symbol"]
    assert int(out["timestamp"].iloc[0]) == _T0
    assert int(out["timestamp"].iloc[1]) == _T0 + 30
    # side is upper-cased to the Databento enum.
    assert out["side"].tolist() == ["B", "A", "N"]
    assert (out["symbol"] == "AAPL").all()


def test_normalize_trades_frame_rejects_missing_columns() -> None:
    raw = _raw_trades_frame([0, 30], [1.0, 1.0], ["B", "A"]).drop(columns=["side"])
    with pytest.raises(ValueError, match="missing required columns"):
        normalize_trades_frame(raw, symbol="AAPL")


def test_normalize_trades_frame_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        normalize_trades_frame(pd.DataFrame(), symbol="AAPL")


def test_aggregate_signed_volume_signs_and_counts() -> None:
    # Three trades inside one 15m window (the first bucket ends at _T0+100s, the
    # 22:15:00 boundary): B(+10), A(-4), N(0 signed, still counted).
    raw = _raw_trades_frame([0, 60, 100], [10.0, 4.0, 7.0], ["B", "A", "N"])
    trades = normalize_trades_frame(raw, symbol="AAPL")

    agg = aggregate_signed_volume(trades, "15m")

    assert len(agg) == 1
    assert float(agg["signed_volume"].iloc[0]) == 6.0  # 10 - 4 + 0
    assert int(agg["trade_count"].iloc[0]) == 3
    assert float(agg["abs_volume"].iloc[0]) == 21.0  # 10 + 4 + 7 (unsigned sum)


def test_aggregate_signed_volume_uint32_size_no_underflow() -> None:
    # Databento delivers `size` as uint32; a sell aggressor computed as `0 - size`
    # on an unsigned dtype underflows to 2**32 - size. The signed sum must stay a
    # true signed magnitude (|signed_volume| <= total traded size), never ~4.3e9.
    raw = _raw_trades_frame([0, 60], [10.0, 4.0], ["B", "A"])
    raw["size"] = raw["size"].astype("uint32")
    trades = normalize_trades_frame(raw, symbol="AAPL")

    agg = aggregate_signed_volume(trades, "15m")

    assert float(agg["signed_volume"].iloc[0]) == 6.0  # 10 - 4, NOT 10 + (2**32 - 4)
    assert float(agg["abs_volume"].iloc[0]) == 14.0  # 10 + 4, unsigned total



def test_aggregate_signed_volume_empty_input() -> None:
    empty = normalize_trades_frame(
        _raw_trades_frame([0], [1.0], ["B"]), symbol="AAPL"
    ).iloc[0:0]
    agg = aggregate_signed_volume(empty, "15m")
    assert list(agg.columns) == [
        "timestamp",
        "signed_volume",
        "trade_count",
        "abs_volume",
    ]
    assert agg.empty


def test_aggregate_signed_volume_aligns_to_resampled_bars() -> None:
    """LOAD-BEARING: trade buckets share the OHLCV resampler's bucket_end grid."""
    df = normalize_ohlcv_frame(_raw_minute_frame(n=180), symbol="AAPL")
    resampled, _tf = wrapper._prepare_symbol_resampled_bars(df, "AAPL", "15m")
    bar_ts = {int(t) for t in resampled["timestamp"].tolist()}

    # One trade per source minute -> every bucket timestamp must be a real bar.
    offsets = [i * 60 for i in range(180)]
    raw = _raw_trades_frame(offsets, [1.0] * 180, ["B"] * 180)
    trades = normalize_trades_frame(raw, symbol="AAPL")

    agg = aggregate_signed_volume(trades, "15m")
    agg_ts = {int(t) for t in agg["timestamp"].tolist()}

    # Every bucket within the resampler's horizon must be a real bar timestamp.
    # (The OHLCV resampler trims its partial trailing bucket; the trades
    # aggregation keeps it, but the producer merge only uses the intersection,
    # so a bucket beyond the last bar is harmless.)
    horizon = max(bar_ts)
    assert {t for t in agg_ts if t <= horizon}.issubset(bar_ts)
    assert int(agg["trade_count"].sum()) == 180


def _raw_opra_trades(
    offsets: list[int],
    sizes: list[float],
    prices: list[float],
    sides: list[str],
    option_types: list[str] | None = None,
) -> pd.DataFrame:
    """A raw OPRA ``trades`` frame already mapped to the underlying.

    One row per option print with epoch-second ``timestamp``, ``size``
    (contracts), ``price`` (per-contract premium), ``side`` (A/B/N) and
    ``option_type`` (C/P/""). Defaults to all-calls so aggressor-focused tests
    keep their arithmetic; put/unknown behavior gets its own explicit frames.
    """
    return pd.DataFrame(
        {
            "timestamp": [_T0 + o for o in offsets],
            "size": sizes,
            "price": prices,
            "side": sides,
            "option_type": option_types if option_types is not None else ["C"] * len(offsets),
        }
    )


def test_normalize_opra_trades_frame_from_datetime_index() -> None:
    index = pd.to_datetime(
        [(_T0 + i * 60) * 1_000_000_000 for i in range(3)], utc=True
    )
    raw = pd.DataFrame(
        {"price": [2.0, 3.0, 1.0], "size": [10, 4, 7], "side": ["a", "B", "n"]},
        index=pd.DatetimeIndex(index, name="ts_event"),
    )

    out = normalize_opra_trades_frame(raw, underlying="aapl")

    assert list(out.columns) == [
        "timestamp",
        "price",
        "size",
        "side",
        "option_type",
        "underlying",
    ]
    assert out["timestamp"].tolist() == [_T0, _T0 + 60, _T0 + 120]
    assert out["side"].tolist() == ["A", "B", "N"]  # upper-cased Databento enum
    # No OSI ``symbol`` column in the raw frame -> option type unknown ("")
    # on every row (the aggregator then keeps these prints unsigned).
    assert out["option_type"].tolist() == ["", "", ""]
    assert out["size"].dtype == np.float64
    assert (out["underlying"] == "AAPL").all()  # parent symbology stamp


def test_normalize_opra_trades_frame_from_ts_event_column() -> None:
    raw = pd.DataFrame(
        {
            "ts_event": pd.to_datetime([_T0 * 1_000_000_000], utc=True),
            "price": [2.5],
            "size": [3],
            "side": ["A"],
        }
    )

    out = normalize_opra_trades_frame(raw, underlying="MSFT")

    assert out["timestamp"].tolist() == [_T0]
    assert out["underlying"].tolist() == ["MSFT"]


def test_normalize_opra_trades_frame_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        normalize_opra_trades_frame(pd.DataFrame(), underlying="AAPL")


def test_normalize_opra_trades_frame_rejects_missing_columns() -> None:
    raw = pd.DataFrame(
        {"ts_event": pd.to_datetime([_T0 * 1_000_000_000], utc=True), "price": [2.0]}
    )
    with pytest.raises(ValueError, match="missing required columns"):
        normalize_opra_trades_frame(raw, underlying="AAPL")


def test_normalize_opra_trades_frame_drops_unpriced_rows() -> None:
    raw = pd.DataFrame(
        {
            "ts_event": pd.to_datetime(
                [_T0 * 1_000_000_000, (_T0 + 60) * 1_000_000_000], utc=True
            ),
            "price": [2.0, None],
            "size": [10, 4],
            "side": ["A", "B"],
        }
    )

    out = normalize_opra_trades_frame(raw, underlying="AAPL")

    # The unpriced print cannot contribute notional and is dropped.
    assert len(out) == 1
    assert out["timestamp"].tolist() == [_T0]


def test_normalize_opra_trades_frame_feeds_aggregation() -> None:
    """The normaliser output is consumed verbatim by the aggregator.

    Both prints are aggressive BUYS (side A); the sign difference comes purely
    from the contract direction parsed off the OSI symbol: the bought call is
    bullish (+2000), the bought put is bearish (-1200).
    """
    index = pd.to_datetime(
        [(_T0 + i * 60) * 1_000_000_000 for i in range(2)], utc=True
    )
    raw = pd.DataFrame(
        {
            "price": [2.0, 3.0],
            "size": [10, 4],
            "side": ["A", "A"],
            "symbol": ["AAPL  260821C00190000", "AAPL  260821P00185000"],
        },
        index=pd.DatetimeIndex(index, name="ts_event"),
    )

    normalized = normalize_opra_trades_frame(raw, underlying="AAPL")
    assert normalized["option_type"].tolist() == ["C", "P"]
    agg = aggregate_signed_uoa_notional(normalized, "15m")

    assert float(agg["uoa_signed_notional"].iloc[0]) == 800.0  # +2000 - 1200
    assert float(agg["uoa_abs_notional"].iloc[0]) == 3200.0


def _raw_opra_tcbbo(
    offsets: list[int],
    sizes: list[float],
    prices: list[float],
    bids: list[float],
    asks: list[float],
    *,
    raw_sides: list[str] | None = None,
    symbols: list[str] | None = None,
) -> pd.DataFrame:
    """A raw OPRA ``tcbbo`` frame: trade price + consolidated NBBO
    (``bid_px_00``/``ask_px_00``) + the mapped OSI ``symbol``.

    The raw ``side`` defaults to ``"N"`` for every row to mirror the live OPRA
    tape (no reliable aggressor flag), proving the normaliser reconstructs the
    aggressor from the quote rule rather than trusting the field. ``symbol``
    defaults to all-call OSI symbols (the live ``to_df()`` mapping always
    attaches one); pass put symbols to exercise the direction sign.
    """
    n = len(offsets)
    index = pd.to_datetime([(_T0 + o) * 1_000_000_000 for o in offsets], utc=True)
    return pd.DataFrame(
        {
            "price": prices,
            "size": sizes,
            "side": raw_sides if raw_sides is not None else ["N"] * n,
            "bid_px_00": bids,
            "ask_px_00": asks,
            "symbol": symbols if symbols is not None else ["AAPL  260821C00190000"] * n,
        },
        index=pd.DatetimeIndex(index, name="ts_event"),
    )


def test_quote_rule_opra_aggressor_classifies_against_nbbo() -> None:
    price = pd.Series([2.0, 1.0, 1.5, 1.5, 2.0])
    bid = pd.Series([1.4, 1.4, 1.4, float("nan"), 2.0])  # row3 missing, row4 locked
    ask = pd.Series([2.0, 2.0, 2.0, 2.0, 2.0])

    side = _quote_rule_opra_aggressor(price, bid, ask)

    # price>=ask -> A; price<=bid -> B; inside spread / missing quote / locked
    # (ask==bid) -> N (honest unsigned).
    assert side.tolist() == ["A", "B", "N", "N", "N"]


def test_quote_rule_opra_aggressor_crossed_book_stays_unsigned() -> None:
    # LOAD-BEARING guard on the ``ask > bid`` validity check. In a CROSSED book
    # (ask strictly < bid -- a real OPRA tape artifact, distinct from a locked
    # ask==bid book) a single price can satisfy BOTH ``price >= ask`` AND
    # ``price <= bid`` at once. Without the validity gate the row would be
    # classified as A *and* B (last-write-wins -> a bogus sign); the gate must
    # force it to honest ``N``. Also pins the still-uncovered missing-ask and
    # missing-price branches so a future refactor cannot silently sign them.
    price = pd.Series([1.5, 2.0, float("nan")])  # row0 inside the crossed quotes
    bid = pd.Series([2.0, 2.0, 1.0])  # row0 bid(2.0) > ask(1.0) -> crossed
    ask = pd.Series([1.0, float("nan"), 2.0])  # row1 missing ask; row2 valid+NaN price

    side = _quote_rule_opra_aggressor(price, bid, ask)

    # crossed book -> N; missing ask -> N; missing price -> N.
    assert side.tolist() == ["N", "N", "N"]


def test_normalize_opra_tcbbo_reconstructs_side_from_quote_rule() -> None:
    # The raw side is uniformly "N" (the live OPRA reality); the quote rule must
    # recover A (ask-lift) and B (bid-hit) from the NBBO so the signed notional
    # is non-degenerate -- the entire point of the trades->tcbbo switch.
    raw = _raw_opra_tcbbo(
        offsets=[0, 60, 100],
        sizes=[10.0, 4.0, 7.0],
        prices=[2.0, 3.0, 1.5],  # at/above ask, at/below bid, inside spread
        bids=[1.8, 3.2, 1.0],
        asks=[2.0, 3.4, 2.0],
    )

    out = normalize_opra_trades_frame(raw, underlying="AAPL")
    assert out["side"].tolist() == ["A", "B", "N"]

    agg = aggregate_signed_uoa_notional(out, "15m")
    # A: +2*10*100=+2000 ; B: -3*4*100=-1200 ; N: 1.5*7*100=1050 abs, 0 signed.
    assert float(agg["uoa_signed_notional"].iloc[0]) == 800.0  # 2000 - 1200
    assert float(agg["uoa_abs_notional"].iloc[0]) == 4250.0  # 2000 + 1200 + 1050


def test_normalize_opra_tcbbo_quote_rule_overrides_raw_side() -> None:
    # Even when the raw frame carries a (stale/unreliable) non-N side, the NBBO
    # quote rule is authoritative when bid/ask are present.
    raw = _raw_opra_tcbbo(
        offsets=[0, 60],
        sizes=[10.0, 4.0],
        prices=[2.0, 3.0],
        bids=[1.8, 3.2],
        asks=[2.0, 3.4],
        raw_sides=["B", "A"],  # deliberately the opposite of the quote-rule answer
    )

    out = normalize_opra_trades_frame(raw, underlying="AAPL")
    # Quote rule (price>=ask -> A, price<=bid -> B) wins over the raw enum.
    assert out["side"].tolist() == ["A", "B"]


def test_aggregate_signed_uoa_notional_inverse_aggressor_signs() -> None:
    # Three OPRA CALL prints in one 15m window. OPRA convention is INVERSE of
    # equity:
    #   A (ask-lift) = call bought = bullish (+): size 10 * price 2 * 100 = +2000
    #   B (bid-hit)  = call sold   = bearish (-): size  4 * price 3 * 100 = -1200
    #   N (cross)    = unsigned (0 signed), still counted: size 7 * price 1 * 100 = 700 abs
    raw = _raw_opra_trades([0, 60, 100], [10.0, 4.0, 7.0], [2.0, 3.0, 1.0], ["A", "B", "N"])

    agg = aggregate_signed_uoa_notional(raw, "15m")

    assert len(agg) == 1
    assert float(agg["uoa_signed_notional"].iloc[0]) == 800.0  # 2000 - 1200 + 0
    assert int(agg["uoa_trade_count"].iloc[0]) == 3
    assert float(agg["uoa_abs_notional"].iloc[0]) == 3900.0  # 2000 + 1200 + 700


def test_aggregate_signed_uoa_notional_uint32_size_no_underflow() -> None:
    # Databento delivers `size` as uint32; a bearish print computed as `0 - n`
    # on an unsigned dtype underflows. The signed sum must stay a true signed
    # magnitude (|signed| <= total premium), never ~4.3e9 * price * 100.
    raw = _raw_opra_trades([0, 60], [10.0, 4.0], [2.0, 3.0], ["A", "B"])
    raw["size"] = raw["size"].astype("uint32")

    agg = aggregate_signed_uoa_notional(raw, "15m")

    assert float(agg["uoa_signed_notional"].iloc[0]) == 800.0  # 2000 - 1200
    assert float(agg["uoa_abs_notional"].iloc[0]) == 3200.0  # 2000 + 1200


def test_aggregate_signed_uoa_notional_put_flow_signs_economic() -> None:
    # The call/put blind spot (fixed 2026-08-04): the sign must be aggressor x
    # contract direction, not aggressor alone. Two PUT prints:
    #   A (ask-lift) on a put = put BOUGHT = bearish (-): 10 * 2 * 100 = -2000
    #   B (bid-hit)  on a put = put SOLD   = bullish (+):  4 * 3 * 100 = +1200
    raw = _raw_opra_trades(
        [0, 60], [10.0, 4.0], [2.0, 3.0], ["A", "B"], option_types=["P", "P"]
    )

    agg = aggregate_signed_uoa_notional(raw, "15m")

    assert float(agg["uoa_signed_notional"].iloc[0]) == -800.0  # -2000 + 1200
    assert float(agg["uoa_abs_notional"].iloc[0]) == 3200.0  # magnitude unaffected


def test_aggregate_signed_uoa_notional_unknown_option_type_stays_unsigned() -> None:
    # A print whose contract direction is unknown ("" value or the column
    # missing entirely) contributes 0 to the signed sum -- assuming "call"
    # would silently restore the blind spot -- but stays in abs + count.
    with_blank = _raw_opra_trades(
        [0, 60], [10.0, 4.0], [2.0, 3.0], ["A", "A"], option_types=["", "C"]
    )
    agg = aggregate_signed_uoa_notional(with_blank, "15m")
    assert float(agg["uoa_signed_notional"].iloc[0]) == 1200.0  # only the call
    assert float(agg["uoa_abs_notional"].iloc[0]) == 3200.0
    assert int(agg["uoa_trade_count"].iloc[0]) == 2

    without_column = _raw_opra_trades([0], [10.0], [2.0], ["A"]).drop(
        columns=["option_type"]
    )
    agg = aggregate_signed_uoa_notional(without_column, "15m")
    assert float(agg["uoa_signed_notional"].iloc[0]) == 0.0
    assert float(agg["uoa_abs_notional"].iloc[0]) == 2000.0


def test_normalize_opra_frame_parses_option_type_from_osi_symbol() -> None:
    # Real OSI shapes from the live parent-symbology mapping (6-char padded
    # root + yymmdd + C/P + 8 strike digits); a non-OSI value degrades to ""
    # (unknown -> unsigned) instead of raising or guessing.
    raw = pd.DataFrame(
        {
            "ts_event": pd.to_datetime(
                [(_T0 + o) * 1_000_000_000 for o in (0, 60, 120)], utc=True
            ),
            "price": [2.0, 3.0, 1.0],
            "size": [1, 2, 3],
            "side": ["A", "B", "N"],
            "symbol": [
                "SPY   260804C00757000",
                "SPY   260803P00748000",
                "not-an-osi-symbol",
            ],
        }
    )

    out = normalize_opra_trades_frame(raw, underlying="SPY")

    assert out["option_type"].tolist() == ["C", "P", ""]


def test_normalize_opra_tcbbo_put_buy_counts_bearish_end_to_end() -> None:
    # End-to-end through the live path (quote-rule aggressor + OSI parse): an
    # ask-lifting print on a PUT must come out bearish. Before the 2026-08-04
    # fix this exact frame aggregated to +2000 (counted as bullish).
    raw = _raw_opra_tcbbo(
        offsets=[0],
        sizes=[10.0],
        prices=[2.0],  # at the ask -> aggressive buyer (A)
        bids=[1.8],
        asks=[2.0],
        symbols=["SPY   260803P00748000"],
    )

    out = normalize_opra_trades_frame(raw, underlying="SPY")
    assert out["side"].tolist() == ["A"]
    assert out["option_type"].tolist() == ["P"]

    agg = aggregate_signed_uoa_notional(out, "15m")
    assert float(agg["uoa_signed_notional"].iloc[0]) == -2000.0
    assert float(agg["uoa_abs_notional"].iloc[0]) == 2000.0


def test_aggregate_signed_uoa_notional_empty_input() -> None:
    agg = aggregate_signed_uoa_notional(pd.DataFrame(), "15m")
    assert list(agg.columns) == [
        "timestamp",
        "uoa_signed_notional",
        "uoa_trade_count",
        "uoa_abs_notional",
    ]
    assert agg.empty


def test_aggregate_signed_uoa_notional_aligns_to_resampled_bars() -> None:
    """LOAD-BEARING: option-print buckets share the underlying's bar grid."""
    df = normalize_ohlcv_frame(_raw_minute_frame(n=180), symbol="AAPL")
    resampled, _tf = wrapper._prepare_symbol_resampled_bars(df, "AAPL", "15m")
    bar_ts = {int(t) for t in resampled["timestamp"].tolist()}

    offsets = [i * 60 for i in range(180)]
    raw = _raw_opra_trades(offsets, [1.0] * 180, [1.5] * 180, ["A"] * 180)

    agg = aggregate_signed_uoa_notional(raw, "15m")
    agg_ts = {int(t) for t in agg["timestamp"].tolist()}

    horizon = max(bar_ts)
    assert {t for t in agg_ts if t <= horizon}.issubset(bar_ts)
    assert int(agg["uoa_trade_count"].sum()) == 180


def test_payload_embeds_signed_uoa_when_opra_trades_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    df = normalize_ohlcv_frame(_raw_minute_frame(n=180), symbol="AAPL")
    monkeypatch.setattr(
        wrapper,
        "build_explicit_structure_from_bars",
        lambda *a, **k: {"bos": [{"id": "b1", "time": _T0, "price": 100.0, "dir": "UP"}]},
    )
    offsets = [i * 60 for i in range(180)]
    raw = _raw_opra_trades(offsets, [5.0] * 180, [2.0] * 180, ["A"] * 180)

    payload = structure_and_bars_to_pipeline_input(
        df, symbol="AAPL", timeframe="15m", opra_trades=raw
    )

    embedded = [b for b in payload["bars"] if "uoa_signed_notional" in b]
    assert embedded, "expected at least one bar to carry embedded UOA notional"
    for bar in embedded:
        assert "uoa_abs_notional" in bar
        # All prints are bullish (A) -> signed == abs on every embedded bar.
        assert bar["uoa_signed_notional"] == bar["uoa_abs_notional"]
        assert bar["uoa_abs_notional"] > 0.0


def test_provenance_records_with_opra_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ``with_opra`` provenance flag reflects whether OPRA prints were fed."""
    df = normalize_ohlcv_frame(_raw_minute_frame(n=180), symbol="AAPL")
    monkeypatch.setattr(
        wrapper,
        "build_explicit_structure_from_bars",
        lambda *a, **k: {"bos": [{"id": "b1", "time": _T0, "price": 100.0, "dir": "UP"}]},
    )

    without = structure_and_bars_to_pipeline_input(df, symbol="AAPL", timeframe="15m")
    assert without["provenance"]["with_opra"] is False

    offsets = [i * 60 for i in range(180)]
    raw = _raw_opra_trades(offsets, [5.0] * 180, [2.0] * 180, ["A"] * 180)
    with_flow = structure_and_bars_to_pipeline_input(
        df, symbol="AAPL", timeframe="15m", opra_trades=raw
    )
    assert with_flow["provenance"]["with_opra"] is True


def test_payload_embeds_signed_volume_when_trades_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    df = normalize_ohlcv_frame(_raw_minute_frame(n=180), symbol="AAPL")
    monkeypatch.setattr(
        wrapper,
        "build_explicit_structure_from_bars",
        lambda *a, **k: {"bos": [{"id": "b1", "time": _T0, "price": 100.0, "dir": "UP"}]},
    )
    offsets = [i * 60 for i in range(180)]
    trades = normalize_trades_frame(
        _raw_trades_frame(offsets, [1.0] * 180, ["B"] * 180), symbol="AAPL"
    )

    payload = structure_and_bars_to_pipeline_input(
        df, symbol="AAPL", timeframe="15m", trades=trades
    )

    enriched = [b for b in payload["bars"] if "signed_volume" in b]
    assert enriched, "expected at least one bar to carry signed volume"
    for bar in enriched:
        assert set(bar) == {
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "signed_volume",
            "trade_count",
            "abs_volume",
        }
        assert bar["signed_volume"] > 0.0  # all buys
        assert bar["trade_count"] >= 1
        assert bar["abs_volume"] >= bar["signed_volume"]
    assert payload["provenance"]["with_trades"] is True


def test_payload_omits_signed_volume_without_trades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    df = normalize_ohlcv_frame(_raw_minute_frame(n=180), symbol="AAPL")
    monkeypatch.setattr(
        wrapper,
        "build_explicit_structure_from_bars",
        lambda *a, **k: {"bos": [{"id": "b1", "time": _T0, "price": 100.0, "dir": "UP"}]},
    )
    payload = structure_and_bars_to_pipeline_input(df, symbol="AAPL", timeframe="15m")

    assert all("signed_volume" not in b for b in payload["bars"])
    assert payload["provenance"]["with_trades"] is False


class TestAvailableEndClamp:
    """Intraday, Databento historical rejects end=now with a 422
    ``data_end_after_available_end`` naming the authoritative available end
    (metadata.get_dataset_range only advertises the T-1 boundary, so there is
    no proactive clamp source). The wrapper must retry exactly once with the
    advertised end — the 2026-08-17 16:05 campaign fire died on this."""

    _MESSAGE = (
        "422 data_end_after_available_end\n"
        "The dataset XNAS.ITCH has data available up to "
        "'2026-08-17 14:00:00+00:00'. The `end` in the query "
        "('2026-08-17 14:05:00+00:00') is after the available range."
    )

    def _error(self):
        from databento.common.error import BentoClientError

        return BentoClientError(
            http_status=422, http_body=None, message=self._MESSAGE
        )

    def test_a_rejected_end_is_clamped_to_the_advertised_available_end(self) -> None:
        calls: list[dict] = []
        sentinel = object()

        def fake_get_range(client, *, context, **kwargs):
            calls.append(dict(kwargs))
            if len(calls) == 1:
                raise self._error()
            return sentinel

        result = wrapper._get_range_clamped_to_available_end(
            fake_get_range,
            object(),
            context="test",
            dataset="XNAS.ITCH",
            end="2026-08-17T14:05:00",
        )

        assert result is sentinel
        assert len(calls) == 2
        assert calls[1]["end"] == "2026-08-17 14:00:00+00:00"
        assert calls[1]["dataset"] == "XNAS.ITCH"

    def test_a_second_rejection_is_not_retried_forever(self) -> None:
        from databento.common.error import BentoClientError

        calls: list[int] = []

        def always_reject(client, *, context, **kwargs):
            calls.append(1)
            raise self._error()

        with pytest.raises(BentoClientError):
            wrapper._get_range_clamped_to_available_end(
                always_reject, object(), context="test", end="x"
            )

        assert len(calls) == 2

    def test_unrelated_client_errors_pass_through_unclamped(self) -> None:
        from databento.common.error import BentoClientError

        calls: list[int] = []

        def reject_auth(client, *, context, **kwargs):
            calls.append(1)
            raise BentoClientError(
                http_status=401, http_body=None, message="401 auth_failed"
            )

        with pytest.raises(BentoClientError):
            wrapper._get_range_clamped_to_available_end(
                reject_auth, object(), context="test", end="x"
            )

        assert len(calls) == 1
