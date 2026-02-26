"""On-demand URL snippet enrichment for high-impact items.

Only called for items above ``score_enrich_threshold``.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Max response body to read (1 MB) — prevents OOM on malicious/huge pages.
_MAX_CONTENT_BYTES = 1_048_576

# Strip HTML tags for safe snippet storage.
_HTML_TAG_RE = re.compile(r"<[^>]+>")

# Block non-HTTPS and internal-network URLs (SSRF protection).
_ALLOWED_SCHEMES = {"https"}
_BLOCKED_HOST_RE = re.compile(
    r"^(localhost|127\.|10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|169\.254\.|0\.|\[::1\]|\[fd|fe80)",
    re.IGNORECASE,
)


class Enricher:
    """Synchronous URL snippet fetcher."""

    def __init__(self) -> None:
        self.client = httpx.Client(
            timeout=3.0,
            follow_redirects=True,
            headers={"User-Agent": "newsstack-fmp/1.0 (enricher)"},
        )

    def fetch_url_snippet(self, url: str | None) -> dict[str, Any]:
        """Fetch URL and return a short text snippet.

        Non-critical — any failure returns ``{"enriched": False}``.
        Response body is capped to 1 MB **during download** via streaming
        so that oversized responses never allocate more memory.
        HTML tags are stripped from the downloaded portion.
        """
        if not url:
            return {"enriched": False}
        try:
            # SSRF guard: only allow HTTPS URLs to public hosts.
            import ipaddress
            import socket
            from urllib.parse import urlparse
            parsed = urlparse(url)
            if parsed.scheme not in _ALLOWED_SCHEMES:
                return {"enriched": False, "error": f"blocked scheme: {parsed.scheme}"}
            host = (parsed.hostname or "").lower()
            if _BLOCKED_HOST_RE.search(host):
                return {"enriched": False, "error": f"blocked host: {host}"}
            # Resolve hostname to detect DNS rebinding / decimal IP bypass
            try:
                infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
                for _fam, _typ, _proto, _canon, addr in infos:
                    ip = ipaddress.ip_address(addr[0])
                    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                        return {"enriched": False, "error": f"blocked resolved IP: {ip}"}
            except (socket.gaierror, ValueError):
                pass  # DNS failure → httpx will also fail → handled below
            with self.client.stream("GET", url) as r:
                # Non-2xx responses are error pages, not article content.
                if r.status_code >= 400:
                    return {
                        "enriched": False,
                        "http_status": r.status_code,
                        "error": f"HTTP {r.status_code}",
                    }
                # Read only up to _MAX_CONTENT_BYTES to avoid OOM.
                chunks: list[bytes] = []
                total = 0
                for chunk in r.iter_bytes(chunk_size=8192):
                    remaining = _MAX_CONTENT_BYTES - total
                    if remaining <= 0:
                        break
                    if len(chunk) > remaining:
                        chunk = chunk[:remaining]
                    chunks.append(chunk)
                    total += len(chunk)
                raw = b"".join(chunks).decode("utf-8", errors="replace")
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
