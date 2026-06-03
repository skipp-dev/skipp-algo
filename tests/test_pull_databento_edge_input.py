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
    aggregate_signed_volume,
    normalize_ohlcv_frame,
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


def test_aggregate_signed_volume_uint32_size_no_underflow() -> None:
    # Databento delivers `size` as uint32; a sell aggressor computed as `0 - size`
    # on an unsigned dtype underflows to 2**32 - size. The signed sum must stay a
    # true signed magnitude (|signed_volume| <= total traded size), never ~4.3e9.
    raw = _raw_trades_frame([0, 60], [10.0, 4.0], ["B", "A"])
    raw["size"] = raw["size"].astype("uint32")
    trades = normalize_trades_frame(raw, symbol="AAPL")

    agg = aggregate_signed_volume(trades, "15m")

    assert float(agg["signed_volume"].iloc[0]) == 6.0  # 10 - 4, NOT 10 + (2**32 - 4)



def test_aggregate_signed_volume_empty_input() -> None:
    empty = normalize_trades_frame(
        _raw_trades_frame([0], [1.0], ["B"]), symbol="AAPL"
    ).iloc[0:0]
    agg = aggregate_signed_volume(empty, "15m")
    assert list(agg.columns) == ["timestamp", "signed_volume", "trade_count"]
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
        }
        assert bar["signed_volume"] > 0.0  # all buys
        assert bar["trade_count"] >= 1
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
