"""Benzinga news ingestion adapters: REST delta + WebSocket streaming.

REST:
    Polls ``/api/v2/news`` with ``updatedSince`` for delta-only fetches.
    Synchronous (httpx.Client) — called from ``poll_once()``.

    Additional news endpoints:
    - ``/api/v2/news/top`` — curated top news stories
    - ``/api/v2/news/channels`` — list available channel IDs/names
    - ``/api/v2/newsquantified`` — quantified news with price context

WebSocket:
    Connects to Benzinga's news stream WS endpoint.  Runs in a **daemon
    thread** with its own asyncio event loop and pushes ``NewsItem``
    objects into a thread-safe ``queue.Queue`` that ``poll_once()``
    drains on each Streamlit refresh.

Both adapters are **optional** — they are only instantiated when
``BENZINGA_API_KEY`` is set and the corresponding feature flag is
enabled in ``Config``.
"""

from __future__ import annotations

import asyncio
import collections
import concurrent.futures
import json
import logging
import queue
import re
import threading
import time
from typing import Any

import httpx

from newsstack_fmp._bz_http import _request_with_retry, _sanitize_url, log_fetch_warning

from .common_types import NewsItem
from .normalize import normalize_benzinga_rest, normalize_benzinga_ws

logger = logging.getLogger(__name__)


# =====================================================================
# 1) REST delta adapter (synchronous)
# =====================================================================

BENZINGA_REST_BASE = "https://api.benzinga.com/api/v2/news"


def _coerce_benzinga_date_param(value: str | None) -> str | None:
    if not value:
        return None
    stripped = str(value).strip()
    if not stripped:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", stripped):
        return stripped
    match = re.match(r"^(\d{4}-\d{2}-\d{2})[T\s]", stripped)
    if match:
        return match.group(1)
    return stripped


def _build_news_params(
    *,
    api_key: str,
    updated_since: str | None,
    page_size: int,
    channels: str | None,
    topics: str | None,
    page: int,
    date_from: str | None,
    date_to: str | None,
    publish_since: str | None,
    tickers: str | None,
    display_output: str | None,
    ticker_param_name: str = "tickers",
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "token": api_key,
        "pageSize": page_size,
        "page": page,
    }
    if updated_since:
        params["updatedSince"] = updated_since
    if date_from:
        params["dateFrom"] = date_from
    if date_to:
        params["dateTo"] = date_to
    if publish_since:
        params["publishSince"] = publish_since
    if tickers:
        params[ticker_param_name] = tickers
    if channels:
        params["channels"] = channels
    if topics:
        params["topics"] = topics
    if display_output:
        params["displayOutput"] = display_output
    return params


def _historical_news_param_variants(base_params: dict[str, Any]) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = [base_params]
    normalized_dates = dict(base_params)
    changed_dates = False
    for key in ("dateFrom", "dateTo", "publishSince"):
        coerced = _coerce_benzinga_date_param(normalized_dates.get(key))
        if coerced and coerced != normalized_dates.get(key):
            normalized_dates[key] = coerced
            changed_dates = True
    if changed_dates:
        variants.append(normalized_dates)

    if base_params.get("tickers"):
        symbol_variants_source = variants.copy()
        for candidate in symbol_variants_source:
            rewritten = dict(candidate)
            rewritten["symbols"] = rewritten.pop("tickers")
            if rewritten not in variants:
                variants.append(rewritten)
    return variants


