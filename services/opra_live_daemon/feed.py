"""Databento Live connection loop for the OPRA shadow daemon."""

from __future__ import annotations

import logging
import random
import threading
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
            databento_usage.record(
                dataset=config.dataset,
                schema=config.schema,
                mode="live",
                consumer="opra-shadow",
                subscriptions=2,
                symbols_requested=len(symbols),
            )
            failures = 0
            for record in client:
                if stop.is_set():
                    break
                if _is_definition(record):
                    row = _mapping(record)
                    state.add_definition(row, ts_ns=int(row.get("ts_recv") or 0))
                    continue
                state.add_trade(record)
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
