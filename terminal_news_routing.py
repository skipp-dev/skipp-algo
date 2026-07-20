"""Deterministic primary/fallback routing for Terminal news ingestion."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

DirectPoll = Callable[
    [],
    tuple[list[Any], dict[str, str], dict[str, int]],
]


class NewsSourceUnavailableError(RuntimeError):
    """All configured news sources failed without exposing credential text."""


@dataclass(frozen=True)
class NewsPollResult:
    items: list[Any]
    provider_cursors: dict[str, str]
    provider_counts: dict[str, int]
    source: str
    fallback_from: str = ""


def poll_news_sources(
    *,
    producer_feed: Any | None,
    direct_poll: DirectPoll,
    direct_available: bool,
    direct_primary: bool,
) -> NewsPollResult:
    """Poll exactly one successful source, using the other only on failure.

    An empty successful batch is still success. This prevents the fallback
    path from turning normal snapshot deduplication into duplicate provider
    requests.
    """
    configured: dict[str, bool] = {
        "producer": producer_feed is not None,
        "direct": direct_available,
    }
    order = ("direct", "producer") if direct_primary else ("producer", "direct")
    available = [source for source in order if configured[source]]
    if not available:
        raise NewsSourceUnavailableError("no news source is configured")

    failures: list[tuple[str, str]] = []
    for source in available:
        try:
            if source == "producer":
                items, cursor = producer_feed.fetch()
                result = NewsPollResult(
                    items=items,
                    provider_cursors={"producer": cursor},
                    provider_counts={"producer": len(items)},
                    source="producer",
                )
            else:
                items, cursors, counts = direct_poll()
                result = NewsPollResult(
                    items=items,
                    provider_cursors=dict(cursors),
                    provider_counts=dict(counts),
                    source="direct",
                )
        except Exception as exc:
            failures.append((source, type(exc).__name__))
            continue

        if failures:
            return NewsPollResult(
                items=result.items,
                provider_cursors=result.provider_cursors,
                provider_counts=result.provider_counts,
                source=result.source,
                fallback_from=failures[0][0],
            )
        return result

    detail = ", ".join(f"{source}:{error_type}" for source, error_type in failures)
    raise NewsSourceUnavailableError(f"all configured news sources failed ({detail})") from None
