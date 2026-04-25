"""NewsAPI.ai stubs (service decommissioned).

This module previously provided NewsAPI.ai (Event Registry) integration.
The service subscription has been cancelled.  All functions now return
empty/False values so existing callers continue to work without errors.

.. note::

   This 44-line stub is **not** the active NewsAPI ingestion path. The
   live implementation lives in :file:`scripts/smc_newsapi_ai.py` (~750
   lines) and serves the SMC newsapi feed-state pipeline.

   Audit-grep convention: when triaging "newsapi" references, always
   check both file paths — top-level :file:`terminal_newsapi.py` (this
   stub, decommissioned) **and** :file:`scripts/smc_newsapi_ai.py`
   (active). The pin :file:`tests/test_terminal_newsapi_stub_marker.py`
   enforces the cross-reference stays present.

   Audit reference: ``docs/reviews/2026-04-24-system-review.md`` finding
   **L-1** (Klasse #40, "Decommissioned stub").
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class NLPSentiment:
    symbol: str = ""
    nlp_score: float = 0.0
    article_count: int = 0
    agreement: float = 0.0
    label: str = "neutral"
    icon: str = ""


def newsapi_available() -> bool:
    return False


def fetch_event_clusters(*args: object, **kwargs: object) -> list:
    return []


def fetch_nlp_sentiment(*args: object, **kwargs: object) -> dict:
    return {}


def fetch_trending_concepts(*args: object, **kwargs: object) -> list:
    return []


def fetch_breaking_events(*args: object, **kwargs: object) -> list:
    return []


def fetch_social_ranked_articles(*args: object, **kwargs: object) -> list:
    return []
