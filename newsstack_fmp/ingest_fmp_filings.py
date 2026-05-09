"""FMP SEC 8-K filings ingestion adapter.

Exposes ``/stable/sec-filings/8-K-latest`` which surfaces material-event
filings (Item 1.01 Material Definitive Agreement, Item 2.02 Earnings,
Item 5.02 Officer Departure, etc.) — high-grade ML signal that the
existing FMP news adapter doesn't surface.

Mirrors the DISABLED-endpoint short-circuit pattern from
``ingest_unusual_whales.py`` and ``ingest_fmp_political.py``: on
401/403/404 the path is marked disabled for the lifetime of the process
so subsequent polls don't burn quota retrying a tier-locked endpoint.
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
FMP_8K_LATEST_PATH = "/sec-filings/8-K-latest"
FMP_13F_LATEST_PATH = "/sec-filings/13F-HR-latest"

_APIKEY_RE = re.compile(r"(apikey|api_key|token|key)=[^&]+", re.IGNORECASE)


def _sanitize_url(url: str) -> str:
    return _APIKEY_RE.sub(r"\1=***", url)


# ── DISABLED-endpoint pattern ─────────────────────────────────────

_DISABLED_PATHS: set[str] = set()
_disabled_lock = threading.Lock()
_TIER_LIMITED_CODES = frozenset({401, 403, 404})


class FmpFilingsEndpointDisabledError(RuntimeError):
    def __init__(self, label: str) -> None:
        super().__init__(
            f"FMP filings endpoint disabled (tier-limited or retired): {label}"
        )
        self.label = label


def is_fmp_filings_disabled(label: str) -> bool:
    with _disabled_lock:
        return label in _DISABLED_PATHS


def mark_fmp_filings_disabled(label: str) -> None:
    with _disabled_lock:
        _DISABLED_PATHS.add(label)


def clear_fmp_filings_disabled() -> None:
    with _disabled_lock:
        _DISABLED_PATHS.clear()


class FmpFilingsAdapter:
    """Synchronous adapter for FMP /sec-filings/8-K-latest."""

    _RETRYABLE_CODES = frozenset({429, 500, 502, 503, 504})
    _MAX_RETRIES = 3

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise RuntimeError("FMP_API_KEY missing")
        self.api_key = api_key
        self.client = httpx.Client(timeout=10.0)

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if is_fmp_filings_disabled(path):
            return None
        url = f"{FMP_BASE}{path}"
        merged = {"apikey": self.api_key, **(params or {})}
        last_exc: Exception | None = None
        for attempt in range(1, self._MAX_RETRIES + 1):
            try:
                r = self.client.get(url, params=merged)
                if r.status_code in _TIER_LIMITED_CODES:
                    mark_fmp_filings_disabled(path)
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

    def fetch_8k_latest(self, *, page: int = 0, limit: int = 50) -> list[dict]:
        """GET /stable/sec-filings/8-K-latest?page=…&limit=…"""
        data = self._get_json(
            FMP_8K_LATEST_PATH, {"page": page, "limit": limit}
        )
        if not isinstance(data, list):
            return []
        return [it for it in data if isinstance(it, dict)]

    def fetch_13f_latest(self, *, page: int = 0, limit: int = 50) -> list[dict]:
        """GET /stable/sec-filings/13F-HR-latest?page=…&limit=…

        B6 follow-up (PR5 2026-05-09): institutional 13F-HR filings as a
        news-shaped event stream — no CIK iteration needed.
        """
        data = self._get_json(
            FMP_13F_LATEST_PATH, {"page": page, "limit": limit}
        )
        if not isinstance(data, list):
            return []
        return [it for it in data if isinstance(it, dict)]

    def close(self) -> None:
        self.client.close()


# ── Module-level wrapper ─────────────────────────────────────────


def _adapter_or_none(api_key: str) -> FmpFilingsAdapter | None:
    if not api_key:
        return None
    try:
        return FmpFilingsAdapter(api_key)
    except RuntimeError:
        return None


def fetch_fmp_8k_latest(
    api_key: str, *, page: int = 0, limit: int = 50
) -> list[dict]:
    """Module-level wrapper: returns [] on missing key / adapter error."""
    adapter = _adapter_or_none(api_key)
    if adapter is None:
        return []
    try:
        return adapter.fetch_8k_latest(page=page, limit=limit)
    except Exception as exc:
        logger.warning("FMP 8-K-latest fetch failed: %s", type(exc).__name__)
        return []
    finally:
        adapter.close()


def fetch_fmp_13f_latest(
    api_key: str, *, page: int = 0, limit: int = 50
) -> list[dict]:
    """Module-level wrapper: returns [] on missing key / adapter error."""
    adapter = _adapter_or_none(api_key)
    if adapter is None:
        return []
    try:
        return adapter.fetch_13f_latest(page=page, limit=limit)
    except Exception as exc:
        logger.warning("FMP 13F-HR-latest fetch failed: %s", type(exc).__name__)
        return []
    finally:
        adapter.close()
