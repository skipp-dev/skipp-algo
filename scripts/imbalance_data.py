"""C13/T8.1 — IBKR opening-auction imbalance wrapper.

The per-symbol entry point (``fetch_opening_imbalance``) performs a
shallow subscribe-then-sleep against the IBKR
``reqMktData(genericTickList="225")`` stream and persists the
last-known auction snapshot to JSONL. The 09:28–09:30 ET window is
enforced by the cron caller (``scripts.collect_opening_imbalances``
schedules the run inside that window); ``DEFAULT_POLL_START_ET`` and
``DEFAULT_POLL_END_ET`` below are exported as the canonical window
defaults for that caller and any future scheduler that needs them.

Tick types per IBKR docs (``IBApi.EWrapper.tickPrice`` /
``IBApi.EWrapper.tickSize``):

* Tick 34 — Auction Volume (size)
* Tick 35 — Auction Price (price)
* Tick 36 — Auction Imbalance (size; signed convention: positive = buy
  imbalance, negative = sell imbalance, 0 = neutral)
* Tick 61 — Regulatory Imbalance (size)

Reference: https://interactivebrokers.github.io/tws-api/tick_types.html

The wrapper is **passive** in C13 Phase A — it only writes a JSONL
artefact. The Phase-B pre-trade filter that consumes it is documented
as ``T8.5`` in the C13 sprint plan.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import logging
import time
from collections.abc import Mapping
from typing import Any, Literal

LOGGER = logging.getLogger(__name__)

# Producer-side schema; bump on REMOVE-only changes (additive ok).
IMBALANCE_SCHEMA_VERSION = "1.0.0"

# Generic tick id list to enable auction ticks 34/35/36/61.
GENERIC_TICK_AUCTION = "225"

# Tick-type IDs we care about (mirrors TWS API constants).
TICK_AUCTION_VOLUME = 34
TICK_AUCTION_PRICE = 35
TICK_AUCTION_IMBALANCE = 36
TICK_REGULATORY_IMBALANCE = 61

# Default polling window (Eastern Time) — 09:28:00 → 09:29:55 inclusive
# so the last snapshot is committed before the regular open at 09:30.
DEFAULT_POLL_START_ET = _dt.time(9, 28, 0)
DEFAULT_POLL_END_ET = _dt.time(9, 29, 55)

# Listing-exchange → IBKR-imbalance-feed routing. NASDAQ has no
# subscription in the C13 Phase-A budget; mark explicitly so the
# downstream consumer can attribute coverage gaps correctly.
LISTING_TO_IMBALANCE_FEED: dict[str, str] = {
    "NYSE": "NYSE",
    "NASDAQ": "UNAVAILABLE",
    "AMEX": "NYSE_MKT",
    "NYSE_MKT": "NYSE_MKT",
    "NYSE_AMERICAN": "NYSE_MKT",
    "ARCA": "NYSE_ARCA",
}

ImbalanceSide = Literal["BUY", "SELL", "NEUTRAL"]


@dataclasses.dataclass(frozen=True)
class ImbalanceSnapshot:
    """Last-known auction state for one symbol on one trade day."""

    symbol: str
    listing_exchange: str
    imbalance_feed: str
    ts_utc: str
    auction_volume: float | None
    auction_price: float | None
    auction_imbalance_shares: float | None
    auction_imbalance_side: ImbalanceSide
    regulatory_imbalance_shares: float | None
    available: bool
    error: str | None = None
    schema_version: str = IMBALANCE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def classify_imbalance_side(shares: float | None) -> ImbalanceSide:
    """Return ``BUY`` / ``SELL`` / ``NEUTRAL`` from a signed share count.

    The IBKR convention is ``positive = buy``, ``negative = sell``,
    ``0 / None = neutral``.
    """
    if shares is None:
        return "NEUTRAL"
    try:
        v = float(shares)
    except (TypeError, ValueError):
        return "NEUTRAL"
    if v > 0:
        return "BUY"
    if v < 0:
        return "SELL"
    return "NEUTRAL"


def listing_to_imbalance_feed(listing_exchange: str) -> str:
    """Return the IBKR imbalance-feed name for a listing exchange.

    Unknown listings return ``"UNKNOWN"`` so downstream coverage
    metrics can attribute them; the wrapper still polls (a Smart-routed
    contract often pulls the right feed implicitly).
    """
    norm = str(listing_exchange or "").strip().upper().replace(" ", "_")
    return LISTING_TO_IMBALANCE_FEED.get(norm, "UNKNOWN")


def build_unavailable_snapshot(
    *,
    symbol: str,
    listing_exchange: str,
    error: str,
    now_utc: _dt.datetime | None = None,
) -> ImbalanceSnapshot:
    """Helper for a "no-data" snapshot (cron continues without blocking)."""
    ts = (now_utc or _dt.datetime.now(tz=_dt.UTC)).isoformat()
    return ImbalanceSnapshot(
        symbol=str(symbol).upper(),
        listing_exchange=str(listing_exchange or "").upper(),
        imbalance_feed=listing_to_imbalance_feed(listing_exchange),
        ts_utc=ts,
        auction_volume=None,
        auction_price=None,
        auction_imbalance_shares=None,
        auction_imbalance_side="NEUTRAL",
        regulatory_imbalance_shares=None,
        available=False,
        error=error,
    )


def build_snapshot_from_ticks(
    *,
    symbol: str,
    listing_exchange: str,
    ticks: Mapping[int, float | None],
    now_utc: _dt.datetime | None = None,
) -> ImbalanceSnapshot:
    """Materialise a snapshot from a captured tick-id → value map.

    ``ticks`` is the raw map kept by the EWrapper subclass during the
    polling window. Missing ticks become ``None``. The signed share
    count from tick 36 drives the ``auction_imbalance_side`` field.
    """
    auction_volume = ticks.get(TICK_AUCTION_VOLUME)
    auction_price = ticks.get(TICK_AUCTION_PRICE)
    auction_imbalance = ticks.get(TICK_AUCTION_IMBALANCE)
    regulatory_imbalance = ticks.get(TICK_REGULATORY_IMBALANCE)

    side = classify_imbalance_side(auction_imbalance)
    available = (
        auction_imbalance is not None
        or auction_price is not None
        or auction_volume is not None
        or regulatory_imbalance is not None
    )

    ts = (now_utc or _dt.datetime.now(tz=_dt.UTC)).isoformat()
    return ImbalanceSnapshot(
        symbol=str(symbol).upper(),
        listing_exchange=str(listing_exchange or "").upper(),
        imbalance_feed=listing_to_imbalance_feed(listing_exchange),
        ts_utc=ts,
        auction_volume=(
            None if auction_volume is None else float(auction_volume)
        ),
        auction_price=(
            None if auction_price is None else float(auction_price)
        ),
        auction_imbalance_shares=(
            None if auction_imbalance is None else float(auction_imbalance)
        ),
        auction_imbalance_side=side,
        regulatory_imbalance_shares=(
            None
            if regulatory_imbalance is None
            else float(regulatory_imbalance)
        ),
        available=available,
        error=None if available else "NO_AUCTION_DATA",
    )


def _import_ib_async() -> Any:
    try:
        from ib_async import IB, Stock
    except ImportError as exc:  # pragma: no cover — exercised manually
        raise RuntimeError(
            "ib_async is not installed. Install with "
            "`pip install -r requirements.txt`."
        ) from exc
    return IB, Stock


def fetch_opening_imbalance(
    *,
    symbol: str,
    listing_exchange: str,
    ib_client: Any | None = None,
    contract_factory: Any | None = None,
    poll_seconds: float = 5.0,
    sleep_fn: Any = time.sleep,
    now_utc: _dt.datetime | None = None,
) -> ImbalanceSnapshot:
    """Poll the auction ticks for one symbol and persist a snapshot.

    Pure-stdlib path: ``ib_client`` is passed as a stub in unit tests.
    The function does not connect/disconnect; callers manage the
    session.

    The polling loop is shallow: we subscribe via
    ``ib_client.reqMktData(generic_tick_list="225")``, sleep for
    ``poll_seconds`` to let TWS deliver a few ticks, then read the
    last-known values from either:

    * ``ib_client.last_auction_ticks`` (a dict that a custom EWrapper
      subclass populates — used by unit-test stubs and bespoke wrappers), or
    * the ib_async ``Ticker`` object returned by ``reqMktData`` (the
      vanilla path the CLI uses; ib_async exposes auction ticks as the
      ``auctionVolume`` / ``auctionPrice`` / ``auctionImbalance`` /
      ``regulatoryImbalance`` attributes).

    The two sources are merged: ``last_auction_ticks`` wins when both
    are populated so a custom wrapper can override the vanilla feed.
    """
    # Default ``contract_factory`` to ``ib_async.Stock`` regardless of
    # whether the caller injected ``ib_client``. Without this, callers
    # that pass a connected ``IB()`` (e.g. the cron CLI) would hit the
    # ``CONTRACT_FACTORY_MISSING`` early-out below and the live path
    # would never build a contract.
    if contract_factory is None:
        try:
            _, Stock = _import_ib_async()
            contract_factory = Stock
        except RuntimeError:
            # ib_async not installed; only the test path (which
            # supplies an explicit factory) can succeed from here.
            pass

    if ib_client is None:
        IB, Stock = _import_ib_async()
        ib_client = IB()
        contract_factory = contract_factory or Stock

    contract = contract_factory(symbol, "SMART", "USD") if contract_factory else None
    if contract is None:  # pragma: no cover — only when factory unset live
        return build_unavailable_snapshot(
            symbol=symbol,
            listing_exchange=listing_exchange,
            error="CONTRACT_FACTORY_MISSING",
            now_utc=now_utc,
        )

    try:
        ticker = ib_client.reqMktData(
            contract,
            genericTickList=GENERIC_TICK_AUCTION,
            snapshot=False,
            regulatorySnapshot=False,
            mktDataOptions=[],
        )
    except Exception as exc:  # pragma: no cover — exercised live
        return build_unavailable_snapshot(
            symbol=symbol,
            listing_exchange=listing_exchange,
            error=f"REQ_MKT_DATA_FAILED: {exc}",
            now_utc=now_utc,
        )

    try:
        sleep_fn(max(0.0, float(poll_seconds)))
        # Source 1: a custom EWrapper subclass populates
        # ``last_auction_ticks`` via its own tickPrice/tickSize
        # callbacks (this is the unit-test stub path).
        ticks = getattr(ib_client, "last_auction_ticks", {}) or {}
        if not isinstance(ticks, Mapping):
            ticks = {}
        # Filter to only the auction ticks we care about so a
        # misbehaving client can't smuggle unrelated data into the
        # snapshot.
        relevant = {
            k: ticks.get(k)
            for k in (
                TICK_AUCTION_VOLUME,
                TICK_AUCTION_PRICE,
                TICK_AUCTION_IMBALANCE,
                TICK_REGULATORY_IMBALANCE,
            )
            if k in ticks
        }
        # Source 2: vanilla ib_async. The Ticker object returned by
        # reqMktData exposes the auction ticks as named attributes
        # once TWS streams them. We only fill in keys missing from
        # ``relevant`` so a bespoke wrapper retains precedence.
        if ticker is not None:
            ticker_map = {
                TICK_AUCTION_VOLUME: getattr(ticker, "auctionVolume", None),
                TICK_AUCTION_PRICE: getattr(ticker, "auctionPrice", None),
                TICK_AUCTION_IMBALANCE: getattr(ticker, "auctionImbalance", None),
                TICK_REGULATORY_IMBALANCE: getattr(
                    ticker, "regulatoryImbalance", None
                ),
            }
            for k, v in ticker_map.items():
                if k not in relevant and v is not None:
                    relevant[k] = v
        snapshot = build_snapshot_from_ticks(
            symbol=symbol,
            listing_exchange=listing_exchange,
            ticks=relevant,
            now_utc=now_utc,
        )
    finally:
        try:
            ib_client.cancelMktData(contract)
        except Exception:  # pragma: no cover — exercised live
            LOGGER.warning("cancelMktData failed for %s", symbol)

    return snapshot
