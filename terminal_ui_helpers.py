"""Pure helper functions extracted from streamlit_terminal.py.

Every function here is free of Streamlit / session-state side-effects
and can be tested in regular pytest without launching a Streamlit app.
"""

from __future__ import annotations

import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from collections import defaultdict
from typing import Any

# ── Icon / colour maps ──────────────────────────────────────────

SENTIMENT_COLORS: dict[str, str] = {
    "bullish": "🟢",
    "bearish": "🔴",
    "neutral": "🟡",
}

MATERIALITY_COLORS: dict[str, str] = {
    "HIGH": "🔴",
    "MEDIUM": "🟠",
    "LOW": "⚪",
}

RECENCY_COLORS: dict[str, str] = {
    "ULTRA_FRESH": "🔥",
    "FRESH": "🟢",
    "WARM": "🟡",
    "AGING": "🟠",
    "STALE": "⚫",
    "UNKNOWN": "❓",
}

MATERIALITY_EMOJI = MATERIALITY_COLORS

RECENCY_EMOJI = RECENCY_COLORS


# ── Feed pruning ────────────────────────────────────────────────


def prune_stale_items(
    feed: list[dict[str, Any]],
    max_age_s: float,
) -> list[dict[str, Any]]:
    """Drop items whose ``published_ts`` is older than *max_age_s* seconds.

    Pure version — caller supplies the max-age explicitly.
    """
    if max_age_s <= 0:
        return feed
    cutoff = time.time() - max_age_s
    return [
        d for d in feed
        if (d.get("published_ts") or 0) >= cutoff
        or (d.get("published_ts") or 0) == 0  # keep items with missing ts
    ]


# ── Feed filtering (Live Feed tab) ─────────────────────────────


def filter_feed(
    feed: list[dict[str, Any]],
    *,
    search_q: str = "",
    sentiment: str = "all",
    category: str = "all",
    from_epoch: float = 0.0,
    to_epoch: float = float("inf"),
) -> list[dict[str, Any]]:
    """Apply text-search, sentiment, category, and date-range filters.

    Returns the filtered list **sorted by score descending**.
    """
    filtered = list(feed)

    if search_q:
        q_lower = search_q.lower()
        filtered = [
            d for d in filtered
            if q_lower in (d.get("headline", "") or "").lower()
            or q_lower in (d.get("ticker", "") or "").lower()
            or q_lower in (d.get("snippet", "") or "").lower()
        ]

    if sentiment != "all":
        filtered = [d for d in filtered if d.get("sentiment_label") == sentiment]

    if category != "all":
        filtered = [d for d in filtered if d.get("category") == category]

    filtered = [
        d for d in filtered
        if from_epoch <= (d.get("published_ts") or 0) <= to_epoch
        or (d.get("published_ts") or 0) == 0  # keep items with missing ts
    ]

    # Remove duplicate feed rows (same ticker + same canonical article)
    filtered = dedup_feed_items(filtered)

    # Score descending, then published_ts ascending as tiebreaker
    filtered.sort(key=lambda d: (-d.get("news_score", 0), d.get("published_ts", 0)))
    return filtered


# ── Formatting helpers ──────────────────────────────────────────


def format_score_badge(score: float, sentiment: str = "") -> str:
    """Return a Streamlit-markdown score badge with colour coding.

    Colour encodes **both** impact level and sentiment direction:

    * score ≥ 0.80  → :green: (bullish) / :red: (bearish) / :gray: (neutral/unknown)  **bold**
    * score ≥ 0.50  → :yellow: (bullish) / :orange: (bearish) / :gray: (neutral/unknown)
    * score < 0.50  → plain text

    A directional prefix is prepended: ``+`` bullish, ``−`` bearish, ``n`` neutral.
    """
    _DIR = {"bullish": "+", "bearish": "−", "neutral": "n"}
    sent = sentiment.lower() if sentiment else ""
    prefix = _DIR.get(sent, "")
    if score >= 0.80:
        if sent == "bullish":
            return f":green[**{prefix}{score:.2f}**]"
        if sent == "bearish":
            return f":red[**{prefix}{score:.2f}**]"
        return f":gray[**{prefix}{score:.2f}**]"
    if score >= 0.50:
        if sent == "bullish":
            return f":yellow[{prefix}{score:.2f}]"
        if sent == "bearish":
            return f":orange[{prefix}{score:.2f}]"
        return f":gray[{prefix}{score:.2f}]"
    return f"{prefix}{score:.2f}"


