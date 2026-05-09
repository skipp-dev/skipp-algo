"""FMP political-trades ingestion adapter (Senate + House).

Exposes the ``/stable/senate-trades`` and ``/stable/house-trades``
endpoints which surface congressional trading disclosures.  These are
high-signal catalysts (Pelosi-style trades historically front-run
sector moves) that the existing FMP news adapter doesn't surface.

Mirrors the DISABLED-endpoint short-circuit pattern from
``ingest_unusual_whales.py``: on 401/403/404 the path is marked
disabled for the lifetime of the process so subsequent polls don't
burn quota retrying a tier-locked endpoint.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

FMP_BASE = "https://financialmodelingprep.com/stable"
# Live-audit 2026-05-09: /stable/senate-trades and /stable/house-trades
# return 400 when called without a `symbol=` param — they are the per-ticker
# detail endpoints, NOT bulk feeds. The legacy /v4/senate-trading-rss-feed
# bulk path is restricted to subscribers from before 2024-08-31 (403).
# As a result the `enable_fmp_senate_trades` and `enable_fmp_house_trades`
# config flags default to "0". Copilot follow-up (2026-05-09): note that
# `_TIER_LIMITED_CODES = {401, 403, 404}` does NOT include 400, so a 400
# response is caught by the module-level wrapper but does NOT auto-disable
# the endpoint — keep `ENABLE_FMP_SENATE_TRADES=0` / `ENABLE_FMP_HOUSE_TRADES=0`
# until per-symbol iteration lands; otherwise the path will be polled every
# tick and burn quota on a 400-loop. A symbol-iteration implementation over
# the universe is left as a follow-up.
# Follow-up: implement per-symbol congressional trading collection or restore
# bulk access via a different FMP plan / endpoint.
FMP_SENATE_TRADES_PATH = "/senate-trades"
FMP_HOUSE_TRADES_PATH = "/house-trades"

# Sanitize apikey from URLs in error messages / logs.
_APIKEY_RE = re.compile(r"(apikey|api_key|token|key)=[^&]+", re.IGNORECASE)


def _sanitize_url(url: str) -> str:
    return _APIKEY_RE.sub(r"\1=***", url)


# ── DISABLED-endpoint pattern (mirrors _bz_http.py / ingest_unusual_whales.py) ──

_DISABLED_PATHS: set[str] = set()
_disabled_lock = threading.Lock()
_TIER_LIMITED_CODES = frozenset({401, 403, 404})


# Audit-fix (2026-05-09): FmpPoliticalEndpointDisabledError removed (defined
# but never raised; mute path is mark_fmp_political_disabled + Exception catch).


def is_fmp_political_disabled(label: str) -> bool:
    with _disabled_lock:
        return label in _DISABLED_PATHS


def mark_fmp_political_disabled(label: str) -> None:
    with _disabled_lock:
        _DISABLED_PATHS.add(label)


def clear_fmp_political_disabled() -> None:
    with _disabled_lock:
        _DISABLED_PATHS.clear()


class FmpPoliticalAdapter:
    """Synchronous adapter for FMP /senate-trades and /house-trades."""

    _RETRYABLE_CODES = frozenset({429, 500, 502, 503, 504})
    _MAX_RETRIES = 3

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise RuntimeError("FMP_API_KEY missing")
        self.api_key = api_key
        self.client = httpx.Client(timeout=10.0)

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET with retry, DISABLED short-circuit, sanitized errors."""
        if is_fmp_political_disabled(path):
            return None
        url = f"{FMP_BASE}{path}"
        merged = {"apikey": self.api_key, **(params or {})}
        last_exc: Exception | None = None
        for attempt in range(1, self._MAX_RETRIES + 1):
            try:
                r = self.client.get(url, params=merged)
                if r.status_code in _TIER_LIMITED_CODES:
                    mark_fmp_political_disabled(path)
                    logger.warning(
                        "FMP %d from %s — endpoint disabled for this process.",
                        r.status_code,
                        _sanitize_url(str(r.url)),
                    )
                    return None
                if (
                    r.status_code in self._RETRYABLE_CODES
                    and attempt < self._MAX_RETRIES
                ):
                    wait = 2 ** attempt
                    logger.warning(
                        "FMP %d from %s — retry %d/%d in %ds",
                        r.status_code,
                        _sanitize_url(str(r.url)),
                        attempt,
                        self._MAX_RETRIES,
                        wait,
                    )
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                try:
                    return r.json()
                except (json.JSONDecodeError, ValueError):
                    raise ValueError(
                        f"FMP returned non-JSON (status={r.status_code}, "
                        f"url={_sanitize_url(str(r.url))})"
                    ) from None
            except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                last_exc = exc
                if attempt < self._MAX_RETRIES:
                    time.sleep(2 ** attempt)
                    continue
        if last_exc is not None:
            raise last_exc
        raise RuntimeError(
            f"FMP: all {self._MAX_RETRIES} retries exhausted for {_sanitize_url(url)}"
        )

    def fetch_senate_trades(self, *, page: int = 0) -> list[dict]:
        """GET /stable/senate-trades?page=…"""
        data = self._get_json(FMP_SENATE_TRADES_PATH, {"page": page})
        if not isinstance(data, list):
            return []
        return [it for it in data if isinstance(it, dict)]

    def fetch_house_trades(self, *, page: int = 0) -> list[dict]:
        """GET /stable/house-trades?page=…"""
        data = self._get_json(FMP_HOUSE_TRADES_PATH, {"page": page})
        if not isinstance(data, list):
            return []
        return [it for it in data if isinstance(it, dict)]

    def close(self) -> None:
        self.client.close()


# ── Module-level wrappers (mirror ingest_unusual_whales pattern) ─────


def _adapter_or_none(api_key: str) -> FmpPoliticalAdapter | None:
    if not api_key:
        return None
    try:
        return FmpPoliticalAdapter(api_key)
    except RuntimeError:
        return None


def fetch_fmp_senate_trades(api_key: str, *, page: int = 0) -> list[dict]:
    """Module-level wrapper: returns [] on missing key / adapter error."""
    adapter = _adapter_or_none(api_key)
    if adapter is None:
        return []
    try:
        return adapter.fetch_senate_trades(page=page)
    except Exception as exc:
        logger.warning("FMP senate-trades fetch failed: %s", type(exc).__name__)
        return []
    finally:
        adapter.close()


def fetch_fmp_house_trades(api_key: str, *, page: int = 0) -> list[dict]:
    """Module-level wrapper: returns [] on missing key / adapter error."""
    adapter = _adapter_or_none(api_key)
    if adapter is None:
        return []
    try:
        return adapter.fetch_house_trades(page=page)
    except Exception as exc:
        logger.warning("FMP house-trades fetch failed: %s", type(exc).__name__)
        return []
    finally:
        adapter.close()
