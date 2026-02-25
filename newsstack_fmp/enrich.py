"""On-demand URL snippet enrichment for high-impact items.

Only called for items above ``score_enrich_threshold``.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

# Max response body to read (1 MB) — prevents OOM on malicious/huge pages.
_MAX_CONTENT_BYTES = 1_048_576

# Strip HTML tags for safe snippet storage.
_HTML_TAG_RE = re.compile(r"<[^>]+>")


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
        Response body is capped to 1 MB and HTML tags are stripped.
        """
        if not url:
            return {"enriched": False}
        try:
            # Check Content-Length before streaming to avoid OOM.
            r = self.client.get(url)
            raw = r.text or ""
            if len(raw) > _MAX_CONTENT_BYTES:
                raw = raw[:_MAX_CONTENT_BYTES]
            # Strip HTML tags and collapse whitespace for clean text.
            text = _HTML_TAG_RE.sub(" ", raw)
            text = " ".join(text.split())
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
