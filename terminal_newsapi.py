"""NewsAPI.ai (Event Registry) integration for the Streamlit terminal.

Provides:
1. **Breaking Events** — currently breaking news events with article counts,
   sentiment, social scores, and source clustering.
2. **Trending Concepts** — real-time trending entities/topics across global news.
3. **NLP Sentiment** — article-level NLP sentiment (-1 to +1) as a validation
   layer alongside the keyword-based scorer in ``open_prep/news.py``.
4. **Event-clustered news** — group articles per ticker by event to reduce
   noise in Top Movers / Rankings.
5. **Social Score ranking** — most-shared financial articles (proxy for
   retail attention / momentum).

Uses the ``eventregistry`` Python SDK (pip install eventregistry).
API key is read from the ``NEWSAPI_AI_KEY`` environment variable.

Results are cached with configurable TTL to minimise token usage.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

log = logging.getLogger(__name__)

# ── Optional SDK import ──────────────────────────────────────────
try:
    from eventregistry import (  # type: ignore[import-untyped]
        EventRegistry,
        GetTrendingConcepts,
        QueryEvents,
        QueryArticles,
        RequestEventsBreakingEvents,
        RequestEventsInfo,
        RequestArticlesInfo,
        ReturnInfo,
        QueryItems,
        ArticleInfoFlags,
        ConceptInfoFlags,
        SourceInfoFlags,
    )

    _ER_AVAILABLE = True
except ImportError:
    _ER_AVAILABLE = False

_APIKEY_RE = re.compile(r"(apikey|apiKey|token)=[^&\s]+", re.IGNORECASE)


# ── Rich ReturnInfo leveraging all plan features ─────────────────

def _rich_return_info() -> Any:
    """Build a ReturnInfo that requests ALL enriched article fields.

    Leverages the full plan: body, authors, links, videos, concepts,
    categories, sentiment, event clustering, duplicate detection,
    social score, location, extracted dates, source ranking.
    """
    if not _ER_AVAILABLE:
        return None
    return ReturnInfo(
        articleInfo=ArticleInfoFlags(
            title=True,
            body=True,
            url=True,
            dateTimePub=True,
            authors=True,
            links=True,
            videos=True,
            concepts=True,
            categories=True,
            image=True,
            sentiment=True,
            eventUri=True,
            isDuplicate=True,
            duplicateList=True,
            socialScore=True,
            location=True,
            source=True,
            extractedDates=True,
            originalArticle=True,
        ),
        conceptInfo=ConceptInfoFlags(
            label=True,
            type=True,
            uri=True,
            image=True,
            description=True,
        ),
        sourceInfo=SourceInfoFlags(
            title=True,
            uri=True,
            ranking=True,
            location=True,
        ),
    )


def _light_return_info() -> Any:
    """Minimal ReturnInfo for lightweight queries (saves tokens)."""
    if not _ER_AVAILABLE:
        return None
    return ReturnInfo(
        articleInfo=ArticleInfoFlags(
            title=True,
            url=True,
            dateTimePub=True,
            sentiment=True,
            socialScore=True,
            source=True,
        ),
    )


# ── Data classes ─────────────────────────────────────────────────

@dataclass
class BreakingEvent:
    """A single breaking event from NewsAPI.ai."""

    uri: str = ""
    title: str = ""
    summary: str = ""
    event_date: str = ""
    article_count: int = 0
    sentiment: float | None = None
    social_score: int = 0
    concepts: list[dict[str, str]] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    location: str = ""
    images: list[str] = field(default_factory=list)

    @property
    def sentiment_label(self) -> str:
        if self.sentiment is None:
            return "neutral"
        if self.sentiment >= 0.2:
            return "positive"
        if self.sentiment <= -0.2:
            return "negative"
        return "neutral"

    @property
    def sentiment_icon(self) -> str:
        return {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}.get(
            self.sentiment_label, "⚪"
        )


@dataclass
class TrendingConcept:
    """A single trending concept from NewsAPI.ai."""

    uri: str = ""
    label: str = ""
    concept_type: str = ""  # person, org, loc, wiki
    trending_score: float = 0.0
    article_count: int = 0
    image: str = ""

    @property
    def type_icon(self) -> str:
        return {
            "person": "👤",
            "org": "🏢",
            "loc": "📍",
            "wiki": "📄",
        }.get(self.concept_type, "🔹")


@dataclass
class BreakingArticle:
    """An article from a breaking event.

    Includes all enriched fields from the NewsAPI.ai plan:
    body, authors, links from body, videos, entity recognition,
    sentiment, social score, duplicate detection.
    """

    title: str = ""
    body: str = ""
    url: str = ""
    source: str = ""
    date: str = ""
    authors: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    videos: list[str] = field(default_factory=list)
    sentiment: float | None = None
    social_score: int = 0
    image: str = ""
    event_uri: str = ""
    is_duplicate: bool = False
    concepts: list[str] = field(default_factory=list)

    @property
    def sentiment_label(self) -> str:
        if self.sentiment is None:
            return "neutral"
        if self.sentiment >= 0.2:
            return "positive"
        if self.sentiment <= -0.2:
            return "negative"
        return "neutral"

    @property
    def sentiment_icon(self) -> str:
        return {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}.get(
            self.sentiment_label, "⚪"
        )


@dataclass
class SocialArticle:
    """An article ranked by social sharing / virality.

    Includes all enriched fields from the NewsAPI.ai plan:
    body, authors, links, videos, entities, categories,
    sentiment, social score, duplicate detection.
    """

    title: str = ""
    body: str = ""
    url: str = ""
    source: str = ""
    date: str = ""
    authors: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    videos: list[str] = field(default_factory=list)
    sentiment: float | None = None
    social_score: int = 0
    image: str = ""
    concepts: list[str] = field(default_factory=list)  # entity labels
    categories: list[str] = field(default_factory=list)
    event_uri: str = ""
    is_duplicate: bool = False

    @property
    def sentiment_label(self) -> str:
        if self.sentiment is None:
            return "neutral"
        if self.sentiment >= 0.2:
            return "positive"
        if self.sentiment <= -0.2:
            return "negative"
        return "neutral"

    @property
    def sentiment_icon(self) -> str:
        return {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}.get(
            self.sentiment_label, "⚪"
        )


@dataclass
class EventCluster:
    """A group of articles about the same event for a specific symbol."""

    event_uri: str = ""
    title: str = ""
    summary: str = ""
    event_date: str = ""
    article_count: int = 0
    sentiment: float | None = None
    sources: list[str] = field(default_factory=list)
    top_articles: list[dict[str, str]] = field(default_factory=list)  # [{title, url, source}]

    @property
    def sentiment_label(self) -> str:
        if self.sentiment is None:
            return "neutral"
        if self.sentiment >= 0.2:
            return "positive"
        if self.sentiment <= -0.2:
            return "negative"
        return "neutral"

    @property
    def sentiment_icon(self) -> str:
        return {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}.get(
            self.sentiment_label, "⚪"
        )


@dataclass
class NLPSentiment:
    """NLP-computed sentiment for a symbol from NewsAPI.ai articles."""

    symbol: str = ""
    nlp_score: float = 0.0       # -1.0 … +1.0  (average across articles)
    article_count: int = 0       # how many articles contributed
    agreement: float = 0.0       # 0.0-1.0: how consistent sentiment is
    label: str = "neutral"       # positive / neutral / negative

    @property
    def icon(self) -> str:
        return {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}.get(
            self.label, "⚪"
        )


# ── In-memory cache ──────────────────────────────────────────────

_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()
_CACHE_MAX_SIZE = 500  # evict when cache exceeds this
_cache_write_count = 0

_BREAKING_TTL = 120  # 2 minutes
_TRENDING_TTL = 180  # 3 minutes
_SENTIMENT_TTL = 300  # 5 minutes  (NLP enrichment — less time-critical)
_SOCIAL_TTL = 120    # 2 minutes
_EVENT_CLUSTER_TTL = 300  # 5 minutes


def _get_cached(key: str, ttl: float) -> Any:
    """Return cached value if still valid, else None."""
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        ts, val = entry
        if time.time() - ts > ttl:
            del _cache[key]  # evict expired entry on read
            return None
        return val


def _set_cached(key: str, val: Any) -> None:
    global _cache_write_count
    now = time.time()
    with _cache_lock:
        _cache[key] = (now, val)
        _cache_write_count += 1
        # Periodic sweep: evict expired entries every 50 writes or when cache is large
        if _cache_write_count % 50 == 0 or len(_cache) > _CACHE_MAX_SIZE:
            max_ttl = max(_BREAKING_TTL, _TRENDING_TTL, _SENTIMENT_TTL, _SOCIAL_TTL, _EVENT_CLUSTER_TTL)
            expired_keys = [k for k, (ts, _) in _cache.items() if now - ts > max_ttl]
            for k in expired_keys:
                del _cache[k]


# ── EventRegistry singleton ─────────────────────────────────────

_er_instance: Any | None = None
_er_lock = threading.Lock()

# Host for direct HTTP calls (token usage endpoint). SDK uses its own default host.
_ER_HOST = "https://www.newsapi.ai"


def _get_er() -> Any | None:
    """Lazy-init EventRegistry client (thread-safe)."""
    global _er_instance
    if _er_instance is not None:
        return _er_instance
    with _er_lock:
        # Double-check after acquiring lock
        if _er_instance is not None:
            return _er_instance
        if not _ER_AVAILABLE:
            log.warning("eventregistry SDK not installed (pip install eventregistry)")
            return None
        api_key = os.environ.get("NEWSAPI_AI_KEY", "")
        if not api_key:
            log.debug("NEWSAPI_AI_KEY not set — NewsAPI.ai features disabled")
            return None
        try:
            _er_instance = EventRegistry(
                apiKey=api_key,
                allowUseOfArchive=False,  # only last 30 days — saves tokens
            )
            log.info("EventRegistry client initialised")
            return _er_instance
        except Exception as exc:
            log.warning("Failed to initialise EventRegistry: %s", exc)
            return None


def get_token_usage() -> dict[str, int]:
    """Return token usage: {'availableTokens': ..., 'usedTokens': ...}.

    Uses a lightweight HTTP call — does NOT consume tokens.
    """
    api_key = os.environ.get("NEWSAPI_AI_KEY", "")
    if not api_key:
        return {"availableTokens": 0, "usedTokens": 0}
    try:
        import httpx  # noqa: F811 — conditional import
    except ImportError:
        log.debug("httpx not installed — cannot check token usage")
        return {"availableTokens": 0, "usedTokens": 0}
    try:
        r = httpx.get(
            f"{_ER_HOST}/api/v1/usage",
            params={"apiKey": api_key},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict):
                return data
        else:
            log.debug("Token usage HTTP %d", r.status_code)
    except (httpx.HTTPError, OSError, ValueError) as exc:
        log.debug("get_token_usage failed: %s", _APIKEY_RE.sub(r"\1=***", str(exc)))
    return {"availableTokens": 0, "usedTokens": 0}


# ── Breaking Events ──────────────────────────────────────────────

def fetch_breaking_events(
    count: int = 20,
    min_articles: int = 5,
    category: str | None = None,
) -> list[BreakingEvent]:
    """Fetch currently breaking news events.

    Parameters
    ----------
    count : int
        Max events to return (up to 50).
    min_articles : int
        Minimum article count for an event to qualify.
    category : str, optional
        Filter to a specific category URI (e.g. ``"news/Business"``).

    Returns
    -------
    list[BreakingEvent]
    """
    cache_key = f"breaking:{count}:{min_articles}:{category}"
    cached = _get_cached(cache_key, _BREAKING_TTL)
    if cached is not None:
        return cached  # type: ignore

    er = _get_er()
    if er is None:
        return []

    try:
        q = QueryEvents(
            minArticlesInEvent=min_articles,
            **({"categoryUri": category} if category else {}),
        )
        q.setRequestedResult(
            RequestEventsBreakingEvents(
                count=min(count, 50),
                returnInfo=ReturnInfo(
                    eventInfo=ReturnInfo().eventInfo,
                ),
            )
        )
        result = er.execQuery(q)

        # Guard against SDK returning None
        if not isinstance(result, dict):
            log.warning("execQuery returned non-dict for breaking events: %r", type(result))
            _set_cached(cache_key, [])
            return []

        # The SDK returns different structures depending on version:
        # v1: result["breakingEvents"]["results"]
        # older: result["events"]["breakingEvents"]
        events_data = (
            result.get("breakingEvents", {}).get("results", [])
            or result.get("events", {}).get("breakingEvents", [])
        )

        events: list[BreakingEvent] = []
        for ev in events_data:
            # Extract concepts
            concepts = []
            for c in ev.get("concepts", []):
                concepts.append({
                    "label": c.get("label", {}).get("eng", ""),
                    "type": c.get("type", ""),
                    "uri": c.get("uri", ""),
                })

            # Extract categories
            cats = [
                c.get("label", "")
                for c in ev.get("categories", [])
                if c.get("label")
            ]

            # Extract location
            loc = ev.get("location", {})
            loc_label = ""
            if loc:
                loc_label = loc.get("label", {}).get("eng", "")
                country = loc.get("country", {}).get("label", {}).get("eng", "")
                if country and country != loc_label:
                    loc_label = f"{loc_label}, {country}" if loc_label else country

            events.append(BreakingEvent(
                uri=ev.get("uri", ""),
                title=_extract_title(ev),
                summary=ev.get("summary", {}).get("eng", ""),
                event_date=ev.get("eventDate", ""),
                article_count=ev.get("totalArticleCount", 0),
                sentiment=ev.get("sentiment"),
                social_score=ev.get("socialScore", 0),
                concepts=concepts,
                categories=cats,
                location=loc_label,
                images=ev.get("images", []),
            ))

        # Sort by article count desc (most covered = most important)
        events.sort(key=lambda e: e.article_count, reverse=True)
        _set_cached(cache_key, events)
        return events

    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError) as exc:
        log.warning("fetch_breaking_events failed: %s", exc)
        return []
    except Exception as exc:
        log.exception("fetch_breaking_events unexpected error: %s", exc)
        return []


def _extract_title(ev: dict) -> str:
    """Extract best available title from an event dict."""
    title = ev.get("title", {})
    if isinstance(title, dict):
        return title.get("eng", "") or next(iter(title.values()), "")  # type: ignore
    return str(title) if title else ""


# ── Breaking Event Articles ─────────────────────────────────────

def fetch_event_articles(
    event_uri: str,
    count: int = 10,
) -> list[BreakingArticle]:
    """Fetch articles for a specific event URI.

    Parameters
    ----------
    event_uri : str
        The event URI (e.g. ``"eng-1234567"``).
    count : int
        Max articles to return.

    Returns
    -------
    list[BreakingArticle]
    """
    cache_key = f"event_articles:{event_uri}:{count}"
    cached = _get_cached(cache_key, _BREAKING_TTL)
    if cached is not None:
        return cached  # type: ignore

    er = _get_er()
    if er is None:
        return []

    try:
        q = QueryArticles(eventUri=event_uri)
        q.setRequestedResult(
            RequestArticlesInfo(
                count=min(count, 100),
                sortBy="socialScore",
                returnInfo=_rich_return_info() or ReturnInfo(),
            )
        )
        result = er.execQuery(q)

        if not isinstance(result, dict):
            log.warning("execQuery returned non-dict for event articles: %r", type(result))
            _set_cached(cache_key, [])
            return []

        articles_data = (
            result.get("articles", {})
            .get("results", [])
        )

        articles: list[BreakingArticle] = []
        for art in articles_data:
            source = art.get("source", {})
            # Extract concept labels
            _concept_labels: list[str] = []
            for c in art.get("concepts", []):
                lbl = c.get("label", {})
                if isinstance(lbl, dict):
                    lbl = lbl.get("eng", "") or next(iter(lbl.values()), "")
                if lbl:
                    _concept_labels.append(str(lbl))

            # Authors can be dicts with 'name' key or plain strings
            _raw_authors = art.get("authors", []) or []
            _author_names: list[str] = []
            for _au in _raw_authors:
                if isinstance(_au, dict):
                    _author_names.append(_au.get("name", "") or "")
                elif isinstance(_au, str):
                    _author_names.append(_au)
            _author_names = [a for a in _author_names if a]

            articles.append(BreakingArticle(
                title=art.get("title", ""),
                body=art.get("body", "") or "",
                url=art.get("url", ""),
                source=source.get("title", "") if isinstance(source, dict) else str(source),
                date=art.get("dateTimePub", ""),
                authors=_author_names,
                links=art.get("links", []) or [],
                videos=art.get("videos", []) or [],
                sentiment=art.get("sentiment"),
                social_score=int(art.get("socialScore", 0) or 0),
                image=art.get("image", ""),
                event_uri=art.get("eventUri", "") or "",
                is_duplicate=bool(art.get("isDuplicate", False)),
                concepts=_concept_labels[:8],
            ))

        _set_cached(cache_key, articles)
        return articles

    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError) as exc:
        log.warning("fetch_event_articles(%s) failed: %s", event_uri, exc)
        return []
    except Exception as exc:
        log.exception("fetch_event_articles(%s) unexpected error: %s", event_uri, exc)
        return []


# ── Trending Concepts ────────────────────────────────────────────

def fetch_trending_concepts(
    count: int = 20,
    source: str = "news",
    concept_type: str | None = None,
) -> list[TrendingConcept]:
    """Fetch currently trending concepts (entities, topics).

    Parameters
    ----------
    count : int
        Max concepts to return.
    source : str
        ``"news"`` for news-based trends, ``"social"`` for social media.
    concept_type : str, optional
        Filter by type: ``"person"``, ``"org"``, ``"loc"``, ``"wiki"``.

    Returns
    -------
    list[TrendingConcept]
    """
    cache_key = f"trending:{count}:{source}:{concept_type}"
    cached = _get_cached(cache_key, _TRENDING_TTL)
    if cached is not None:
        return cached  # type: ignore

    er = _get_er()
    if er is None:
        return []

    try:
        q = GetTrendingConcepts(
            source=source,
            count=min(count, 50),
            **({"conceptType": concept_type} if concept_type else {}),
        )
        result = er.execQuery(q)

        if result is None:
            log.warning("execQuery returned None for trending concepts")
            _set_cached(cache_key, [])
            return []

        # Response is a list of concept dicts
        concepts_data = result if isinstance(result, list) else (result.get("trendingConcepts", []) if isinstance(result, dict) else [])

        concepts: list[TrendingConcept] = []
        for c in concepts_data:
            # The trending API returns different structures depending on version
            concept_info = c.get("concept", c)  # nested or flat
            label = concept_info.get("label", {})
            if isinstance(label, dict):
                label_str = label.get("eng", "") or next(iter(label.values()), "")
            else:
                label_str = str(label)

            # trendingScore structure: {"news": {"score": 1175.7, "testPopFq": 394, ...}}
            # or could be a plain number in older API versions
            raw_score = c.get("trendingScore", 0)
            _ts = 0.0
            _article_count = 0
            if isinstance(raw_score, dict):
                # Extract from nested structure: {source: {score: N, testPopFq: N}}
                for _src_data in raw_score.values():
                    if isinstance(_src_data, dict):
                        _ts = float(_src_data.get("score", 0) or 0)
                        _article_count = int(_src_data.get("testPopFq", 0) or 0)
                        break
                    elif isinstance(_src_data, (int, float)):
                        _ts = float(_src_data)
            else:
                try:
                    _ts = float(raw_score or 0)
                except (TypeError, ValueError):
                    _ts = 0.0

            # Also check top-level articleCount (older API)
            if _article_count == 0:
                _article_count = int(c.get("articleCount", 0) or 0)

            concepts.append(TrendingConcept(
                uri=concept_info.get("uri", ""),
                label=label_str,
                concept_type=concept_info.get("type", ""),
                trending_score=_ts,
                article_count=_article_count,
                image=concept_info.get("image", ""),
            ))

        # Sort by trending score desc
        concepts.sort(key=lambda c: c.trending_score, reverse=True)
        _set_cached(cache_key, concepts)
        return concepts

    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError) as exc:
        log.warning("fetch_trending_concepts failed: %s", exc)
        return []
    except Exception as exc:
        log.exception("fetch_trending_concepts unexpected error: %s", exc)
        return []


# ── NLP Sentiment for symbols ───────────────────────────────────

def fetch_nlp_sentiment(
    symbols: list[str],
    hours: int = 24,
) -> dict[str, NLPSentiment]:
    """Fetch NLP-computed sentiment for a list of ticker symbols.

    Queries NewsAPI.ai for recent articles mentioning each symbol and
    averages the per-article NLP sentiment.  Returns a dict mapping
    symbol → NLPSentiment.

    This is designed as a **validation layer** alongside the keyword-based
    scorer in ``open_prep/news.py``.  The NLP score is ML-computed by
    NewsAPI.ai's pipeline and captures nuance that keyword matching misses.

    Parameters
    ----------
    symbols : list[str]
        Ticker symbols to score (e.g. ``["AAPL", "TSLA"]``).
    hours : int
        Look-back window in hours (default 24).
    """
    cache_key = f"nlp_sentiment:{','.join(sorted(symbols))}:{hours}"
    cached = _get_cached(cache_key, _SENTIMENT_TTL)
    if cached is not None:
        return cached  # type: ignore

    er = _get_er()
    if er is None:
        return {}

    result: dict[str, NLPSentiment] = {}

    # Batch: query all symbols at once (OR query), then bucket results
    try:
        # Build concept URIs for tickers (EventRegistry convention)
        date_start = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d")

        q = QueryArticles(
            keywords=QueryItems.OR(symbols),
            dateStart=date_start,
            lang="eng",
            isDuplicateFilter="skipDuplicates",
            dataType="news",
        )
        q.setRequestedResult(
            RequestArticlesInfo(
                count=100,  # max articles to analyse
                sortBy="date",
                returnInfo=_light_return_info() or ReturnInfo(),
            )
        )
        api_result = er.execQuery(q)
        if not isinstance(api_result, dict):
            log.warning("execQuery returned non-dict for NLP sentiment: %r", type(api_result))
            return {}
        articles = api_result.get("articles", {}).get("results", [])

        # Bucket articles by symbol using word-boundary matching
        # to avoid false positives (e.g. ticker "A" matching "Amazon")
        sym_set = {s.upper() for s in symbols}
        per_sym: dict[str, list[float]] = {s: [] for s in sym_set}
        # Pre-compile patterns for each symbol.
        # For multi-word labels (e.g. "Donald Trump") use substring match;
        # for short/single-word tickers use word-boundary to avoid false positives.
        sym_patterns: dict[str, re.Pattern[str]] = {}
        for s in sym_set:
            if " " in s or len(s) > 6:
                sym_patterns[s] = re.compile(re.escape(s), re.IGNORECASE)
            else:
                sym_patterns[s] = re.compile(r'\b' + re.escape(s) + r'\b')

        for art in articles:
            sent = art.get("sentiment")
            if sent is None:
                continue
            title_upper = (art.get("title") or "").upper()
            # Match symbols mentioned in title using word boundaries
            for sym, pattern in sym_patterns.items():
                if pattern.search(title_upper):
                    per_sym[sym].append(float(sent))

        for sym in sym_set:
            scores = per_sym.get(sym, [])
            if not scores:
                result[sym] = NLPSentiment(symbol=sym)
                continue
            avg = sum(scores) / len(scores)
            # Agreement = 1 - normalised std dev  (all same sign → high agreement)
            if len(scores) > 1:
                mean = avg
                variance = sum((s - mean) ** 2 for s in scores) / len(scores)
                std = variance ** 0.5
                agreement = max(0.0, 1.0 - std)
            else:
                agreement = 1.0

            if avg >= 0.1:
                label = "positive"
            elif avg <= -0.1:
                label = "negative"
            else:
                label = "neutral"

            result[sym] = NLPSentiment(
                symbol=sym,
                nlp_score=round(avg, 3),
                article_count=len(scores),
                agreement=round(agreement, 2),
                label=label,
            )

        _set_cached(cache_key, result)
        return result

    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError) as exc:
        log.warning("fetch_nlp_sentiment failed: %s", exc)
        return {}
    except Exception as exc:
        log.exception("fetch_nlp_sentiment unexpected error: %s", exc)
        return {}


# ── Event-clustered news for a symbol ────────────────────────────

def fetch_event_clusters(
    symbol: str,
    count: int = 10,
    hours: int = 48,
) -> list[EventCluster]:
    """Fetch news events about a symbol, grouped by event (story).

    Instead of showing individual articles per ticker, this uses
    ``getEvents`` with a keyword filter to group all articles about
    the same story.  Reduces noise in Top Movers / Rankings.

    Parameters
    ----------
    symbol : str
        Ticker symbol (e.g. ``"AAPL"``).
    count : int
        Max events to return.
    hours : int
        Look-back window.

    Returns
    -------
    list[EventCluster]
        Sorted by article_count descending (biggest stories first).
    """
    cache_key = f"event_clusters:{symbol}:{count}:{hours}"
    cached = _get_cached(cache_key, _EVENT_CLUSTER_TTL)
    if cached is not None:
        return cached  # type: ignore

    er = _get_er()
    if er is None:
        return []

    try:
        date_start = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d")

        q = QueryEvents(
            keywords=symbol,
            dateStart=date_start,
            minArticlesInEvent=2,
        )
        q.setRequestedResult(
            RequestEventsInfo(
                count=min(count, 50),
                sortBy="rel",
                returnInfo=ReturnInfo(),
            )
        )
        api_result = er.execQuery(q)

        if not isinstance(api_result, dict):
            log.warning("execQuery returned non-dict for event clusters: %r", type(api_result))
            _set_cached(cache_key, [])
            return []

        events_data = api_result.get("events", {}).get("results", [])

        clusters: list[EventCluster] = []
        for ev in events_data:
            title = _extract_title(ev)
            summary = ev.get("summary", {})
            if isinstance(summary, dict):
                summary_text = summary.get("eng", "") or next(iter(summary.values()), "")
            else:
                summary_text = str(summary) if summary else ""

            # Collect unique source names
            sources: list[str] = []
            top_arts: list[dict[str, str]] = []
            for art in ev.get("stories", ev.get("articles", []))[:5]:
                src = art.get("source", {})
                src_name = src.get("title", "") if isinstance(src, dict) else str(src)
                if src_name and src_name not in sources:
                    sources.append(src_name)
                top_arts.append({
                    "title": art.get("title", ""),
                    "url": art.get("url", ""),
                    "source": src_name,
                })

            clusters.append(EventCluster(
                event_uri=ev.get("uri", ""),
                title=title,
                summary=summary_text[:400],
                event_date=ev.get("eventDate", ""),
                article_count=ev.get("totalArticleCount", 0),
                sentiment=ev.get("sentiment"),
                sources=sources[:5],
                top_articles=top_arts[:3],
            ))

        clusters.sort(key=lambda c: c.article_count, reverse=True)
        _set_cached(cache_key, clusters)
        return clusters

    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError) as exc:
        log.warning("fetch_event_clusters(%s) failed: %s", symbol, exc)
        return []
    except Exception as exc:
        log.exception("fetch_event_clusters(%s) unexpected error: %s", symbol, exc)
        return []


# ── Social Score ranking (most-shared articles) ─────────────────

def fetch_social_ranked_articles(
    count: int = 30,
    category: str = "news/Business",
    hours: int = 24,
) -> list[SocialArticle]:
    """Fetch the most-shared financial news articles.

    Sorted by ``socialScore`` — a proxy for retail attention / momentum.

    Parameters
    ----------
    count : int
        Max articles to return.
    category : str
        NewsAPI.ai category URI.
    hours : int
        Look-back window.

    Returns
    -------
    list[SocialArticle]
    """
    cache_key = f"social_ranked:{count}:{category}:{hours}"
    cached = _get_cached(cache_key, _SOCIAL_TTL)
    if cached is not None:
        return cached  # type: ignore

    er = _get_er()
    if er is None:
        return []

    try:
        date_start = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d")

        q = QueryArticles(
            categoryUri=category,
            dateStart=date_start,
            lang="eng",
            isDuplicateFilter="skipDuplicates",
            dataType="news",
        )
        q.setRequestedResult(
            RequestArticlesInfo(
                count=min(count, 100),
                sortBy="socialScore",
                sortByAsc=False,
                returnInfo=_rich_return_info() or ReturnInfo(),
            )
        )
        api_result = er.execQuery(q)
        if not isinstance(api_result, dict):
            log.warning("execQuery returned non-dict for social articles: %r", type(api_result))
            _set_cached(cache_key, [])
            return []
        articles_raw = api_result.get("articles", {}).get("results", [])

        articles: list[SocialArticle] = []
        for art in articles_raw:
            source = art.get("source", {})
            # Extract concept labels
            concept_labels: list[str] = []
            for c in art.get("concepts", []):
                lbl = c.get("label", {})
                if isinstance(lbl, dict):
                    lbl = lbl.get("eng", "") or next(iter(lbl.values()), "")
                if lbl:
                    concept_labels.append(str(lbl))

            # Extract category labels
            cat_labels: list[str] = []
            for cat in art.get("categories", []):
                cat_lbl = cat.get("label", "") if isinstance(cat, dict) else str(cat)
                if cat_lbl:
                    cat_labels.append(str(cat_lbl))

            # Authors can be dicts with 'name' key or plain strings
            _raw_authors_s = art.get("authors", []) or []
            _author_names_s: list[str] = []
            for _au_s in _raw_authors_s:
                if isinstance(_au_s, dict):
                    _author_names_s.append(_au_s.get("name", "") or "")
                elif isinstance(_au_s, str):
                    _author_names_s.append(_au_s)
            _author_names_s = [a for a in _author_names_s if a]

            articles.append(SocialArticle(
                title=art.get("title", ""),
                body=art.get("body", "") or "",
                url=art.get("url", ""),
                source=source.get("title", "") if isinstance(source, dict) else str(source),
                date=art.get("dateTimePub", ""),
                authors=_author_names_s,
                links=art.get("links", []) or [],
                videos=art.get("videos", []) or [],
                sentiment=art.get("sentiment"),
                social_score=int(art.get("socialScore", 0) or 0),
                image=art.get("image", ""),
                concepts=concept_labels[:8],
                categories=cat_labels[:5],
                event_uri=art.get("eventUri", "") or "",
                is_duplicate=bool(art.get("isDuplicate", False)),
            ))

        # Already sorted by socialScore from the API, but ensure
        articles.sort(key=lambda a: a.social_score, reverse=True)
        _set_cached(cache_key, articles)
        return articles

    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError) as exc:
        log.warning("fetch_social_ranked_articles failed: %s", exc)
        return []
    except Exception as exc:
        log.exception("fetch_social_ranked_articles unexpected error: %s", exc)
        return []


# ── Helpers for Streamlit rendering ──────────────────────────────

def sentiment_badge(val: float | None) -> str:
    """Return a colored badge string for a sentiment value (-1 to +1)."""
    if val is None:
        return "⚪ n/a"
    if not isinstance(val, (int, float)):
        return "⚪ n/a"
    if val >= 0.2:
        return f"🟢 {val:+.2f}"
    if val <= -0.2:
        return f"🔴 {val:+.2f}"
    return f"⚪ {val:+.2f}"


def is_available() -> bool:
    """Check if NewsAPI.ai integration is available (SDK + key)."""
    return _ER_AVAILABLE and bool(os.environ.get("NEWSAPI_AI_KEY", ""))


def has_tokens() -> bool:
    """Check if the API key still has tokens available.

    Uses cached result (60s TTL) to avoid hitting the usage endpoint too often.
    Returns True if usage check fails (assume available rather than blocking).
    """
    cached = _get_cached("_token_check", 60)
    if cached is not None:
        return cached  # type: ignore

    usage = get_token_usage()
    avail = usage.get("availableTokens", 0)
    used = usage.get("usedTokens", 0)
    # If both are 0 it means the HTTP call failed — assume tokens available
    if avail == 0 and used == 0:
        return True
    result = used < avail
    _set_cached("_token_check", result)
    return result


def nlp_vs_keyword_badge(nlp: NLPSentiment | None, kw_label: str, kw_score: float) -> str:
    """Combined badge showing both NLP and keyword sentiment for comparison.

    Returns a Markdown-safe string like:
        🟢 NLP +0.35 · 🔴 KW bearish (-0.40) — ⚠️ DIVERGENCE
    """
    # Keyword side
    kw_icon = {"bullish": "🟢", "bearish": "🔴"}.get(kw_label, "🟡")
    kw_part = f"{kw_icon} KW {kw_label} ({kw_score:+.2f})"

    if nlp is None or nlp.article_count == 0:
        return f"⚪ NLP n/a · {kw_part}"

    nlp_part = f"{nlp.icon} NLP {nlp.nlp_score:+.2f}"

    # Check for divergence (NLP and keyword disagree on direction)
    nlp_dir = 1 if nlp.nlp_score > 0.1 else (-1 if nlp.nlp_score < -0.1 else 0)
    kw_dir = 1 if kw_score > 0.1 else (-1 if kw_score < -0.1 else 0)
    divergence = ""
    if nlp_dir != 0 and kw_dir != 0 and nlp_dir != kw_dir:
        divergence = " — ⚠️ DIVERGENCE"

    return f"{nlp_part} · {kw_part}{divergence}"
