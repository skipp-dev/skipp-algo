"""Benzinga news ingestion adapters: REST delta + WebSocket streaming.

REST:
    Polls ``/api/v2/news`` with ``updatedSince`` for delta-only fetches.
    Synchronous (httpx.Client) — called from ``poll_once()``.

    Additional news endpoints:
    - ``/api/v2/news/top`` — curated top news stories
    - ``/api/v2/news/channels`` — list available channel IDs/names
    - ``/api/v2/news/quantified`` — quantified news with price context

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
import json
import logging
import queue
import re
import threading
import time
from typing import Any

import httpx

from .common_types import NewsItem
from .normalize import normalize_benzinga_rest, normalize_benzinga_ws

logger = logging.getLogger(__name__)

# Regex to strip API keys/tokens from URLs before logging.
_TOKEN_RE = re.compile(r"(apikey|token)=[^&]+", re.IGNORECASE)


def _sanitize_url(url: str) -> str:
    """Remove apikey/token query params from a URL for safe logging."""
    return _TOKEN_RE.sub(r"\1=***", url)


# =====================================================================
# 1) REST delta adapter (synchronous)
# =====================================================================

BENZINGA_REST_BASE = "https://api.benzinga.com/api/v2/news"


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
        params: dict[str, Any] = {
            "token": self.api_key,
            "pageSize": page_size,
        }
        if updated_since:
            params["updatedSince"] = updated_since
        if channels:
            params["channels"] = channels
        if topics:
            params["topics"] = topics

        _RETRYABLE = {429, 500, 502, 503, 504}
        _MAX_ATTEMPTS = 3
        last_exc: Exception | None = None
        r: httpx.Response | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                r = self.client.get(BENZINGA_REST_BASE, params=params)
                if r.status_code in _RETRYABLE and attempt < _MAX_ATTEMPTS - 1:
                    logger.warning(
                        "Benzinga HTTP %s (attempt %d/%d) – retrying in %ds",
                        r.status_code, attempt + 1, _MAX_ATTEMPTS,
                        2 ** attempt,
                    )
                    time.sleep(2 ** attempt)
                    continue
                r.raise_for_status()
                break  # success
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
                assert r is not None
                raise httpx.HTTPStatusError(
                    message=f"HTTP {r.status_code} from {_sanitize_url(str(r.url))}",
                    request=exc.request,
                    response=exc.response,
                ) from None

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

BENZINGA_TOP_NEWS_URL = "https://api.benzinga.com/api/v2/news/top"
BENZINGA_CHANNELS_URL = "https://api.benzinga.com/api/v2/news/channels"
BENZINGA_QUANTIFIED_URL = "https://api.benzinga.com/api/v2/news/quantified"

_NEWS_RETRYABLE = {429, 500, 502, 503, 504}
_NEWS_MAX_ATTEMPTS = 3


def _news_request_with_retry(
    client: httpx.Client,
    url: str,
    params: dict[str, Any],
) -> httpx.Response:
    """GET with exponential backoff on retryable status codes (news)."""
    last_exc: Exception | None = None
    r: httpx.Response | None = None
    for attempt in range(_NEWS_MAX_ATTEMPTS):
        try:
            r = client.get(url, params=params)
            if r.status_code in _NEWS_RETRYABLE and attempt < _NEWS_MAX_ATTEMPTS - 1:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r
        except (httpx.ConnectError, httpx.ReadTimeout) as exc:
            last_exc = exc
            if attempt < _NEWS_MAX_ATTEMPTS - 1:
                time.sleep(2 ** attempt)
                continue
            raise
        except httpx.HTTPStatusError:
            raise
    if r is not None:
        return r
    raise RuntimeError(
        "Benzinga news: no response after retries"
        + (f" (last error: {last_exc})" if last_exc else "")
    )


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
            r = _news_request_with_retry(client, BENZINGA_TOP_NEWS_URL, params)
            data = r.json()
        except Exception as exc:
            logger.warning("Benzinga top_news fetch failed: %s", _sanitize_url(str(exc)))
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
            r = _news_request_with_retry(client, BENZINGA_CHANNELS_URL, params)
            data = r.json()
        except Exception as exc:
            logger.warning("Benzinga channels fetch failed: %s", _sanitize_url(str(exc)))
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
    date_from: str | None = None,
    date_to: str | None = None,
    updated_since: str | None = None,
    publish_since: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch quantified news (news with price-impact context) from Benzinga.

    Returns
    -------
    list[dict]
        Items with keys: headline, volume, day_open, open_gap, range, etc.
    """
    params: dict[str, Any] = {
        "token": api_key,
        "pageSize": str(page_size),
        "page": str(page),
    }
    if date_from:
        params["dateFrom"] = date_from
    if date_to:
        params["dateTo"] = date_to
    if updated_since:
        params["updatedSince"] = updated_since
    if publish_since:
        params["publishSince"] = publish_since

    with httpx.Client(timeout=10.0, headers={"Accept": "application/json"}) as client:
        try:
            r = _news_request_with_retry(client, BENZINGA_QUANTIFIED_URL, params)
            data = r.json()
        except Exception as exc:
            logger.warning("Benzinga quantified_news fetch failed: %s", _sanitize_url(str(exc)))
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

    # ── Public API ──────────────────────────────────────────────

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

        backoff = 1.0
        while not self._stop_event.is_set():
            try:
                async with websockets.connect(
                    self.ws_url,
                    additional_headers={"Authorization": f"Token {self.api_key}"},
                    ping_interval=20,
                    ping_timeout=20,
                ) as ws:
                    logger.info("BenzingaWsAdapter: connected to %s", self.ws_url)
                    backoff = 1.0

                    # Auth / subscribe handshake (adjust to real Benzinga WS protocol)
                    auth_msg = json.dumps({"action": "subscribe", "data": {"streams": ["news"]}})
                    await ws.send(auth_msg)

                    async for message in ws:
                        if self._stop_event.is_set():
                            break
                        try:
                            msg = json.loads(message)
                        except Exception:
                            continue

                        payloads = self._extract_payloads(msg)
                        for p in payloads:
                            item = normalize_benzinga_ws(p)
                            if item.is_valid and self._matches_channel_filter(item):
                                try:
                                    self.queue.put_nowait(item)
                                except queue.Full:
                                    # Drop oldest to make room
                                    try:
                                        self.queue.get_nowait()
                                    except queue.Empty:
                                        pass
                                    self.queue.put_nowait(item)
                                    logger.warning(
                                        "BenzingaWsAdapter: queue full (max=%d) — dropped oldest item.",
                                        self.queue.maxsize,
                                    )

            except Exception as exc:
                if self._stop_event.is_set():
                    break
                logger.warning("BenzingaWsAdapter: connection error: %s — reconnecting in %.1fs", exc, backoff)
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
        """Unpack WS message into a list of raw dicts."""
        if isinstance(msg, dict) and "data" in msg:
            data = msg["data"]
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict)]
            return [data] if isinstance(data, dict) else []
        if isinstance(msg, list):
            return [m for m in msg if isinstance(m, dict)]
        if isinstance(msg, dict):
            return [msg]
        return []