class BenzingaRestAdapter:
    """Synchronous Benzinga REST news adapter using ``updatedSince``."""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise RuntimeError("BENZINGA_API_KEY missing")
        self.api_key = api_key
        self.client = httpx.Client(
            timeout=10.0,
            headers={"Accept": "application/json"},
        )

    def fetch_news(
        self,
        updated_since: str | None = None,
        page_size: int = 100,
        channels: str | None = None,
        topics: str | None = None,
        *,
        page: int = 0,
        date_from: str | None = None,
        date_to: str | None = None,
        publish_since: str | None = None,
        tickers: str | None = None,
        display_output: str | None = None,
    ) -> list[NewsItem]:
        """Fetch latest news, optionally only items updated since *updated_since*.

        Parameters
        ----------
        updated_since : str, optional
            ``updatedSince`` value (epoch or ISO) for delta-only fetches.
        page_size : int
            Number of items per API call.
        channels : str, optional
            Comma-separated channel names to filter by (e.g.
            ``"Analyst Ratings,SEC,Markets"``).
        topics : str, optional
            Comma-separated topic names to filter by.
        """
        params = _build_news_params(
            api_key=self.api_key,
            updated_since=updated_since,
            page_size=page_size,
            channels=channels,
            topics=topics,
            page=page,
            date_from=date_from,
            date_to=date_to,
            publish_since=publish_since,
            tickers=tickers,
            display_output=display_output,
        )
        request_variants = _historical_news_param_variants(params)

        _RETRYABLE = {429, 500, 502, 503, 504}
        _MAX_ATTEMPTS = 3
        last_exc: Exception | None = None
        r: httpx.Response | None = None
        for variant_index, request_params in enumerate(request_variants):
            last_variant = variant_index == len(request_variants) - 1
            for attempt in range(_MAX_ATTEMPTS):
                try:
                    r = self.client.get(BENZINGA_REST_BASE, params=request_params)
                    if r.status_code in _RETRYABLE and attempt < _MAX_ATTEMPTS - 1:
                        logger.warning(
                            "Benzinga HTTP %s (attempt %d/%d) – retrying in %ds",
                            r.status_code, attempt + 1, _MAX_ATTEMPTS,
                            2 ** attempt,
                        )
                        time.sleep(2 ** attempt)
                        continue
                    r.raise_for_status()
                    break
                except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                    last_exc = exc
                    if attempt < _MAX_ATTEMPTS - 1:
                        logger.warning(
                            "Benzinga network error (attempt %d/%d): %s – retrying in %ds",
                            attempt + 1, _MAX_ATTEMPTS, exc, 2 ** attempt,
                        )
                        time.sleep(2 ** attempt)
                        continue
                    raise
                except httpx.HTTPStatusError as exc:
                    if r is None:
                        raise RuntimeError("HTTPStatusError raised without a response object") from exc
                    if r.status_code == 400 and not last_variant:
                        logger.warning(
                            "Benzinga rejected historical news request shape (%s); retrying with provider fallback.",
                            _sanitize_url(str(r.url)),
                        )
                        last_exc = exc
                        break
                    raise httpx.HTTPStatusError(
                        message=f"HTTP {r.status_code} from {_sanitize_url(str(r.url))}",
                        request=exc.request,
                        response=exc.response,
                    ) from None
            else:
                continue

            if r is not None and r.status_code < 400:
                break
            if last_variant and last_exc is not None:
                raise last_exc

        if r is None:
            raise RuntimeError(
                "Benzinga: no response after retries"
                + (f" (last error: {last_exc})" if last_exc else "")
            )

        ct = r.headers.get("content-type", "")
        try:
            data = r.json()
        except Exception:
            raise ValueError(
                f"Benzinga returned non-JSON (content-type={ct!r}, "
                f"status={r.status_code}, url={_sanitize_url(str(r.url))})"
            ) from None

        # Response may be ``[…]`` or ``{"articles": […], …}``
        items: list = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("articles") or data.get("results") or data.get("data") or []
            if not items:
                has_known = any(k in data for k in ("articles", "results", "data"))
                if data and not has_known:
                    logger.warning(
                        "Benzinga response dict has no recognized data key (keys=%s).",
                        ", ".join(list(data.keys())[:5]),
                    )
        else:
            logger.warning(
                "Benzinga returned %s instead of list/dict — 0 items ingested.",
                type(data).__name__,
            )

        return [normalize_benzinga_rest(it) for it in items if isinstance(it, dict)]

    def close(self) -> None:
        self.client.close()


# =====================================================================
# 1b) Additional News endpoints (synchronous, standalone functions)
# =====================================================================

