"""CNN equity Fear & Greed index fetcher (free, no API key).

Why this module exists
----------------------
``terminal_bitcoin.fetch_fear_greed`` already wires *crypto* F&G from
``api.alternative.me`` into the Bitcoin tab — but that index is
crypto-only and not relevant for the SMC / Open-Prep equity scoring
pipeline. The FMP ``/stable/fear-and-greed-index`` endpoint was retired
(returned 404 on Ultimate, legacy ``/api/v3`` returns 403 "Legacy
Endpoint"); the dormant ``open_prep/macro.py::get_fear_and_greed_index``
caller and its consumer in ``terminal_bitcoin.fetch_fear_greed`` were
removed in P-6 (2026-04-30; see docs/reviews/2026-04-24-system-review.md).

This module fetches CNN's public dataviz endpoint (the one that powers
the cnn.com/markets/fear-and-greed page). The endpoint is unauthenticated
but does require a browser-like ``User-Agent`` — without it the CDN
returns 403.

Returned shape (or ``None`` on any failure — fail-soft, the caller
treats sentiment as missing rather than aborting the pipeline):

    {
        "value": 72.0,            # 0..100, rounded
        "label": "Greed",         # CNN-style bucket
        "raw_label": "greed",     # CNN endpoint's own rating string
        "source": "cnn",
        "fetched_at": "2026-04-27T20:30:11+00:00",
    }

The bucket labels follow the same convention as
``terminal_bitcoin.classify_fear_greed`` so dashboards can share a
single colour mapping.
"""

from __future__ import annotations

import json
import logging
import ssl
import urllib.error
from datetime import UTC, datetime
from typing import Any
from urllib.request import Request, urlopen

try:
    import certifi
except Exception:  # pragma: no cover
    certifi = None

logger = logging.getLogger("open_prep.sentiment_fng")

# Public dataviz endpoint that powers cnn.com/markets/fear-and-greed.
# Documented in many community projects (see e.g.
# https://github.com/whit3rabbit/fear-and-greed-index). The leading path
# segment is the most-recent-date ISO; CNN ignores it and returns the
# current snapshot, so we just send "graphdata" with no suffix.
_CNN_FNG_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"

# CNN's CDN returns 403 without a browser-like UA. We send a generic
# Mozilla string so we don't pretend to be a specific browser version
# that may later be blocked.
_USER_AGENT = "Mozilla/5.0 (compatible; skippAlgo-OpenPrep/1.0)"

_DEFAULT_TIMEOUT_SECONDS = 5.0


def _bucket_label(value: float) -> str:
    """Return the canonical 5-bucket label (mirrors terminal_bitcoin)."""

    if value <= 24:
        return "Extreme Fear"
    if value <= 44:
        return "Fear"
    if value <= 54:
        return "Neutral"
    if value <= 74:
        return "Greed"
    return "Extreme Greed"


def _ssl_context() -> ssl.SSLContext:
    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


def fetch_cnn_equity_fear_greed(
    *, timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
) -> dict[str, Any] | None:
    """Fetch the current CNN equity F&G snapshot.

    Fail-soft: returns ``None`` on any network / parse error. Callers
    must treat ``None`` as "sentiment missing" and proceed without
    aborting (same contract as
    ``terminal_bitcoin.fetch_fear_greed``).
    """

    request = Request(_CNN_FNG_URL, headers={"User-Agent": _USER_AGENT})
    try:
        with urlopen(request, timeout=timeout_seconds, context=_ssl_context()) as response:
            payload = response.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        logger.info("CNN F&G fetch failed (network): %s", exc)
        return None
    except Exception as exc:  # pragma: no cover - defensive: unexpected SSL/proxy issues
        logger.warning("CNN F&G fetch failed (unexpected): %s", exc)
        return None

    try:
        data = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        logger.warning("CNN F&G payload not valid JSON: %s", exc)
        return None

    snapshot = data.get("fear_and_greed") if isinstance(data, dict) else None
    if not isinstance(snapshot, dict):
        logger.warning("CNN F&G payload missing 'fear_and_greed' object")
        return None

    raw_score = snapshot.get("score")
    if not isinstance(raw_score, (int, float)) or isinstance(raw_score, bool):
        logger.warning("CNN F&G payload missing numeric 'score'")
        return None

    value = round(float(raw_score), 2)
    if value < 0 or value > 100:
        logger.warning("CNN F&G score out of expected 0..100 range: %s", value)
        return None

    raw_label = snapshot.get("rating") if isinstance(snapshot.get("rating"), str) else ""
    return {
        "value": value,
        "label": _bucket_label(value),
        "raw_label": raw_label,
        "source": "cnn",
        "fetched_at": datetime.now(UTC).isoformat(),
    }
