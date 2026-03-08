"""NewsAPI.ai stubs (service decommissioned).

This module previously provided NewsAPI.ai (Event Registry) integration.
The service subscription has been cancelled.  All functions now return
empty/False values so existing callers continue to work without errors.
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
