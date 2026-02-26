"""Unified internal schema shared across all news providers.

Every adapter (FMP, Benzinga REST, Benzinga WS, …) normalises its raw
payload into a ``NewsItem`` before entering the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class NewsItem:
    """Provider-agnostic news record."""

    provider: str  # "fmp_stock_latest" | "fmp_press_latest" | "benzinga_rest" | "benzinga_ws" | …
    item_id: str  # provider-unique stable identifier
    published_ts: float  # epoch seconds
    updated_ts: float  # epoch seconds (>= published_ts when known)
    headline: str
    snippet: str
    tickers: list[str]
    url: str | None
    source: str  # publisher / site / author
    raw: dict[str, Any] = field(default_factory=dict)

    # ── Convenience ─────────────────────────────────────────────

    @property
    def is_valid(self) -> bool:
        """Minimal sanity check before pipeline accepts the item."""
        return bool(self.item_id and self.headline)
