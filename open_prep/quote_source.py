"""Quote-source abstraction for the realtime-signals producer (Task 1.1).

Defines the seam between ``RealtimeEngine`` and its price-feed provider.
The engine selects Databento by default and retains ``FMPQuoteSource`` as
its explicit rollback and startup fallback.

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
import os
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from .databento_quote_feed import DatabentoQuoteFeed
    from .quote_reference import QuoteReference

logger = logging.getLogger(__name__)

# Mirrors realtime_signals._BATCH_QUOTE_CHUNK_SIZE — kept as a private local
# constant so this module has no import-time dependency on realtime_signals.
_BATCH_QUOTE_CHUNK_SIZE = 250

# Bounded-age staleness guard for DatabentoQuoteSource (final-review Finding
# 3). Env-overridable, kept local (no import-time dependency on
# realtime_signals — same rationale as _BATCH_QUOTE_CHUNK_SIZE above).
_MAX_BAR_AGE_ENV_VAR = "DATABENTO_QUOTE_MAX_BAR_AGE_SECS"
# 90s: comfortably above the producer's default 20s poll interval (tolerates
# a few missed 1s-bars/poll cycles without flapping) yet well below the
# producer's DATA_STALL_SECONDS=300 data_stale threshold (>3x margin), so a
# dead feed's symbols age out and fetch() goes empty long before the
# producer-level gauge would even notice — see class docstring.
_DEFAULT_MAX_BAR_AGE_SECS = 90.0


def _resolve_max_bar_age_secs(explicit: float | None) -> float:
    if explicit is not None:
        return float(explicit)
    raw = os.environ.get(_MAX_BAR_AGE_ENV_VAR)
    if raw:
        try:
            parsed = float(raw)
        except ValueError:
            parsed = None
        # Must be a positive, finite number: a zero/negative override would age
        # EVERY bar out on arrival (fail-closing the whole feed to empty), and a
        # NaN/inf would disable the staleness guard entirely (frozen prices
        # served forever). Reject both -- fall back to the safe default.
        if parsed is not None and parsed > 0 and parsed != float("inf"):
            return parsed
        logger.warning(
            "Invalid %s=%r (must be a positive finite number) -- falling back to default %.1fs",
            _MAX_BAR_AGE_ENV_VAR, raw, _DEFAULT_MAX_BAR_AGE_SECS,
        )
    return _DEFAULT_MAX_BAR_AGE_SECS


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


class DatabentoQuoteSource:
    """Databento-backed ``QuoteSource`` (Task 1.3 of the signal-migration
    plan).

    Combines a ``DatabentoQuoteFeed``'s thread-safe live-bar cache (Task 1.2)
    with a ``QuoteReference``'s daily previous-close/ADV lookup (Task 0.2)
    into rows conforming to the Task 0.1 contract
    (``docs/databento_quote_row_contract.md``): ``price``/``lastPrice`` =
    latest bar close, ``volume`` = cumulative regular-session volume,
    ``previousClose``/``avgVolume`` = the reference row, ``timestamp``/
    ``received_at`` = the bar's ``ts_event``/``ts_recv``, ``dayHigh``/
    ``dayLow`` = the cache's session high/low.

    Unlike ``FMPQuoteSource`` (whose FMP batch-quote endpoint never returns
    ``avgVolume`` — see the Task 0.1 contract doc), this source CAN and DOES
    populate ``avgVolume`` directly from the reference, so it is always
    present in the emitted row rather than depending on a watchlist
    fallback.

    Fail-closed: a symbol with no cached bar yet, with a bar older than
    ``max_bar_age_secs`` (final-review Finding 3 — see below), or with no
    reference entry, is OMITTED from the result entirely — never emitted
    with a fabricated or stale price, mirroring how the FMP path drops
    symbols FMP didn't return a quote for.

    Bounded-age staleness guard (Finding 3): the feed's background reconnect
    loop now re-arms itself after its circuit breaker trips (a supervisor
    cooldown, ``DatabentoQuoteFeed._run_feed_loop``), but during that cooldown
    — or if it never recovers — nothing purges the cache, so ``latest_bar``/
    ``cumulative_volume`` would otherwise keep returning the LAST CACHED entry,
    and this source would keep emitting a frozen price with no signal reaching
    the producer.
    ``fetch`` instead treats a bar older than ``max_bar_age_secs`` (measured
    against ``bar.ts_recv``, the feed's capture time) exactly like "no bar":
    omit the symbol. Once every symbol has aged out, ``fetch`` returns an
    empty list, which is what stops ``RealtimeEngine._last_data_epoch`` from
    advancing (it is stamped only on a non-empty fetch —
    ``open_prep/realtime_signals.py``) and lets the existing
    ``signals_producer_data_stale`` gauge fire after ``DATA_STALL_SECONDS``
    (300s) — turning a silently-frozen feed into an observable, fail-closed
    one. This source-side gate is complementary to (not a replacement for) the
    feed's supervisor restart: the supervisor brings the feed back, the gate
    keeps stale prices out of signals while it is down.

    ``RealtimeEngine`` wires this source as its default. The adapter remains
    standalone from signal math: it only satisfies the shared quote-row
    contract behind the ``RT_QUOTE_SOURCE`` seam.
    """

    def __init__(
        self,
        feed: DatabentoQuoteFeed,
        reference: QuoteReference,
        *,
        source_label: str = "databento",
        max_bar_age_secs: float | None = None,
    ) -> None:
        self._feed = feed
        self._reference = reference
        self._source_label = source_label
        # None -> DATABENTO_QUOTE_MAX_BAR_AGE_SECS env override, else the
        # built-in default (see _resolve_max_bar_age_secs above).
        self._max_bar_age_secs = _resolve_max_bar_age_secs(max_bar_age_secs)

    def reload_reference(self) -> bool:
        """Swap in a freshly-loaded ``QuoteReference`` so a new session's
        previous_close/ADV (rewritten out-of-band by
        ``python -m open_prep.quote_reference``) is served without a producer
        restart. Otherwise the source keeps yesterday's previous_close for the
        life of the process, skewing ``changesPercentage`` after the daily
        rebuild.

        Fail-soft: a missing/corrupt artifact (or a directly-constructed
        reference with no source path) leaves the current reference in place —
        never cleared to empty, which would fail-close every symbol. Returns
        True only when a reload was actually applied.
        """
        try:
            self._reference = self._reference.reload()
            return True
        except (OSError, ValueError):
            logger.warning(
                "QuoteReference reload failed -- keeping the current reference",
                exc_info=True,
            )
            return False

    def fetch(
        self,
        symbols: list[str],
        session: str,
        *,
        now: float | None = None,
    ) -> list[dict[str, Any]]:
        """Build contract-conformant quote rows for ``symbols``.

        ``session`` is accepted for ``QuoteSource`` protocol parity with
        ``FMPQuoteSource``; the feed itself only ever caches regular-session
        bars (Task 1.2's RTH gate), so rows are built identically regardless
        of the value passed here.

        ``now`` is an injectable clock (defaults to ``time.time()``) so the
        bounded-age staleness guard (class docstring) is deterministic in
        tests without real wall-clock sleeps.
        """
        resolved_now = now if now is not None else time.time()
        rows: list[dict[str, Any]] = []
        for symbol_raw in symbols:
            symbol = str(symbol_raw).strip().upper()
            if not symbol:
                continue

            bar = self._feed.latest_bar(symbol)
            if bar is None:
                continue  # fail-closed: no bar yet -- omit, never fabricate

            if resolved_now - bar.ts_recv > self._max_bar_age_secs:
                continue  # fail-closed: bar too old -- omit, never emit a frozen price

            reference_row = self._reference.get(symbol)
            if reference_row is None:
                continue  # fail-closed: no daily reference -- omit

            day_high, day_low = self._feed.session_high_low(symbol)
            if day_high is None or day_low is None:
                continue  # fail-closed: incomplete cache entry -- omit

            price = bar.close
            prev_close = reference_row.previous_close
            change_pct = ((price - prev_close) / prev_close) * 100 if prev_close else 0.0

            rows.append({
                "symbol": symbol,
                "price": price,
                "lastPrice": price,
                "previousClose": prev_close,
                "volume": self._feed.cumulative_volume(symbol),
                # Present unlike FMP's batch-quote row (see class docstring)
                # -- sourced straight from the daily reference, not a
                # watchlist fallback.
                "avgVolume": reference_row.average_daily_volume,
                "timestamp": bar.ts_event,
                "received_at": bar.ts_recv,
                "dayHigh": day_high,
                "dayLow": day_low,
                "changesPercentage": change_pct,
                "source": self._source_label,
            })
        return rows