BENZINGA_TOP_NEWS_URL = "https://api.benzinga.com/api/v2/news-top-stories"
BENZINGA_CHANNELS_URL = "https://api.benzinga.com/api/v2/channels"
BENZINGA_QUANTIFIED_URL = "https://api.benzinga.com/api/v2/newsquantified"


def fetch_benzinga_top_news(
    api_key: str,
    *,
    channel: str | None = None,
    limit: int = 20,
    display_output: str | None = None,
    type_: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch curated top news from Benzinga.

    Parameters
    ----------
    api_key : str
        Benzinga API key.
    channel : str, optional
        Comma-separated channel names to filter by.
    limit : int
        Maximum number of stories (default 20).
    display_output : str, optional
        ``"full"``, ``"abstract"`` or ``"headline"``.
    type_ : str, optional
        Content type filter.

    Returns
    -------
    list[dict]
        Raw top news items with keys: author, created, updated, title,
        teaser, body, url, image, channels, stocks, tags.
    """
    params: dict[str, Any] = {"token": api_key, "limit": str(limit)}
    if channel:
        params["channel"] = channel
    if display_output:
        params["displayOutput"] = display_output
    if type_:
        params["type"] = type_

    with httpx.Client(timeout=10.0, headers={"Accept": "application/json"}) as client:
        try:
            r = _request_with_retry(client, BENZINGA_TOP_NEWS_URL, params, label="Benzinga top_news")
            data = r.json()
        except Exception as exc:
            log_fetch_warning("Benzinga top_news", exc)
            return []

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("articles") or data.get("results") or data.get("data") or []
    return []


def fetch_benzinga_channels(
    api_key: str,
    *,
    page_size: int = 100,
    page: int = 0,
) -> list[dict[str, Any]]:
    """Fetch available news channel IDs/names from Benzinga.

    Returns
    -------
    list[dict]
        Channel entries with keys like ``name``, ``id``.
    """
    params: dict[str, Any] = {
        "token": api_key,
        "pageSize": str(page_size),
        "page": str(page),
    }

    with httpx.Client(timeout=10.0, headers={"Accept": "application/json"}) as client:
        try:
            r = _request_with_retry(client, BENZINGA_CHANNELS_URL, params, label="Benzinga channels")
            data = r.json()
        except Exception as exc:
            log_fetch_warning("Benzinga channels", exc)
            return []

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("channels") or data.get("data") or []
    return []


def fetch_benzinga_quantified_news(
    api_key: str,
    *,
    page_size: int = 50,
    page: int = 0,
    symbols: str | None = None,
    date: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    updated_since: str | int | None = None,
) -> list[dict[str, Any]]:
    """Fetch quantified news (news with price-impact context) from Benzinga.

    Authenticates via the ``?token=`` query parameter (consistent with the
    official ``benzinga-python-client`` and the rest of our Benzinga calls).
    Live tests confirm both ``Authorization`` header and ``?token=`` are
    accepted by the server, but ``?token=`` keeps the codebase uniform.

    All query parameters are documented in snake_case (``date_from``,
    ``date_to``, ``updated_since``, ``pagesize``, ``page``, ``symbols``,
    ``date``) per the official Benzinga newsquantified reference.

    Returns
    -------
    list[dict]
        Items with keys: Symb, Headlines, DayOpen, OpenGap%, Range%, etc.
    """
    params: dict[str, Any] = {
        "token": api_key,
        "pagesize": str(page_size),
        "page": str(page),
    }
    if symbols:
        params["symbols"] = symbols
    if date:
        params["date"] = date
    if date_from:
        params["date_from"] = date_from
    if date_to:
        params["date_to"] = date_to
    if updated_since is not None:
        params["updated_since"] = str(updated_since)

    with httpx.Client(timeout=10.0, headers={"Accept": "application/json"}) as client:
        try:
            r = _request_with_retry(client, BENZINGA_QUANTIFIED_URL, params, label="Benzinga quantified_news")
            data = r.json()
        except Exception as exc:
            log_fetch_warning("Benzinga quantified_news", exc)
            return []

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("articles") or data.get("results") or data.get("data") or []
    return []


# =====================================================================
# 2) WebSocket streaming adapter (async in daemon thread)
# =====================================================================

# Default WS URL per Benzinga docs.  Override via BENZINGA_WS_URL env var.
DEFAULT_BENZINGA_WS_URL = "wss://api.benzinga.com/api/v1/news/stream"


class BenzingaWsAdapter:
    """WebSocket news streamer – runs in a background daemon thread.

    Items are pushed into ``self.queue`` (thread-safe) and can be
    drained from the main thread via ``drain()``.

    Usage::

        ws = BenzingaWsAdapter(api_key, ws_url)
        ws.start()          # non-blocking: spawns daemon thread

        # On each Streamlit refresh:
        items = ws.drain()  # returns List[NewsItem], may be empty
    """

    # Adapter is considered unhealthy once this many consecutive WS connect
    # attempts have failed without a successful intervening handshake.
    _WS_HEALTH_THRESHOLD: int = 5

    # Bounded retry budget for the put_nowait/get_nowait race window in
    # :meth:`_enqueue_item`. Audit 2026-05-10 (PR-F).
    _ENQUEUE_RETRY_BUDGET: int = 8

    def __init__(
        self,
        api_key: str,
        ws_url: str = DEFAULT_BENZINGA_WS_URL,
        channels: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.ws_url = ws_url
        self.queue: queue.Queue[NewsItem] = queue.Queue(maxsize=5000)

        # Optional client-side channel filter (WS pushes all news).
        self._channel_filter: set[str] | None = None
        if channels:
            self._channel_filter = {
                c.strip().lower() for c in channels.split(",") if c.strip()
            }

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        # Health tracking: count of consecutive *connect* failures since the
        # last successful WS handshake. Exposed via :pyattr:`is_healthy`.
        self._consecutive_connect_failures: int = 0
        # PR-F (audit 2026-05-10): drop accounting for the bounded
        # ring-buffer enqueue. ``total_items_dropped`` counts items the
        # adapter chose to evict (queue full but new item still placed).
        # ``total_enqueue_drops`` counts items that could NOT be placed
        # at all because the queue stayed full across the retry window.
        self.total_items_dropped: int = 0
        self.total_enqueue_drops: int = 0

    # ── Public API ──────────────────────────────────────────────

    @property
    def is_healthy(self) -> bool:
        """True while consecutive connect failures are below the threshold.

        Flips back to True on the next successful WS handshake (which resets
        the counter inside :meth:`_ws_loop`).
        """
        return self._consecutive_connect_failures < self._WS_HEALTH_THRESHOLD

    def _matches_channel_filter(self, item: NewsItem) -> bool:
        """Return True if item matches the channel filter (or no filter set)."""
        if self._channel_filter is None:
            return True
        # Extract channels from the raw Benzinga payload.
        # Benzinga WS items have raw["channels"] as list of dicts with "name".
        raw_channels = item.raw.get("channels") or []
        item_channels: set[str] = set()
        if isinstance(raw_channels, list):
            for ch in raw_channels:
                if isinstance(ch, dict):
                    name = ch.get("name", "")
                elif isinstance(ch, str):
                    name = ch
                else:
                    continue
                if name:
                    item_channels.add(name.strip().lower())
        return bool(item_channels & self._channel_filter)

    def start(self) -> None:
        """Start the background WS loop (daemon thread)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="benzinga-ws")
        self._thread.start()
        logger.info("BenzingaWsAdapter: background thread started.")

    def stop(self) -> None:
        """Signal the background thread to stop."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            logger.info("BenzingaWsAdapter: background thread stopped.")

    def drain(self) -> list[NewsItem]:
        """Non-blocking: drain all queued items."""
        items: list[NewsItem] = []
        while True:
            try:
                items.append(self.queue.get_nowait())
            except queue.Empty:
                break
        return items

    def _enqueue_item(self, item: NewsItem) -> bool:
        """Place *item* on :attr:`queue` with bounded ring-buffer eviction.

        Audit 2026-05-10 (PR-F): the previous inline implementation had
        a ``put_nowait`` -> ``Full`` -> ``get_nowait`` -> ``Empty`` -> ``pass``
        race followed by an UNGUARDED ``put_nowait(item)``. When the
        consumer drained between our ``Full`` exception and our eviction
        attempt the eviction quietly failed; the unguarded retry then
        either silently succeeded or raised ``queue.Full`` and killed
        the WS reader thread.

        The fix mirrors PR-D (#2125) on ``BackgroundPoller``:

        * On ``Empty`` we ``continue`` and retry ``put_nowait`` -- the
          consumer just made room, so the next put almost always wins.
        * Bound the loop with ``_ENQUEUE_RETRY_BUDGET`` to avoid a
          pathological producer/consumer cadence spinning.
        * If the item still cannot be placed, increment
          ``total_enqueue_drops`` and ``total_items_dropped`` and log a
          WARNING. Drops are no longer silent and never raise.

        Returns True iff the item was successfully enqueued.
        """
        evicted = 0
        enqueued = False
        for _ in range(self._ENQUEUE_RETRY_BUDGET):
            try:
                self.queue.put_nowait(item)
                enqueued = True
                break
            except queue.Full:
                try:
                    self.queue.get_nowait()
                    evicted += 1
                except queue.Empty:
                    # Race: consumer drained between our Full and our
                    # get_nowait. Retry the put -- do NOT silently drop.
                    continue

        if evicted:
            self.total_items_dropped += evicted
            logger.warning(
                "BenzingaWsAdapter: queue full (max=%d) -- evicted %d stale "
                "item(s) (total dropped: %d)",
                self.queue.maxsize, evicted, self.total_items_dropped,
            )

        if not enqueued:
            self.total_enqueue_drops += 1
            self.total_items_dropped += 1
            logger.warning(
                "BenzingaWsAdapter: could not enqueue item after %d retries "
                "(total enqueue drops: %d)",
                self._ENQUEUE_RETRY_BUDGET, self.total_enqueue_drops,
            )

        return enqueued

    # ── Internal: async event loop in daemon thread ─────────────

    def _run_loop(self) -> None:
        """Entry point for the daemon thread."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._ws_loop())
        except Exception:
            logger.exception("BenzingaWsAdapter: event loop crashed")
        finally:
            loop.close()

    async def _ws_loop(self) -> None:
        """Reconnect loop with exponential backoff."""
        try:
            import websockets  # type: ignore[import-untyped]
        except ImportError:
            logger.error("BenzingaWsAdapter requires 'websockets' package.  pip install websockets")
            return

        # Benzinga WS authenticates via ?token=<key> query string.
        # The Authorization header path returns HTTP 401.  Verified live 2026-04-21.
        sep = "&" if "?" in self.ws_url else "?"
        connect_url = f"{self.ws_url}{sep}token={self.api_key}"
        masked_url = f"{self.ws_url}{sep}token=***"

        backoff = 1.0
        while not self._stop_event.is_set():
            try:
                async with websockets.connect(
                    connect_url,
                    ping_interval=20,
                    ping_timeout=20,
                ) as ws:
                    logger.info("BenzingaWsAdapter: connected to %s", masked_url)
                    backoff = 1.0
                    # Successful handshake → adapter is healthy again.
                    self._consecutive_connect_failures = 0

                    # Optional subscribe handshake; server pushes news regardless.
                    auth_msg = json.dumps({"action": "subscribe", "data": {"streams": ["news"]}})
                    try:
                        await ws.send(auth_msg)
                    except Exception:
                        # Audit 2026-05-10 (PR-K): the subscribe handshake is
                        # optional (the server pushes news regardless), but a
                        # silent except: pass hides observability of upstream
                        # protocol changes. Log at debug with traceback so
                        # operators can correlate against connect/disconnect
                        # patterns without raising the log floor.
                        logger.debug(
                            "BenzingaWsAdapter: optional subscribe handshake "
                            "failed (server pushes news regardless)",
                            exc_info=True,
                        )

                    async for message in ws:
                        if self._stop_event.is_set():
                            break
                        try:
                            msg = json.loads(message)
                        except (json.JSONDecodeError, ValueError):
                            continue

                        payloads = self._extract_payloads(msg)
                        for p in payloads:
                            item = normalize_benzinga_ws(p)
                            if item.is_valid and self._matches_channel_filter(item):
                                self._enqueue_item(item)

            except Exception as exc:
                if self._stop_event.is_set():
                    break
                self._consecutive_connect_failures += 1
                logger.warning("BenzingaWsAdapter: connection error: %s — reconnecting in %.1fs (consecutive_failures=%d)", type(exc).__name__, backoff, self._consecutive_connect_failures, exc_info=True)
                # Split sleep into short intervals to allow faster shutdown
                _slept = 0.0
                while _slept < backoff and not self._stop_event.is_set():
                    await asyncio.sleep(min(0.5, backoff - _slept))
                    _slept += 0.5
                if self._stop_event.is_set():
                    break
                backoff = min(30.0, backoff * 1.7)

    @staticmethod
    def _extract_payloads(msg: Any) -> list[dict[str, Any]]:
        """Unpack WS message into a list of raw dicts.

        Benzinga's live WS (api_version=websocket/v1, kind=News/v1) wraps the
        actual article in ``msg["data"]["content"]``.  Older/simulated messages
        may put the article directly under ``msg["data"]`` or at the top level.
        """

        def _unwrap_content(d: dict[str, Any]) -> dict[str, Any]:
            content = d.get("content")
            if isinstance(content, dict):
                merged = dict(content)
                # Preserve envelope action/id without overwriting content fields.
                for k in ("action",):
                    if k in d and k not in merged:
                        merged[k] = d[k]
                return merged
            return d

        if isinstance(msg, dict) and "data" in msg:
            data = msg["data"]
            if isinstance(data, list):
                return [_unwrap_content(d) for d in data if isinstance(d, dict)]
            return [_unwrap_content(data)] if isinstance(data, dict) else []
        if isinstance(msg, list):
            return [_unwrap_content(m) for m in msg if isinstance(m, dict)]
        if isinstance(msg, dict):
            return [_unwrap_content(msg)]
        return []


# =====================================================================
# 3) Benzinga RSS adapter  (free tier — no API key required)
# =====================================================================
#
# Benzinga publishes two public market-news RSS feeds:
#   https://www.benzinga.com/markets/feed   — equities/macro market news
#   https://www.benzinga.com/news/feed      — general financial news
#
# Each <item> may carry one or more
#   <category domain="stock-symbol">TICKER</category>
# tags giving exact ticker attribution.  The feed requires no auth.

_BENZINGA_RSS_FEEDS: tuple[str, ...] = (
    "https://www.benzinga.com/markets/feed",
    "https://www.benzinga.com/news/feed",
)
_RSS_USER_AGENT = (
    "Mozilla/5.0 (compatible; skipp-algo/1.0; +https://skippalgo.com/bot)"
)
_RSS_TIMEOUT = 10  # seconds per feed
_RSS_MAX_WORKERS = 4  # parallel RSS fetch threads
_RSS_MAX_SEEN_GUIDS = 4096  # cap dedup memory; pipeline cache handles long-term
_RSS_MAX_ATTEMPTS = 3  # transient RSS errors: retry with exponential backoff
_RSS_RETRYABLE_EXCEPTIONS = (
    Exception,
)  # feedparser raises generic Exception on network/parse failures
_RSS_STOCK_DOMAIN = "stock-symbol"


def _parse_rss_tickers(entry: Any) -> list[str]:
    """Extract ticker symbols from feedparser entry tags."""
    tickers: list[str] = []
    for tag in getattr(entry, "tags", []) or []:
        domain = getattr(tag, "scheme", None) or getattr(tag, "domain", None) or ""
        term = getattr(tag, "term", None) or getattr(tag, "label", None) or ""
        if domain == _RSS_STOCK_DOMAIN and term:
            ticker = term.strip().upper()
            if ticker and 1 <= len(ticker) <= 6:
                tickers.append(ticker)
    return tickers


def _entry_to_news_item(entry: Any, *, source_url: str) -> NewsItem | None:
    """Convert a feedparser entry to a NewsItem.  Returns None on failure."""
    guid: str = (
        getattr(entry, "id", None)
        or getattr(entry, "link", None)
        or ""
    ).strip()
    title: str = (getattr(entry, "title", None) or "").strip()
    if not guid or not title:
        return None

    link: str | None = (getattr(entry, "link", None) or "").strip() or None

    def _struct_to_ts(struct: Any) -> float | None:
        if struct:
            import calendar as _calendar
            return float(_calendar.timegm(struct))
        return None

    # published timestamp — fall back to updated_parsed if the feed only
    # provides an updated date (RSS-7: be robust against partial feeds).
    published_ts = _struct_to_ts(getattr(entry, "published_parsed", None))
    updated_ts = _struct_to_ts(getattr(entry, "updated_parsed", None))
    if published_ts is None:
        published_ts = updated_ts if updated_ts is not None else 0.0
    if updated_ts is None:
        updated_ts = published_ts

    # snippet — prefer summary over content
    snippet: str = ""
    summary = getattr(entry, "summary", None) or ""
    if summary:
        snippet = re.sub(r"<[^>]+>", "", summary).strip()[:500]

    author: str = (
        getattr(entry, "author", None)
        or getattr(entry, "dc_creator", None)
        or "benzinga"
    ).strip()

    tickers = _parse_rss_tickers(entry)

    return NewsItem(
        provider="benzinga_rss",
        item_id=guid,
        published_ts=published_ts,
        updated_ts=updated_ts,
        headline=title,
        snippet=snippet,
        tickers=tickers,
        url=link,
        source=author,
        raw={
            "guid": guid,
            "feed_url": source_url,
            "tickers_raw": tickers,
        },
    )


def _process_parsed_feed(
    parsed: dict[str, Any],
    feed_url: str,
    *,
    min_epoch: float,
    adapter: BenzingaRssAdapter,
) -> list[NewsItem]:
    """Process entries from one parsed feed into NewsItems."""
    items: list[NewsItem] = []
    try:
        if parsed.get("bozo"):
            adapter.bozo_total += 1
            logger.warning(
                "BenzingaRSS: bozo parse of %s: %s",
                feed_url,
                parsed.get("bozo_exception", "?"),
            )
            if not parsed.get("entries"):
                return items
        for entry in parsed.get("entries", []):
            item = _entry_to_news_item(entry, source_url=feed_url)
            if item is None:
                continue
            adapter.items_parsed += 1
            if item.published_ts < min_epoch:
                continue
            with adapter._lock:
                if item.item_id in adapter._seen_guids_set:
                    adapter.items_deduped += 1
                    continue
                adapter._seen_guids.append(item.item_id)
                adapter._seen_guids_set.add(item.item_id)
                # Evict oldest when deque rolls over
                if len(adapter._seen_guids_set) > len(adapter._seen_guids):
                    adapter._seen_guids_set = set(adapter._seen_guids)
            items.append(item)
    except Exception as exc:
        adapter.fetch_errors += 1
        logger.warning("BenzingaRSS: parse failed for %s: %s", feed_url, exc)
    return items


def _fetch_single_feed(
    feed_url: str,
    *,
    timeout: int,
    feedparser: Any,
    max_attempts: int = _RSS_MAX_ATTEMPTS,
) -> dict[str, Any]:
    """Fetch a single RSS feed with retry/backoff.

    Returns the parsed feed dict.  On repeated failure returns an empty
    dict so the caller can continue with the remaining feeds.
    """
    for attempt in range(max_attempts):
        try:
            parsed = feedparser.parse(
                feed_url,
                agent=_RSS_USER_AGENT,
                request_headers={"Accept": "application/rss+xml, application/xml, */*"},
                timeout=timeout,
            )
            return parsed
        except _RSS_RETRYABLE_EXCEPTIONS as exc:
            if attempt < max_attempts - 1:
                wait = 2 ** attempt
                logger.warning(
                    "BenzingaRSS: fetch failed for %s (attempt %d/%d): %s — retrying in %ds",
                    feed_url,
                    attempt + 1,
                    max_attempts,
                    exc,
                    wait,
                )
                time.sleep(wait)
            else:
                logger.warning(
                    "BenzingaRSS: fetch failed for %s after %d attempts: %s",
                    feed_url,
                    max_attempts,
                    exc,
                )
    return {}


class BenzingaRssAdapter:
    """Polls Benzinga's public RSS feeds — no API key required.

    Typical usage (inside ``poll_once()``)::

        adapter = BenzingaRssAdapter()
        items: list[NewsItem] = adapter.fetch_news(min_epoch=last_seen)

    The adapter uses a simple in-process seen-guid set to deduplicate
    across consecutive polls in the same process.  Cross-process
    deduplication is handled by the pipeline cache layer.
    """

    def __init__(
        self,
        *,
        feeds: tuple[str, ...] = _BENZINGA_RSS_FEEDS,
        timeout: int = _RSS_TIMEOUT,
    ) -> None:
        self._feeds = feeds
        self._timeout = timeout
        self._seen_guids: collections.deque[str] = collections.deque(maxlen=_RSS_MAX_SEEN_GUIDS)
        self._seen_guids_set: set[str] = set()
        self._lock = threading.Lock()
        # ── Metrics counters ──────────────────────────────────────────
        self.fetch_total: int = 0
        self.fetch_errors: int = 0
        self.last_fetch_errors: int = 0  # errors on the most-recent fetch call
        self.items_parsed: int = 0
        self.items_deduped: int = 0
        self.bozo_total: int = 0
        self.last_fetch_duration: float = 0.0

    def fetch_news(self, *, min_epoch: float = 0.0) -> list[NewsItem]:
        """Fetch and return new NewsItems from all configured RSS feeds.

        Args:
            min_epoch: only include items with ``published_ts >= min_epoch``.
                       Pass 0.0 to get all available items on first call.

        Returns a list sorted oldest-first by ``published_ts``.
        """
        try:
            import feedparser  # type: ignore[import-untyped]
        except ImportError as exc:
            logger.warning(
                "feedparser not installed — BenzingaRssAdapter unavailable: %s", exc
            )
            return []

        results: list[NewsItem] = []
        _t0 = time.monotonic()
        _errors_this_fetch: int = 0

        if not self._feeds:
            logger.warning("BenzingaRSS: no feeds configured; marking fetch as error")
            self.fetch_total += 1
            self.fetch_errors += 1
            self.last_fetch_errors = 1
            self.last_fetch_duration = time.monotonic() - _t0
            return []

        workers = min(len(self._feeds), _RSS_MAX_WORKERS)
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_url = {
                executor.submit(
                    _fetch_single_feed, feed_url, timeout=self._timeout, feedparser=feedparser
                ): feed_url
                for feed_url in self._feeds
            }
            for future in concurrent.futures.as_completed(future_to_url):
                feed_url = future_to_url[future]
                try:
                    parsed = future.result()
                except Exception as exc:
                    _errors_this_fetch += 1
                    self.fetch_errors += 1
                    logger.warning("BenzingaRSS: fetch failed for %s: %s", feed_url, exc)
                    continue
                if not parsed:
                    _errors_this_fetch += 1
                    self.fetch_errors += 1
                    continue
                if parsed.get("bozo") and not parsed.get("entries"):
                    _errors_this_fetch += 1
                    self.fetch_errors += 1
                prev_errors = self.fetch_errors
                results.extend(
                    _process_parsed_feed(
                        parsed, feed_url, min_epoch=min_epoch, adapter=self
                    )
                )
                _errors_this_fetch += max(0, self.fetch_errors - prev_errors)

        self.fetch_total += 1
        self.last_fetch_errors = _errors_this_fetch
        self.last_fetch_duration = time.monotonic() - _t0

        results.sort(key=lambda x: x.published_ts)
        return results

    def close(self) -> None:
        """No-op; present for interface parity with other adapters."""