def format_age_string(published_ts: float | None, *, now: float | None = None) -> str:
    """Human-readable age string in ``d:hh:mm:ss`` format, or ``?``."""
    if published_ts is None or published_ts <= 0:
        return "?"
    if now is None:
        now = time.time()
    delta = max(now - published_ts, 0.0)
    total_s = int(delta)
    days, rem = divmod(total_s, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    if days > 0:
        return f"{days}:{hours:02d}:{mins:02d}:{secs:02d}"
    return f"0:{hours:02d}:{mins:02d}:{secs:02d}"


def provider_icon(provider: str) -> str:
    """Return an emoji icon for the news provider."""
    if "benzinga" in provider:
        return "🅱️"
    if "fmp" in provider:
        return "📊"
    return ""


def safe_markdown_text(text: str) -> str:
    """Escape square brackets for safe Streamlit markdown rendering."""
    return text.replace("[", "\\[").replace("]", "\\]")


def safe_url(url: str) -> str:
    """Validate scheme and escape parentheses for safe markdown/HTML link rendering.

    Only ``http`` and ``https`` schemes are allowed; anything else (e.g.
    ``javascript:``, ``data:``, ``vbscript:``) is rejected and returns ``""``.
    """
    if not url:
        return ""
    stripped = url.strip()
    # Only allow http(s) — reject javascript:, data:, vbscript: etc.
    if not stripped.lower().startswith(("http://", "https://")):
        return ""
    return stripped.replace("(", "%28").replace(")", "%29")


# ── Article dedup helpers ───────────────────────────────────────

_TRACKING_QUERY_PARAMS: set[str] = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
}


