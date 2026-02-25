"""Benzinga news ingestion adapters: REST delta + WebSocket streaming.

REST:
    Polls ``/api/v2/news`` with ``updatedSince`` for delta-only fetches.
    Synchronous (httpx.Client) — called from ``poll_once()``.

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
import threading
import time
from typing import Any, Dict, List, Optional

import re

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
        self.client = httpx.Client(timeout=10.0)

    def fetch_news(
        self,
        updated_since: Optional[str] = None,
        page_size: int = 100,
    ) -> List[NewsItem]:
        """Fetch latest news, optionally only items updated since *updated_since*.

        ``updated_since`` format depends on Benzinga API (epoch or ISO).
        """
        params: Dict[str, Any] = {
            "token": self.api_key,
            "pageSize": page_size,
        }
        if updated_since:
            params["updatedSince"] = updated_since

        r = self.client.get(BENZINGA_REST_BASE, params=params)
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise httpx.HTTPStatusError(
                message=f"HTTP {r.status_code} from {_sanitize_url(str(r.url))}",
                request=exc.request,
                response=exc.response,
            ) from None

        ct = r.headers.get("content-type", "")
        try:
            data = r.json()
        except Exception:
            raise ValueError(
                f"Benzinga returned non-JSON (content-type={ct!r}, "
                f"status={r.status_code}, url={_sanitize_url(str(r.url))})"
            )

        # Response may be ``[…]`` or ``{"articles": […], …}``
        items: list = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("articles") or data.get("results") or data.get("data") or []

        return [normalize_benzinga_rest(it) for it in items if isinstance(it, dict)]

    def close(self) -> None:
        self.client.close()


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

    def __init__(self, api_key: str, ws_url: str = DEFAULT_BENZINGA_WS_URL) -> None:
        self.api_key = api_key
        self.ws_url = ws_url
        self.queue: queue.Queue[NewsItem] = queue.Queue(maxsize=5000)

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # ── Public API ──────────────────────────────────────────────

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

    def drain(self) -> List[NewsItem]:
        """Non-blocking: drain all queued items."""
        items: List[NewsItem] = []
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
                            if item.is_valid:
                                try:
                                    self.queue.put_nowait(item)
                                except queue.Full:
                                    # Drop oldest to make room
                                    try:
                                        self.queue.get_nowait()
                                    except queue.Empty:
                                        pass
                                    self.queue.put_nowait(item)

            except Exception as exc:
                if self._stop_event.is_set():
                    break
                logger.warning("BenzingaWsAdapter: connection error: %s — reconnecting in %.1fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(30.0, backoff * 1.7)

    @staticmethod
    def _extract_payloads(msg: Any) -> List[Dict[str, Any]]:
        """Unpack WS message into a list of raw dicts."""
        if isinstance(msg, dict) and "data" in msg:
            data = msg["data"]
            return data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        if isinstance(msg, list):
            return [m for m in msg if isinstance(m, dict)]
        if isinstance(msg, dict):
            return [msg]
        return []
