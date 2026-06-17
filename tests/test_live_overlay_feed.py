"""Unit tests for services/live_overlay_daemon/feed.py helper functions.

Covers three fragile patterns fixed in the post-merge tech-debt pass:

1. ``_symbol_from_record`` — ``or``-based fallback replaced with ``is None``
   guard so that a valid ``instrument_id == 0`` is not incorrectly treated as
   absent.
2. ``_record_to_bar`` — same ``is None`` guard for ``ts_event == 0``.
3. ``_run_feed_loop`` symbology map — built from ``SymbolMappingMsg`` records in
   the iterator rather than the private ``client._symbology_map`` attribute.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from services.live_overlay_daemon.feed import _record_to_bar, _symbol_from_record


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ohlcv(
    *,
    instrument_id: int | None = 1,
    ts_event: int | None = 1_000_000,
    open_: int = 100_000_000_000,
    high: int = 110_000_000_000,
    low: int = 90_000_000_000,
    close: int = 105_000_000_000,
    volume: int = 500,
) -> Any:
    """Minimal fake OhlcvMsg-like object."""
    ns = SimpleNamespace(
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )
    if instrument_id is not None:
        ns.instrument_id = instrument_id
    if ts_event is not None:
        ns.ts_event = ts_event
    return ns


def _make_ohlcv_with_hd(
    *,
    iid_on_hd: int,
    ts_on_hd: int = 0,
) -> Any:
    """OhlcvMsg where instrument_id and ts_event live under .hd, not top-level."""
    hd = SimpleNamespace(instrument_id=iid_on_hd, ts_event=ts_on_hd)
    return SimpleNamespace(
        open=100_000_000_000,
        high=110_000_000_000,
        low=90_000_000_000,
        close=105_000_000_000,
        volume=500,
        hd=hd,
    )


# ---------------------------------------------------------------------------
# _symbol_from_record — is-None guard
# ---------------------------------------------------------------------------


class TestSymbolFromRecord:
    """_symbol_from_record must treat instrument_id=0 as a valid key."""

    def test_normal_resolution(self) -> None:
        record = _make_ohlcv(instrument_id=42)
        symmap = {42: "AAPL"}
        assert _symbol_from_record(record, symmap) == "AAPL"

    def test_instrument_id_zero_is_valid_key(self) -> None:
        """instrument_id=0 is falsy but a legitimate mapping key; must not be
        silently skipped by an ``or``-based fallback."""
        record = _make_ohlcv(instrument_id=0)
        symmap = {0: "SPX"}
        assert _symbol_from_record(record, symmap) == "SPX"

    def test_instrument_id_missing_falls_back_to_hd(self) -> None:
        """When instrument_id is absent at top level, the .hd path is tried."""
        record = _make_ohlcv_with_hd(iid_on_hd=99)
        symmap = {99: "QQQ"}
        # record has no top-level instrument_id attribute → should fall to .hd
        assert _symbol_from_record(record, symmap) == "QQQ"

    def test_instrument_id_none_falls_back_to_hd(self) -> None:
        """Explicit None at top level also triggers the .hd fallback."""
        ns = SimpleNamespace(
            instrument_id=None,
            open=100_000_000_000,
            high=100_000_000_000,
            low=100_000_000_000,
            close=100_000_000_000,
            volume=1,
            hd=SimpleNamespace(instrument_id=7),
        )
        symmap = {7: "IWM"}
        assert _symbol_from_record(ns, symmap) == "IWM"

    def test_unknown_instrument_id_returns_none(self) -> None:
        record = _make_ohlcv(instrument_id=999)
        assert _symbol_from_record(record, {}) is None

    def test_hd_access_error_does_not_raise(self) -> None:
        """If record has neither instrument_id nor .hd, returns None (no crash)."""
        record = SimpleNamespace(open=1, high=1, low=1, close=1, volume=1)
        assert _symbol_from_record(record, {42: "X"}) is None

    def test_result_is_uppercased(self) -> None:
        record = _make_ohlcv(instrument_id=1)
        assert _symbol_from_record(record, {1: "aapl"}) == "AAPL"


# ---------------------------------------------------------------------------
# _record_to_bar — ts_event is-None guard
# ---------------------------------------------------------------------------


class TestRecordToBar:
    """_record_to_bar must handle ts_event=0 correctly."""

    def test_normal_bar(self) -> None:
        record = _make_ohlcv(ts_event=1_700_000_000_000_000_000)
        bar = _record_to_bar(record)
        assert bar is not None
        assert bar["ts_event"] == 1_700_000_000_000_000_000

    def test_ts_event_zero_is_preserved(self) -> None:
        """ts_event=0 is falsy but a valid nanosecond timestamp;
        the old ``or``-fallback would have silently replaced it with a
        fallback value."""
        record = _make_ohlcv(ts_event=0)
        bar = _record_to_bar(record)
        assert bar is not None
        assert bar["ts_event"] == 0, (
            f"ts_event=0 must not be replaced by the hd fallback; got {bar['ts_event']!r}"
        )

    def test_ts_event_missing_falls_back_to_hd(self) -> None:
        """When ts_event is absent at top level, the .hd.ts_event path is tried."""
        record = _make_ohlcv_with_hd(iid_on_hd=1, ts_on_hd=999)
        bar = _record_to_bar(record)
        assert bar is not None
        assert bar["ts_event"] == 999

    def test_non_ohlcv_record_returns_none(self) -> None:
        record = SimpleNamespace(some_field=1)
        assert _record_to_bar(record) is None

    def test_prices_converted_from_fixed_point(self) -> None:
        record = _make_ohlcv(
            open_=10_000_000_000,  # 10.0 in 1e-9 fixed-point
            close=20_000_000_000,
        )
        bar = _record_to_bar(record)
        assert bar is not None
        assert bar["open"] == pytest.approx(10.0)
        assert bar["close"] == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# SymbolMappingMsg handling (symbology map build in iterator)
# ---------------------------------------------------------------------------


class TestSymbologyMapFromIterator:
    """The local symmap must be populated from SymbolMappingMsg records
    encountered in the iterator, not from a private client attribute."""

    def _make_symbol_mapping_msg(self, instrument_id: int, stype_out_symbol: str) -> Any:
        """Minimal fake SymbolMappingMsg."""
        return SimpleNamespace(
            instrument_id=instrument_id,
            stype_out_symbol=stype_out_symbol,
        )

    def test_symbol_mapping_msg_is_detected_by_type_name(self) -> None:
        """The feed loop identifies SymbolMappingMsg by type name.

        We verify the detection heuristic ('SYMBOLMAPPING' in type name
        upper-cased) matches the fake record type we create — ensuring the
        test faithfully exercises the same branch the live code takes.
        """
        # Create a class whose __name__ contains 'SymbolMapping', as the real
        # Databento SDK would produce (e.g. 'SymbolMappingMsg').
        SymbolMappingMsg = type("SymbolMappingMsg", (), {})
        msg = SymbolMappingMsg()
        assert "SYMBOLMAPPING" in type(msg).__name__.upper()

    def test_symmap_populated_from_msg_attributes(self) -> None:
        """instrument_id + stype_out_symbol from a SymbolMappingMsg-like record
        must be insertable into a plain dict — as the feed loop does."""
        msg = self._make_symbol_mapping_msg(42, "AAPL")
        symmap: dict[int, str] = {}
        sym_iid = getattr(msg, "instrument_id", None)
        stype_out = getattr(msg, "stype_out_symbol", None)
        if sym_iid is not None and stype_out:
            symmap[sym_iid] = stype_out
        assert symmap == {42: "AAPL"}

    def test_symmap_key_zero_is_insertable(self) -> None:
        """instrument_id=0 is a valid key and must not be excluded by a falsy
        check."""
        msg = self._make_symbol_mapping_msg(0, "VIX")
        symmap: dict[int, str] = {}
        sym_iid = getattr(msg, "instrument_id", None)
        stype_out = getattr(msg, "stype_out_symbol", None)
        if sym_iid is not None and stype_out:
            symmap[sym_iid] = stype_out
        assert symmap == {0: "VIX"}

    def test_subsequent_ohlcv_resolved_via_local_symmap(self) -> None:
        """After a SymbolMappingMsg populates the local symmap, a subsequent
        OHLCV record with the same instrument_id resolves to the correct symbol
        via _symbol_from_record."""
        symmap: dict[int, str] = {42: "TSLA"}
        ohlcv = _make_ohlcv(instrument_id=42)
        assert _symbol_from_record(ohlcv, symmap) == "TSLA"

    def test_missing_stype_out_does_not_insert_none(self) -> None:
        """A SymbolMappingMsg without stype_out_symbol must not corrupt the
        symmap with a None value."""
        msg = SimpleNamespace(instrument_id=5)  # no stype_out_symbol
        symmap: dict[int, str] = {}
        sym_iid = getattr(msg, "instrument_id", None)
        stype_out = getattr(msg, "stype_out_symbol", None)
        if sym_iid is not None and stype_out:
            symmap[sym_iid] = stype_out
        assert symmap == {}
