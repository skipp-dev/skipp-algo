#!/usr/bin/env python3
"""Continuously materialize browser-independent Terminal candidates.

The Streamlit UI keeps its own session feed.  This process deliberately reads
the private producer snapshot directly so ``/api/v1/news-candidates`` remains
available after deploys and when no browser session is open.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from terminal_export import rewrite_jsonl
from terminal_feed_lifecycle import is_market_hours
from terminal_feed_state import build_derived_feed_state
from terminal_internal_feed import ProducerFeedClient
from terminal_poller import ClassifiedItem

logger = logging.getLogger("terminal_candidate_mirror")


class CandidateSource(Protocol):
    def reset(self) -> None: ...

    def fetch(self) -> tuple[list[ClassifiedItem], str]: ...


@dataclass(frozen=True, slots=True)
class MirrorConfig:
    output_path: Path
    poll_interval_seconds: float = 10.0
    feed_max_age_seconds: float = 14_400.0
    live_story_ttl_seconds: float = 7_200.0
    max_items: int = 1_000


@dataclass(frozen=True, slots=True)
class MirrorResult:
    source_items: int
    retained_items: int
    active_symbols: int


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default
    value = float(raw)
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be within {minimum:g}-{maximum:g}")
    return value


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default
    value = int(raw)
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be within {minimum}-{maximum}")
    return value


def config_from_env() -> MirrorConfig:
    return MirrorConfig(
        output_path=Path(
            os.getenv("TERMINAL_CANDIDATE_JSONL_PATH", "artifacts/terminal_candidates.jsonl")
        ),
        poll_interval_seconds=_bounded_float(
            "TERMINAL_CANDIDATE_POLL_INTERVAL_SECONDS", 10.0, 5.0, 300.0
        ),
        feed_max_age_seconds=_bounded_float(
            "TERMINAL_CANDIDATE_MAX_AGE_SECONDS", 14_400.0, 60.0, 86_400.0
        ),
        live_story_ttl_seconds=_bounded_float(
            "TERMINAL_LIVE_STORY_TTL_S", 7_200.0, 60.0, 86_400.0
        ),
        max_items=_bounded_int("TERMINAL_CANDIDATE_SOURCE_LIMIT", 1_000, 1, 1_000),
    )


def source_from_env() -> ProducerFeedClient:
    return ProducerFeedClient(
        os.getenv("TERMINAL_PRODUCER_FEED_URL", ""),
        os.getenv("TERMINAL_PRODUCER_FEED_TOKEN", ""),
        timeout_s=_bounded_float("TERMINAL_PRODUCER_FEED_TIMEOUT_S", 5.0, 0.5, 30.0),
        max_age_s=_bounded_float("TERMINAL_PRODUCER_FEED_MAX_AGE_S", 300.0, 30.0, 3_600.0),
    )


def mirror_once(
    source: CandidateSource,
    config: MirrorConfig,
    *,
    now: float | None = None,
    market_hours: bool | None = None,
) -> MirrorResult:
    """Fetch the complete current snapshot and atomically replace the mirror."""
    current_time = float(now if now is not None else time.time())
    source.reset()
    items, _cursor = source.fetch()
    rows = [item.to_dict() for item in items]
    state = build_derived_feed_state(
        rows,
        cfg=config,
        now=current_time,
        market_hours=is_market_hours() if market_hours is None else market_hours,
    )
    rewrite_jsonl(str(config.output_path), state.feed)
    active_symbols = {
        str(row.get("ticker") or "").strip().upper()
        for row in state.feed
        if row.get("attention_active")
    }
    active_symbols.discard("")
    return MirrorResult(
        source_items=len(rows),
        retained_items=len(state.feed),
        active_symbols=len(active_symbols),
    )


def run_forever(source: CandidateSource, config: MirrorConfig) -> None:
    stop_event = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    while not stop_event.is_set():
        started = time.monotonic()
        try:
            result = mirror_once(source, config)
            logger.info(
                "candidate mirror refreshed source_items=%d retained_items=%d active_symbols=%d",
                result.source_items,
                result.retained_items,
                result.active_symbols,
            )
        except Exception as exc:
            logger.warning("candidate mirror refresh failed (%s)", type(exc).__name__)
        elapsed = time.monotonic() - started
        stop_event.wait(max(0.0, config.poll_interval_seconds - elapsed))


def main() -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = config_from_env()
    source = source_from_env()
    run_forever(source, config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
