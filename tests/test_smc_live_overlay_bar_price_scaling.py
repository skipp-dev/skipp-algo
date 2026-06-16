"""L2 regression: feed._record_to_bar() must divide OHLC prices by 1e9.

Databento DBN ``OhlcvMsg`` stores prices as nanosecond-precision fixed-point
integers (1 price unit == 1e-9 USD, i.e. $ price * 1_000_000_000 == stored int).
feed._record_to_bar() must divide each price field by 1e9 before writing to the
cache.  A regression (e.g. wrong scale, missing division) would give downstream
consumers and the Pine script nonsensical prices without any other visible error.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


# ---------------------------------------------------------------------------
# Helper: lightweight stand-in for databento OhlcvMsg
# ---------------------------------------------------------------------------

def _make_record(
    *,
    open_: int,
    high: int,
    low: int,
    close: int,
    volume: int,
    ts_event: int = 0,
) -> Any:
    """Return an object that quacks like databento.OhlcvMsg (attribute access)."""
    hd = SimpleNamespace(ts_event=ts_event)
    return SimpleNamespace(
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        hd=hd,
    )


# ---------------------------------------------------------------------------
# Import the function under test
# ---------------------------------------------------------------------------

from services.live_overlay_daemon.feed import _record_to_bar  # noqa: E402


class TestRecordToBar:
    """_record_to_bar correctly decodes Databento fixed-point prices."""

    # Databento stores $100.00 as 100_000_000_000 (1e9 per dollar)
    _USD_100_INT = 100_000_000_000
    _USD_100_FLOAT = 100.0

    def test_open_scaled(self) -> None:
        rec = _make_record(open_=self._USD_100_INT, high=1, low=1, close=1, volume=0)
        bar = _record_to_bar(rec)
        assert bar is not None
        assert bar["open"] == pytest.approx(self._USD_100_FLOAT), (
            "open price not divided by 1e9 — Databento fixed-point scale broken"
        )

    def test_high_scaled(self) -> None:
        rec = _make_record(open_=1, high=self._USD_100_INT, low=1, close=1, volume=0)
        bar = _record_to_bar(rec)
        assert bar is not None
        assert bar["high"] == pytest.approx(self._USD_100_FLOAT)

    def test_low_scaled(self) -> None:
        rec = _make_record(open_=1, high=1, low=self._USD_100_INT, close=1, volume=0)
        bar = _record_to_bar(rec)
        assert bar is not None
        assert bar["low"] == pytest.approx(self._USD_100_FLOAT)

    def test_close_scaled(self) -> None:
        rec = _make_record(open_=1, high=1, low=1, close=self._USD_100_INT, volume=0)
        bar = _record_to_bar(rec)
        assert bar is not None
        assert bar["close"] == pytest.approx(self._USD_100_FLOAT)

    def test_volume_not_scaled(self) -> None:
        """Volume is already a plain integer — must NOT be divided by 1e9."""
        rec = _make_record(open_=1, high=1, low=1, close=1, volume=42_000)
        bar = _record_to_bar(rec)
        assert bar is not None
        assert bar["volume"] == 42_000, (
            "volume must pass through without 1e9 scaling"
        )

    def test_ts_event_passthrough(self) -> None:
        ts = 1_700_000_000_000_000_000  # nanoseconds epoch
        rec = _make_record(open_=1, high=1, low=1, close=1, volume=0, ts_event=ts)
        bar = _record_to_bar(rec)
        assert bar is not None
        assert bar["ts_event"] == ts

    def test_realistic_es_price(self) -> None:
        """Smoke-test with a realistic ES mini price (~5800 USD)."""
        price_int = 5_800_250_000_000  # 5800.25 in Databento fixed-point
        rec = _make_record(
            open_=price_int,
            high=price_int,
            low=price_int,
            close=price_int,
            volume=1_200,
        )
        bar = _record_to_bar(rec)
        assert bar is not None
        assert bar["open"] == pytest.approx(5800.25)
        assert bar["close"] == pytest.approx(5800.25)
        assert bar["volume"] == 1_200

    def test_returns_none_on_broken_record(self) -> None:
        """A record that raises on attribute access must yield None (no crash)."""
        bar = _record_to_bar(object())  # plain object has no .open / .hd
        assert bar is None


import pytest  # noqa: E402 — imported at bottom to keep test body clean
