"""Tests for scripts.imbalance_data (C13/T8.1)."""

from __future__ import annotations

import datetime as _dt

from scripts.imbalance_data import (
    GENERIC_TICK_AUCTION,
    IMBALANCE_SCHEMA_VERSION,
    LISTING_TO_IMBALANCE_FEED,
    TICK_AUCTION_IMBALANCE,
    TICK_AUCTION_PRICE,
    TICK_AUCTION_VOLUME,
    TICK_REGULATORY_IMBALANCE,
    build_snapshot_from_ticks,
    build_unavailable_snapshot,
    classify_imbalance_side,
    listing_to_imbalance_feed,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_schema_version_pinned() -> None:
    assert IMBALANCE_SCHEMA_VERSION == "1.0.0"


def test_generic_tick_auction_is_225() -> None:
    # TWS API: genericTick "225" enables tick IDs 34/35/36/61.
    assert GENERIC_TICK_AUCTION == "225"


def test_tick_ids_pinned_to_tws_doc() -> None:
    assert TICK_AUCTION_VOLUME == 34
    assert TICK_AUCTION_PRICE == 35
    assert TICK_AUCTION_IMBALANCE == 36
    assert TICK_REGULATORY_IMBALANCE == 61


def test_nasdaq_listing_routes_to_unavailable() -> None:
    # No NASDAQ-imbalance subscription in C13 Phase A.
    assert LISTING_TO_IMBALANCE_FEED["NASDAQ"] == "UNAVAILABLE"
    assert listing_to_imbalance_feed("NASDAQ") == "UNAVAILABLE"


def test_nyse_listing_routes_to_nyse_feed() -> None:
    assert listing_to_imbalance_feed("NYSE") == "NYSE"


def test_amex_aliases_route_to_nyse_mkt() -> None:
    assert listing_to_imbalance_feed("AMEX") == "NYSE_MKT"
    assert listing_to_imbalance_feed("NYSE MKT") == "NYSE_MKT"
    assert listing_to_imbalance_feed("NYSE_AMERICAN") == "NYSE_MKT"


def test_unknown_listing_routes_to_unknown() -> None:
    assert listing_to_imbalance_feed("BATS") == "UNKNOWN"
    assert listing_to_imbalance_feed("") == "UNKNOWN"


# ---------------------------------------------------------------------------
# classify_imbalance_side
# ---------------------------------------------------------------------------


def test_classify_imbalance_side_signs() -> None:
    assert classify_imbalance_side(100_000) == "BUY"
    assert classify_imbalance_side(-50_000) == "SELL"
    assert classify_imbalance_side(0) == "NEUTRAL"
    assert classify_imbalance_side(None) == "NEUTRAL"


def test_classify_imbalance_side_invalid_input() -> None:
    assert classify_imbalance_side("abc") == "NEUTRAL"  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# build_unavailable_snapshot
# ---------------------------------------------------------------------------


def test_unavailable_snapshot_marks_available_false() -> None:
    s = build_unavailable_snapshot(
        symbol="aapl",
        listing_exchange="NASDAQ",
        error="NO_SUBSCRIPTION",
    )
    assert s.symbol == "AAPL"
    assert s.listing_exchange == "NASDAQ"
    assert s.imbalance_feed == "UNAVAILABLE"
    assert s.available is False
    assert s.error == "NO_SUBSCRIPTION"
    assert s.auction_imbalance_side == "NEUTRAL"


# ---------------------------------------------------------------------------
# build_snapshot_from_ticks
# ---------------------------------------------------------------------------


def test_snapshot_from_ticks_buy_imbalance() -> None:
    ticks = {
        TICK_AUCTION_VOLUME: 250_000.0,
        TICK_AUCTION_PRICE: 21.34,
        TICK_AUCTION_IMBALANCE: 80_000.0,
        TICK_REGULATORY_IMBALANCE: 79_500.0,
    }
    s = build_snapshot_from_ticks(
        symbol="ZIM", listing_exchange="NYSE", ticks=ticks,
        now_utc=_dt.datetime(2026, 4, 27, 13, 28, tzinfo=_dt.UTC),
    )
    assert s.available is True
    assert s.imbalance_feed == "NYSE"
    assert s.auction_imbalance_shares == 80_000.0
    assert s.auction_imbalance_side == "BUY"
    assert s.auction_price == 21.34
    assert s.regulatory_imbalance_shares == 79_500.0
    assert s.error is None
    assert s.schema_version == IMBALANCE_SCHEMA_VERSION


def test_snapshot_from_ticks_sell_imbalance() -> None:
    ticks = {TICK_AUCTION_IMBALANCE: -120_000.0}
    s = build_snapshot_from_ticks(
        symbol="LAC", listing_exchange="NYSE", ticks=ticks,
    )
    assert s.auction_imbalance_side == "SELL"
    assert s.available is True


def test_snapshot_from_empty_ticks_marks_unavailable() -> None:
    s = build_snapshot_from_ticks(
        symbol="X", listing_exchange="NYSE", ticks={},
    )
    assert s.available is False
    assert s.auction_imbalance_side == "NEUTRAL"


def test_snapshot_to_dict_round_trip() -> None:
    s = build_unavailable_snapshot(
        symbol="X", listing_exchange="NYSE", error="HALTED",
    )
    d = s.to_dict()
    assert d["symbol"] == "X"
    assert d["error"] == "HALTED"
    assert d["schema_version"] == IMBALANCE_SCHEMA_VERSION
