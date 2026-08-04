"""Databento Live connection loop for the OPRA shadow daemon."""

from __future__ import annotations

import logging
import random
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import databento_usage

from .config import Config, read_hotlist_file
from .definitions import bootstrap_definitions
from .state import OpraShadowState, _mapping

logger = logging.getLogger(__name__)


def _is_definition(record: Any) -> bool:
    name = type(record).__name__.lower()
    row = _mapping(record)
    return "definition" in name or (
        "instrument_class" in row and ("underlying" in row or "asset" in row)
    )


def route_record(state: OpraShadowState, record: Any) -> str:
    """Dispatch one live record to its path; returns the route taken.

    Order matters: definitions first, then quotes (tcbbo, BBO-bearing), and
    everything else is a trades-schema record that gets COUNTED. Extracted
    from the live loop so the routing is unit-testable without a Live client.
    """
    if _is_definition(record):
        row = _mapping(record)
        state.add_definition(row, ts_ns=int(row.get("ts_recv") or 0))
        return "definition"
    if _is_quote(record):
        state.update_quote(record)
        return "quote"
    state.add_trade(record)
    return "trade"


def _is_quote(record: Any) -> bool:
    """tcbbo (CMBP1) records carry the BBO; trades (TradeMsg) records do not.

    Since #4368 the tcbbo stream is the quote source only — counting happens
    on the trades stream, whose ``sequence`` field distinguishes genuine
    identical child fills that tcbbo cannot (it has no sequence field at all).
    """
    if isinstance(record, Mapping):
        return "bid_px_00" in record or "ask_px_00" in record
    return hasattr(record, "bid_px_00") or hasattr(record, "ask_px_00")


def _parent_symbols(hotlist: tuple[str, ...]) -> list[str]:
    return [f"{ticker}.OPT" for ticker in hotlist]


def run(config: Config, state: OpraShadowState, stop: threading.Event) -> None:
    """Run until stopped; reconnect with bounded exponential backoff and jitter."""
    if not config.enabled:
        logger.info("OPRA live daemon is off; no provider connection opened")
        return
    from databento_client import _import_databento
    from databento_provider import DabentoProvider

    db = _import_databento()
    symbols = _parent_symbols(tuple(sorted(state.hotlist)))
    try:
        for definition in bootstrap_definitions(
            DabentoProvider(config.api_key),
            symbols=symbols,
            instant=datetime.now(UTC),
        ):
            state.add_definition(definition)
    except Exception:
        logger.warning("OPRA definition bootstrap failed; live updates remain active", exc_info=True)

    failures = 0
    while not stop.is_set():
        symbols = _parent_symbols(tuple(sorted(state.hotlist)))
        client = None
        pending_records = 0
        try:
            client = db.Live(key=config.api_key)
            client.subscribe(
                dataset=config.dataset,
                schema="definition",
                symbols=symbols,
                stype_in="parent",
            )
            client.subscribe(
                dataset=config.dataset,
                schema=config.schema,
                symbols=symbols,
                stype_in="parent",
            )
            # Count source (#4368): trades carries the sequence numbers that
            # distinguish genuine identical child fills; tcbbo above stays
            # subscribed purely as the BBO-at-trade source. Measured volume:
            # trades == tcbbo record-for-record, so this doubles the trade
            # stream — NOT the 91x a cbbo-1s quote subscription would cost.
            client.subscribe(
                dataset=config.dataset,
                schema="trades",
                symbols=symbols,
                stype_in="parent",
            )
            databento_usage.record(
                dataset=config.dataset,
                schema=config.schema,
                mode="live",
                consumer="opra-shadow",
                subscriptions=3,
                symbols_requested=len(symbols),
            )
            failures = 0
            for record in client:
                if stop.is_set():
                    break
                if route_record(state, record) == "definition":
                    continue
                pending_records += 1
                if (
                    pending_records % 1000 == 0
                    and config.hotlist_path is not None
                    and config.hotlist_path.exists()
                ):
                    updated = read_hotlist_file(config.hotlist_path)
                    if updated and frozenset(updated) != state.hotlist:
                        state.update_hotlist(updated)
                        logger.info("OPRA hotlist changed; reconnecting subscriptions")
                        break
                if pending_records >= 1000:
                    databento_usage.record(
                        dataset=config.dataset,
                        schema=config.schema,
                        mode="live",
                        consumer="opra-shadow",
                        records=pending_records,
                    )
                    pending_records = 0
        except Exception:
            failures += 1
            databento_usage.record(
                dataset=config.dataset,
                schema=config.schema,
                mode="live",
                consumer="opra-shadow",
                errors=1,
                reconnects=1,
            )
            logger.warning("OPRA live connection failed", exc_info=True)
        finally:
            if pending_records:
                databento_usage.record(
                    dataset=config.dataset,
                    schema=config.schema,
                    mode="live",
                    consumer="opra-shadow",
                    records=pending_records,
                )
            if client is not None:
                try:
                    client.stop()
                except Exception:
                    logger.debug("OPRA client stop failed", exc_info=True)
        if not stop.is_set():
            delay = min(60.0, 2.0 ** min(failures, 5)) + random.uniform(0.0, 1.0)
            stop.wait(delay)


def start(config: Config, state: OpraShadowState, stop: threading.Event) -> threading.Thread:
    thread = threading.Thread(
        target=run,
        args=(config, state, stop),
        name="opra-live-feed",
        daemon=True,
    )
    thread.start()
    return thread
