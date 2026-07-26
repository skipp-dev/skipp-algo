"""Cross-source news event matcher.

The shadow-latency harness joins Benzinga WS↔REST by a shared ``item_id``. But
comparing Benzinga against *other* providers — TradingView headlines (Reuters /
Dow Jones), or X/Twitter — has no shared id: each provider assigns its own. To
place a ``t_tv`` / ``t_x`` timestamp next to ``t_ws`` / ``t_rest`` for the SAME
real-world event we must match on content, not id.

This module is the shared matcher for both:
  * the **historical content-lead pre-study** (``scripts/bz_tv_lead_study.py``):
    does TradingView's Reuters/DJ feed carry market-movers with an earlier
    *published* time (or carry ones Benzinga misses)?  — answerable offline, €0.
  * the later **live** wiring: populate ``t_tv`` / ``t_x`` in the recorder by
    matching each foreign item to the Benzinga event it corresponds to.

Matching rule: two items are the same event iff they (1) share ≥1 ticker,
(2) were published within ``time_window_s``, and (3) have headline similarity
≥ ``min_headline_sim``. Clustering is greedy single-linkage over time order.

Pure and side-effect free — the data fetch lives in the study script.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

_CASHTAG = re.compile(r"\$[a-z]{1,6}\b")
_NONWORD = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")

# Tiny stopword set — enough to stop trivial glue words from inflating the
# token-Jaccard similarity without needing an NLP dependency.
_STOP = frozenset(
    {"a", "an", "the", "on", "in", "of", "to", "for", "and", "as", "at",
     "its", "it", "over", "after", "amid", "with", "is", "are", "be"}
)


def normalize_headline(headline: str) -> str:
    """Lowercase, drop cashtags and punctuation, collapse whitespace."""
    s = headline.lower()
    s = _CASHTAG.sub(" ", s)
    s = _NONWORD.sub(" ", s)
    return _WS.sub(" ", s).strip()


def _tokens(headline: str) -> set[str]:
    return {t for t in normalize_headline(headline).split() if t and t not in _STOP}


def headline_similarity(a: str, b: str) -> float:
    """Similarity in ``0.0..1.0``: max of char-ratio and token-Jaccard.

    ``difflib`` char ratio catches near-verbatim relays; token Jaccard catches
    reordered paraphrases. Taking the max makes the score robust to either.
    """
    na, nb = normalize_headline(a), normalize_headline(b)
    if not na or not nb:
        return 0.0
    char_ratio = difflib.SequenceMatcher(None, na, nb).ratio()
    ta, tb = _tokens(a), _tokens(b)
    jaccard = (len(ta & tb) / len(ta | tb)) if (ta or tb) else 0.0
    return max(char_ratio, jaccard)


@dataclass
class SourceItem:
    """One news item from one provider."""

    source: str  # "benzinga" | "tv" | "x" | ...
    item_id: str
    published_ts: float
    headline: str
    tickers: list[str] = field(default_factory=list)
    arrival_ts: float | None = None  # local receipt time (live); None historically

    def ticker_set(self) -> set[str]:
        return {t.strip().upper() for t in self.tickers if t and t.strip()}


def items_match(
    a: SourceItem, b: SourceItem, *, time_window_s: float, min_headline_sim: float
) -> bool:
    """True iff *a* and *b* are plausibly the same real-world event."""
    if not (a.ticker_set() & b.ticker_set()):
        return False
    if abs(a.published_ts - b.published_ts) > time_window_s:
        return False
    return headline_similarity(a.headline, b.headline) >= min_headline_sim


@dataclass
class MatchedEvent:
    """One real-world event, with the earliest item seen per source."""

    tickers: list[str]
    per_source: dict[str, SourceItem] = field(default_factory=dict)

    def _add(self, item: SourceItem) -> None:
        cur = self.per_source.get(item.source)
        if cur is None or item.published_ts < cur.published_ts:
            self.per_source[item.source] = item
        # union tickers, preserving order of first appearance
        for t in item.ticker_set():
            if t not in self.tickers:
                self.tickers.append(t)

    @property
    def representative_headline(self) -> str:
        earliest = min(self.per_source.values(), key=lambda i: i.published_ts)
        return earliest.headline

    def timestamp(self, source: str, *, prefer_arrival: bool = True) -> float | None:
        """Timestamp for *source*: arrival time if present, else published."""
        item = self.per_source.get(source)
        if item is None:
            return None
        if prefer_arrival and item.arrival_ts is not None:
            return item.arrival_ts
        return item.published_ts


def match_events(
    items: list[SourceItem],
    *,
    time_window_s: float = 120.0,
    min_headline_sim: float = 0.6,
) -> list[MatchedEvent]:
    """Greedy single-linkage clustering of items into events.

    Items are processed in published-time order; each item joins the first
    existing cluster containing a member it matches, otherwise it starts a new
    cluster. Within a cluster the earliest item per source is retained.
    """
    clusters: list[tuple[MatchedEvent, list[SourceItem]]] = []
    for item in sorted(items, key=lambda i: i.published_ts):
        placed = False
        for event, members in clusters:
            if any(
                items_match(item, m, time_window_s=time_window_s,
                            min_headline_sim=min_headline_sim)
                for m in members
            ):
                event._add(item)
                members.append(item)
                placed = True
                break
        if not placed:
            ev = MatchedEvent(tickers=[])
            ev._add(item)
            clusters.append((ev, [item]))
    return [event for event, _ in clusters]