def canonical_article_key(d: dict[str, Any]) -> str:
    """Return a stable identity key for an article-like feed item.

    Preference order:
    1) normalized URL (without tracking params)
    2) normalized (ticker + headline + hour bucket)
    3) item_id + ticker
    """
    ticker = str(d.get("ticker") or "").strip().upper()
    raw_url = str(d.get("url") or "").strip()
    if raw_url.lower().startswith(("http://", "https://")):
        try:
            parts = urlsplit(raw_url)
            clean_query = urlencode(
                [
                    (k, v)
                    for k, v in parse_qsl(parts.query, keep_blank_values=True)
                    if k.lower() not in _TRACKING_QUERY_PARAMS
                ],
                doseq=True,
            )
            path = parts.path.rstrip("/") or "/"
            normalized = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, clean_query, ""))
            return f"url:{normalized}"
        except Exception:
            return f"url:{raw_url.lower()}"

    headline = " ".join(str(d.get("headline") or "").strip().lower().split())
    if headline:
        published_ts = d.get("published_ts")
        hour_bucket = ""
        if isinstance(published_ts, (int, float)) and published_ts > 0:
            hour_bucket = str(int(published_ts) // 3600)
        return f"hl:{ticker}:{headline}:{hour_bucket}"

    item_id = str(d.get("item_id") or "").strip()
    if item_id:
        return f"id:{item_id}:{ticker}"
    return f"fallback:{ticker}"


def dedup_articles(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate article items while preserving original order."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for d in items:
        key = canonical_article_key(d)
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out

def feed_item_identity_key(d: dict[str, Any]) -> str:
    """Identity key for feed rows that preserves per-ticker visibility.

    Unlike ``canonical_article_key``, this always namespaces by ticker so
    one multi-ticker article can still appear once per ticker.
    """
    ticker = str(d.get("ticker") or "").strip().upper()
    return f"{ticker}:{canonical_article_key(d)}"

def dedup_feed_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate feed rows while preserving original order."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for d in items:
        key = feed_item_identity_key(d)
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


# ── Highlight helpers ───────────────────────────────────────────


def highlight_fresh_row(age_min: Any, n_cols: int) -> list[str]:
    """Return CSS styles for a DataFrame row.

    If *age_min* < 20, all *n_cols* cells are coloured orange.
    """
    if isinstance(age_min, (int, float)) and age_min < 20:
        return ["color: #FF8C00"] * n_cols
    return [""] * n_cols


def enrich_materiality(value: str) -> str:
    """Prepend emoji to a materiality label: ``HIGH`` → ``🔴 HIGH``."""
    icon = MATERIALITY_EMOJI.get(value, "")
    return f"{icon} {value}" if icon else value


def enrich_recency(value: str) -> str:
    """Prepend emoji to a recency bucket: ``FRESH`` → ``🟢 FRESH``."""
    icon = RECENCY_EMOJI.get(value, "")
    return f"{icon} {value}" if icon else value


# ── Stats helpers ───────────────────────────────────────────────


def compute_feed_stats(feed: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate headline stats from the feed.

    Returns a dict with keys:
    ``count``, ``unique_tickers``, ``actionable``, ``high_materiality``,
    ``avg_relevance``, ``newest_age_min``.
    """
    unique_tickers = len(set(d["ticker"] for d in feed if d.get("ticker") != "MARKET"))
    actionable = sum(1 for d in feed if d.get("is_actionable"))
    high_mat = sum(1 for d in feed if d.get("materiality") == "HIGH")
    total_rel = sum(d.get("relevance", 0) for d in feed)
    avg_rel = total_rel / max(1, len(feed))

    newest_ts = max((d.get("published_ts") or 0 for d in feed), default=0)
    newest_age_min = (time.time() - newest_ts) / 60 if newest_ts > 0 else 0

    return {
        "count": len(feed),
        "unique_tickers": unique_tickers,
        "actionable": actionable,
        "high_materiality": high_mat,
        "avg_relevance": avg_rel,
        "newest_age_min": newest_age_min,
    }


# ── Top Movers ──────────────────────────────────────────────────


def compute_top_movers(
    feed: list[dict[str, Any]],
    *,
    window_s: float = 1800,
    now: float | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Best-scored item per ticker within the last *window_s* seconds.

    Returns a list sorted by score descending, capped to *limit*.
    """
    if now is None:
        now = time.time()
    recent = [d for d in feed if (now - (d.get("published_ts") or 0)) < window_s]

    best_by_tk: dict[str, dict[str, Any]] = {}
    for d in recent:
        tk = d.get("ticker", "?")
        if tk == "MARKET":
            continue
        prev = best_by_tk.get(tk)
        if prev is None or d.get("news_score", 0) > prev.get("news_score", 0):
            best_by_tk[tk] = d

    sorted_movers = sorted(
        best_by_tk.values(),
        key=lambda x: (-x.get("news_score", 0), x.get("ticker", "")),
    )
    return sorted_movers[:limit]


# ── Segment aggregation ────────────────────────────────────────

# Channels that are too generic to be useful as segments.
_SKIP_CHANNELS: set[str] = {"", "news", "general", "markets", "trading", "top stories"}


def aggregate_segments(
    feed: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build per-segment (news channel) aggregation rows.

    Each returned dict contains:
    ``segment``, ``articles``, ``tickers``, ``avg_score``, ``sentiment``,
    ``bull``, ``bear``, ``neut``, ``net_sent``, ``_ticker_map``.

    Sorted by article count descending.
    """
    seg_items: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for d in feed:
        tk = d.get("ticker", "?")
        if tk == "MARKET":
            continue
        chs = d.get("channels", [])
        if not chs:
            chs = [d.get("category", "other")]
        for ch in chs:
            ch_clean = ch.strip().title() if isinstance(ch, str) else str(ch)
            if ch_clean.lower() not in _SKIP_CHANNELS:
                seg_items[ch_clean].append(d)

    seg_rows: list[dict[str, Any]] = []
    for seg_name, items_list in seg_items.items():
        unique_items = dedup_articles(
            sorted(items_list, key=lambda d: d.get("news_score", 0), reverse=True)
        )
        tickers_in_seg: dict[str, dict[str, Any]] = {}
        bull = bear = neut = 0
        total_score = 0.0
        for d in unique_items:
            tk = d.get("ticker", "?")
            s = d.get("news_score", 0)
            total_score += s
            sent = d.get("sentiment_label", "neutral")
            if sent == "bullish":
                bull += 1
            elif sent == "bearish":
                bear += 1
            else:
                neut += 1
            prev = tickers_in_seg.get(tk)
            if prev is None or s > prev.get("news_score", 0):
                tickers_in_seg[tk] = d

        n_articles = len(unique_items)
        avg_score = total_score / n_articles if n_articles else 0
        net_sent = bull - bear
        sent_icon = "🟢" if net_sent > 0 else ("🔴" if net_sent < 0 else "🟡")

        seg_rows.append({
            "segment": seg_name,
            "articles": n_articles,
            "tickers": len(tickers_in_seg),
            "avg_score": round(avg_score, 4),
            "sentiment": sent_icon,
            "bull": bull,
            "bear": bear,
            "neut": neut,
            "net_sent": net_sent,
            "_ticker_map": tickers_in_seg,
            "_items": unique_items,
        })

    seg_rows.sort(key=lambda r: r["articles"], reverse=True)
    return seg_rows


def split_segments_by_sentiment(
    seg_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Split segment rows into (bullish, neutral, bearish) lists."""
    leading = [r for r in seg_rows if r["net_sent"] > 0]
    neutral = [r for r in seg_rows if r["net_sent"] == 0]
    lagging = [r for r in seg_rows if r["net_sent"] < 0]
    return leading, neutral, lagging


def build_segment_summary_rows(
    seg_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build display-friendly summary dicts for the segment overview table."""
    return [
        {
            "Segment": r["segment"],
            "Articles": r["articles"],
            "Tickers": r["tickers"],
            "Avg Score": r["avg_score"],
            "Sentiment": r["sentiment"],
            "🟢": r["bull"],
            "🔴": r["bear"],
            "🟡": r["neut"],
        }
        for r in seg_rows
    ]


# ── Heatmap data ────────────────────────────────────────────────


def build_heatmap_data(
    feed: list[dict[str, Any]],
    sector_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Build treemap leaf rows grouped by sector.

    When *sector_map* is provided (ticker → GICS sector), groups items
    by GICS sector.  Otherwise falls back to news article channels.

    Each row: ``sector``, ``ticker``, ``score``, ``sentiment``,
    ``net_sent``, ``articles``.
    """
    seg_data: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for d in feed:
        tk = d.get("ticker", "?")
        if tk == "MARKET":
            continue

        if sector_map is not None:
            # Use GICS sector lookup
            sector = sector_map.get(tk.upper(), "Other")
            seg_data[sector].append(d)
        else:
            # Fallback: group by news channels
            chs = d.get("channels", [])
            if not chs:
                chs = [d.get("category", "other")]
            for ch in chs:
                ch_clean = ch.strip().title() if isinstance(ch, str) else str(ch)
                if ch_clean.lower() not in _SKIP_CHANNELS:
                    seg_data[ch_clean].append(d)

    hm_data: list[dict[str, Any]] = []
    for seg_name, items_list in seg_data.items():
        tickers_seen: dict[str, dict[str, Any]] = {}
        bull_count = bear_count = 0
        for d in items_list:
            tk = d.get("ticker", "?")
            s = d.get("news_score", 0)
            sent = d.get("sentiment_label", "neutral")
            if sent == "bullish":
                bull_count += 1
            elif sent == "bearish":
                bear_count += 1
            prev = tickers_seen.get(tk)
            if prev is None or s > prev.get("news_score", 0):
                tickers_seen[tk] = d

        tk_counts: dict[str, int] = defaultdict(int)
        for _d in items_list:
            tk_counts[_d.get("ticker", "?")] += 1

        net = bull_count - bear_count
        for tk, d in tickers_seen.items():
            hm_data.append({
                "sector": seg_name,
                "ticker": tk,
                "score": d.get("news_score", 0),
                "sentiment": d.get("sentiment_label", "neutral"),
                "net_sent": net,
                "articles": tk_counts.get(tk, 0),
            })

    return hm_data


# ── Alert matching (pure rule evaluation) ───────────────────────


def match_alert_rule(
    rule: dict[str, Any],
    *,
    ticker: str,
    news_score: float,
    sentiment_label: str,
    materiality: str,
    category: str,
) -> bool:
    """Return True if the item matches the given alert rule.

    This is the pure matching logic extracted from ``_evaluate_alerts``.
    """
    tk_match = rule["ticker"] in ("*", ticker)
    if not tk_match:
        return False

    cond = rule.get("condition", "")
    if cond == "score >= threshold" and news_score >= rule.get("threshold", 0.80):
        return True
    if cond == "sentiment == bearish" and sentiment_label == "bearish":
        return True
    if cond == "sentiment == bullish" and sentiment_label == "bullish":
        return True
    if cond == "materiality == HIGH" and materiality == "HIGH":
        return True
    return bool(cond == "category matches" and category == rule.get("category", ""))


# ── JSONL dedup key ─────────────────────────────────────────────


def item_dedup_key(d: dict[str, Any]) -> str:
    """Canonical dedup key for a feed item: ``{item_id}:{ticker}``."""
    return f"{d.get('item_id', '')}:{d.get('ticker', '')}"


def dedup_merge(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge *incoming* items into *existing*, skipping duplicates.

    Returns the combined list (incoming first, then existing).  Does NOT
    sort — caller decides ordering.
    """
    existing_keys = {item_dedup_key(d) for d in existing}
    new_items = [d for d in incoming if item_dedup_key(d) not in existing_keys]
    return new_items + existing


# ── Rankings enrichment ─────────────────────────────────────────


def enrich_rank_rows(rank_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add emoji prefixes to materiality and recency fields in-place.

    Returns the same list for chaining.
    """
    for r in rank_rows:
        r["materiality"] = enrich_materiality(r.get("materiality", ""))
        r["recency"] = enrich_recency(r.get("recency", ""))
    return rank_rows
