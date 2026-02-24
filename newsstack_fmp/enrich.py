"""On-demand URL snippet enrichment for high-impact items.

Only called for items above ``score_enrich_threshold``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class Enricher:
    """Synchronous URL snippet fetcher."""

    def __init__(self) -> None:
        self.client = httpx.Client(
            timeout=3.0,
            follow_redirects=True,
            headers={"User-Agent": "newsstack-fmp/1.0 (enricher)"},
        )

    def fetch_url_snippet(self, url: Optional[str]) -> Dict[str, Any]:
        """Fetch URL and return a short text snippet.

        Non-critical — any failure returns ``{"enriched": False}``.
        """
        if not url:
            return {"enriched": False}
        try:
            r = self.client.get(url)
            text = r.text or ""
            return {
                "enriched": True,
                "url_final": str(r.url),
                "http_status": r.status_code,
                "snippet": text[:700],
            }
        except Exception as exc:
            logger.debug("Enrich failed for %s: %s", url, exc)
            return {"enriched": False, "error": str(exc)}

    def close(self) -> None:
        self.client.close()
