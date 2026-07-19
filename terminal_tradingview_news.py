"""Compatibility types for the retired TradingView news provider.

TradingView remains a consumer, publish, and validation surface.  It is not an
upstream provider for the runtime system.  The former unofficial headlines
endpoint was intentionally removed; all public fetch helpers are now
fail-closed compatibility functions and perform no network I/O.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class TVHeadline:
    """Legacy headline shape retained for consumer/schema compatibility."""

    id: str
    title: str
    provider: str
    source: str
    published: float
    urgency: int
    tickers: list[str]
    story_url: str
    is_exclusive: bool = False
    is_flash: bool = False
    permission: str = ""

    def to_feed_dict(self) -> dict[str, Any]:
        """Convert a legacy headline to the terminal feed shape."""
        if self.published > 0:
            age_min = max((time.time() - self.published) / 60.0, 0.0)
            if age_min <= 5:
                recency = "ULTRA_FRESH"
            elif age_min <= 15:
                recency = "FRESH"
            elif age_min <= 60:
                recency = "WARM"
            elif age_min <= 1440:
                recency = "AGING"
            else:
                recency = "STALE"
            age_minutes: float | None = round(age_min, 1)
        else:
            recency = "UNKNOWN"
            age_minutes = None

        return {
            "item_id": self.id,
            "ticker": self.tickers[0] if self.tickers else "MARKET",
            "tickers_all": self.tickers,
            "headline": self.title,
            "snippet": "",
            "url": self.story_url,
            "source": self.source,
            "published_ts": self.published,
            "updated_ts": self.published,
            "provider": f"tv_{self.provider}",
            "category": "news",
            "impact": 0.5,
            "clarity": 0.5,
            "polarity": 0.0,
            "news_score": 0.4,
            "cluster_hash": "",
            "novelty_count": 1,
            "relevance": 0.5,
            "entity_count": len(self.tickers),
            "sentiment_label": "neutral",
            "sentiment_score": 0.0,
            "event_class": "UNKNOWN",
            "event_label": "",
            "materiality": "MEDIUM",
            "recency_bucket": recency,
            "age_minutes": age_minutes,
            "is_actionable": recency in {"ULTRA_FRESH", "FRESH", "WARM"},
            "source_tier": _source_tier(self.provider),
            "source_rank": _source_rank(self.provider),
            "channels": [],
            "tags": ["tradingview"],
            "is_wiim": False,
        }


_TIER_1_PROVIDERS = {"reuters", "dow-jones", "market-watch"}
_TIER_2_PROVIDERS = {"tradingview", "dpa_afx", "cnbctv"}
_TIER_3_PROVIDERS = {"gurufocus", "stocktwits", "zacks", "invezz", "cointelegraph"}


def _source_tier(provider: str) -> str:
    normalized = provider.lower()
    if normalized in _TIER_1_PROVIDERS:
        return "TIER_1"
    if normalized in _TIER_2_PROVIDERS:
        return "TIER_2"
    if normalized in _TIER_3_PROVIDERS:
        return "TIER_3"
    return "TIER_4"


def _source_rank(provider: str) -> int:
    return {"TIER_1": 1, "TIER_2": 2, "TIER_3": 3}.get(_source_tier(provider), 4)


@dataclass
class _HealthState:
    """Legacy health shape used by the terminal diagnostics panel."""

    consecutive_failures: int = 0
    last_success_ts: float = 0.0
    last_failure_ts: float = 0.0
    last_error: str = ""
    total_requests: int = 0
    total_failures: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_success(self) -> None:
        with self._lock:
            self.consecutive_failures = 0
            self.last_success_ts = time.time()
            self.total_requests += 1

    def record_failure(self, error: str) -> None:
        with self._lock:
            self.consecutive_failures += 1
            self.last_failure_ts = time.time()
            self.last_error = error
            self.total_requests += 1
            self.total_failures += 1

    @property
    def is_healthy(self) -> bool:
        return False


_health = _HealthState()


def is_available() -> bool:
    """Return ``False``: the upstream provider is permanently retired."""

    return False


def health_status() -> dict[str, Any]:
    """Return compatibility diagnostics without probing TradingView."""

    with _health._lock:
        if _health.total_requests == 0:
            status = "retired"
        elif _health.consecutive_failures >= 3:
            status = "down"
        elif _health.consecutive_failures > 0:
            status = "degraded"
        else:
            status = "healthy"
        return {
            "status": status,
            "consecutive_failures": _health.consecutive_failures,
            "last_success": _health.last_success_ts,
            "last_failure": _health.last_failure_ts,
            "last_error": _health.last_error or "TradingView provider retired",
            "total_requests": _health.total_requests,
            "total_failures": _health.total_failures,
            "uptime_pct": 0.0,
        }


def fetch_tv_headlines(ticker: str, *, max_items: int = 30) -> list[TVHeadline]:
    """Return no data; retained only for legacy callers."""

    del ticker, max_items
    return []


def fetch_tv_multi(
    tickers: list[str],
    *,
    max_per_ticker: int = 15,
    max_total: int = 50,
) -> list[TVHeadline]:
    """Return no data; retained only for legacy callers."""

    del tickers, max_per_ticker, max_total
    return []


def fetch_tv_feed_dicts(
    tickers: list[str],
    *,
    max_per_ticker: int = 10,
    max_total: int = 40,
) -> list[dict[str, Any]]:
    """Return no data; retained only for legacy feed integrations."""

    del tickers, max_per_ticker, max_total
    return []
