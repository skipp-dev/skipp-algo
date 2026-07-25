"""Quote-source abstraction for the realtime-signals producer (Task 1.1).

Introduces the seam between ``RealtimeEngine`` and its price-feed provider so
a later task (1.3 of the Databento signal-migration plan) can inject a
Databento-backed ``QuoteSource`` without touching signal-detection logic.

``FMPQuoteSource`` is a 1:1 extraction of the pre-Task-1.1 inline fetch logic:

- ``session="regular"`` mirrors ``RealtimeEngine._fetch_realtime_quotes()``
  (the live A0/A1/A2 signal-detection hot path — chunked
  ``get_stable_batch_quotes`` calls).
- ``session in ("premarket", "postmarket")`` mirrors the three-call +
  postmarket-adaptation block inside ``RealtimeEngine._poll_extended_shadow()``
  (``get_stable_batch_quotes`` / ``get_stable_batch_aftermarket_quotes`` /
  ``get_stable_batch_aftermarket_trades``, plus ``build_postmarket_quotes``
  for postmarket).  This task implements it and covers it with a parity test,
  but does NOT rewire ``_poll_extended_shadow`` to use it — see
  ``task-1.1-report.md`` for why (that method also computes FMP-internal
  freshness/overlap shadow diagnostics from the raw per-stream rows, which is
  out of scope for a pure row-contract abstraction and is deferred to
  Phase 4 of the migration plan, same as the plan's own phase table).

Row shape: see ``docs/databento_quote_row_contract.md`` (Task 0.1).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Mirrors realtime_signals._BATCH_QUOTE_CHUNK_SIZE — kept as a private local
# constant so this module has no import-time dependency on realtime_signals.
_BATCH_QUOTE_CHUNK_SIZE = 250


class QuoteSource(Protocol):
    """Symbol list + session -> quote rows in the Task 0.1 row contract."""

    def fetch(self, symbols: list[str], session: str) -> list[dict[str, Any]]:
        ...


class FMPQuoteSource:
    """FMP-backed ``QuoteSource``.

    ``client`` may be either an already-constructed FMP client instance, or a
    zero-arg callable returning one (``lambda: engine.client``).  The
    callable form preserves the exact laziness of ``RealtimeEngine.client``
    (a property that may attempt ``FMPClient.from_env()`` and raise on each
    access until a client is successfully constructed) — that raise must
    surface *inside* the existing per-chunk try/except, unchanged from
    pre-refactor behavior, so the client is resolved on every call rather
    than cached at construction time.
    """

    def __init__(self, client: Any) -> None:
        self._client_source = client
        # Bookkeeping from the last premarket/postmarket fetch, exposed for
        # callers (e.g. extended-shadow diagnostics) that need the raw
        # per-stream rows without a second network round trip.
        self.last_regular_rows: list[dict[str, Any]] = []
        self.last_quote_rows: list[dict[str, Any]] = []
        self.last_trade_rows: list[dict[str, Any]] = []
        self.last_adapted_quotes: dict[str, dict[str, Any]] | None = None
        self.last_adapted_stats: dict[str, int] | None = None

    def _resolve_client(self) -> Any:
        source = self._client_source
        return source() if callable(source) else source

    def fetch(
        self,
        symbols: list[str],
        session: str,
        *,
        close_volume_by_symbol: dict[str, float] | None = None,
        baseline_session_date: str = "",
        now_epoch: float | None = None,
    ) -> list[dict[str, Any]]:
        if session == "regular":
            return self._fetch_regular(symbols)
        return self._fetch_extended(
            symbols,
            session,
            close_volume_by_symbol=close_volume_by_symbol or {},
            baseline_session_date=baseline_session_date,
            now_epoch=now_epoch,
        )

    # -- verbatim from RealtimeEngine._fetch_realtime_quotes() -------------
    def _fetch_regular(self, symbols: list[str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        chunk_size = _BATCH_QUOTE_CHUNK_SIZE
        for chunk_start in range(0, len(symbols), chunk_size):
            chunk = symbols[chunk_start:chunk_start + chunk_size]
            try:
                client = self._resolve_client()
                fetch_quotes = getattr(client, "get_stable_batch_quotes", None)
                raw = (fetch_quotes or client.get_batch_quotes)(chunk)
                rows.extend(raw)
            except Exception as exc:
                logger.warning(
                    "Failed to fetch realtime quotes for chunk %d–%d: %s",
                    chunk_start, chunk_start + len(chunk), exc,
                )
        return rows

    # -- verbatim from RealtimeEngine._poll_extended_shadow() --------------
    def _fetch_extended(
        self,
        symbols: list[str],
        session: str,
        *,
        close_volume_by_symbol: dict[str, float],
        baseline_session_date: str,
        now_epoch: float | None,
    ) -> list[dict[str, Any]]:
        client = self._resolve_client()
        regular = client.get_stable_batch_quotes(symbols)
        quote_rows = client.get_stable_batch_aftermarket_quotes(symbols)
        trade_rows = client.get_stable_batch_aftermarket_trades(symbols)
        resolved_now_epoch = now_epoch if now_epoch is not None else time.time()

        self.last_regular_rows = regular
        self.last_quote_rows = quote_rows
        self.last_trade_rows = trade_rows
        self.last_adapted_quotes = None
        self.last_adapted_stats = None

        if session == "postmarket":
            from open_prep.postmarket_quotes import build_postmarket_quotes

            current_session_date = datetime.now(
                ZoneInfo("America/New_York")
            ).date().isoformat()
            adapted = build_postmarket_quotes(
                reference_rows=regular,
                quote_rows=quote_rows,
                trade_rows=trade_rows,
                close_volume_by_symbol=close_volume_by_symbol,
                baseline_session_date=baseline_session_date,
                current_session_date=current_session_date,
                now_epoch=resolved_now_epoch,
            )
            self.last_adapted_quotes = adapted.quotes
            self.last_adapted_stats = adapted.stats

        return regular
