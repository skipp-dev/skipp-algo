"""Tests for scripts.collect_opening_imbalances (C13/T8.2)."""

from __future__ import annotations

import datetime as _dt
from typing import Any

from scripts.collect_opening_imbalances import collect_imbalances
from scripts.imbalance_data import (
    ImbalanceSnapshot,
    build_unavailable_snapshot,
)


def _stub_fetch_buy(
    *, symbol: str, listing_exchange: str, poll_seconds: float,
    now_utc: _dt.datetime | None,
) -> ImbalanceSnapshot:
    """Stub fetch — always returns a BUY snapshot for NYSE/AMEX rows."""
    from scripts.imbalance_data import (
        TICK_AUCTION_IMBALANCE,
        build_snapshot_from_ticks,
    )

    return build_snapshot_from_ticks(
        symbol=symbol,
        listing_exchange=listing_exchange,
        ticks={TICK_AUCTION_IMBALANCE: 50_000.0},
        now_utc=now_utc,
    )


def _stub_fetch_raises(
    *, symbol: str, listing_exchange: str, poll_seconds: float,
    now_utc: _dt.datetime | None,
) -> ImbalanceSnapshot:
    raise RuntimeError("simulated TWS error")


# ---------------------------------------------------------------------------
# NASDAQ rows skip fetch entirely
# ---------------------------------------------------------------------------


def test_nasdaq_rows_emit_unavailable_without_fetching() -> None:
    calls: list[str] = []

    def stub(**kw: Any) -> ImbalanceSnapshot:
        calls.append(kw["symbol"])
        return build_unavailable_snapshot(
            symbol=kw["symbol"],
            listing_exchange=kw["listing_exchange"],
            error="should_not_be_called",
        )

    rows = [("MARA", "NASDAQ"), ("OPEN", "NASDAQ")]
    snapshots, errors = collect_imbalances(rows, fetch_fn=stub)

    assert calls == []  # NASDAQ never goes through fetch
    assert errors == []
    assert len(snapshots) == 2
    for s in snapshots:
        assert s.available is False
        assert s.error == "NO_SUBSCRIPTION"
        assert s.imbalance_feed == "UNAVAILABLE"


# ---------------------------------------------------------------------------
# NYSE / AMEX rows go through fetch
# ---------------------------------------------------------------------------


def test_nyse_and_amex_rows_get_fetched() -> None:
    rows = [("ZIM", "NYSE"), ("KULR", "AMEX")]
    snapshots, errors = collect_imbalances(rows, fetch_fn=_stub_fetch_buy)
    assert errors == []
    assert len(snapshots) == 2
    assert snapshots[0].symbol == "ZIM"
    assert snapshots[0].imbalance_feed == "NYSE"
    assert snapshots[0].auction_imbalance_side == "BUY"
    assert snapshots[1].imbalance_feed == "NYSE_MKT"
    assert snapshots[1].auction_imbalance_side == "BUY"


# ---------------------------------------------------------------------------
# Fetch exceptions degrade to UNAVAILABLE without aborting the run
# ---------------------------------------------------------------------------


def test_fetch_exception_is_caught_per_row() -> None:
    rows = [("ZIM", "NYSE"), ("LAC", "NYSE")]
    snapshots, errors = collect_imbalances(rows, fetch_fn=_stub_fetch_raises)
    assert len(errors) == 2
    assert all("simulated TWS error" in e for e in errors)
    assert len(snapshots) == 2
    for s in snapshots:
        assert s.available is False
        assert s.error and s.error.startswith("FETCH_RAISED")


# ---------------------------------------------------------------------------
# Mixed rows: each row routed correctly
# ---------------------------------------------------------------------------


def test_mixed_rows_routing() -> None:
    rows = [
        ("ZIM", "NYSE"),       # → NYSE feed (fetch)
        ("MARA", "NASDAQ"),    # → UNAVAILABLE (skip fetch)
        ("KULR", "AMEX"),      # → NYSE_MKT (fetch)
    ]
    snapshots, errors = collect_imbalances(rows, fetch_fn=_stub_fetch_buy)
    assert errors == []
    feeds = [s.imbalance_feed for s in snapshots]
    assert feeds == ["NYSE", "UNAVAILABLE", "NYSE_MKT"]
    avail = [s.available for s in snapshots]
    assert avail == [True, False, True]
