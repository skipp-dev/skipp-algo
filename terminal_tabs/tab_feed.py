"""Tab: Live Feed — searchable, filterable news feed with NLP enrichment."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import streamlit as st

from open_prep.playbook import classify_recency as _classify_recency
from terminal_newsapi import (
    NLPSentiment,
    fetch_nlp_sentiment,
    is_available as newsapi_available,
)
from terminal_ui_helpers import (
    RECENCY_COLORS,
    SENTIMENT_COLORS,
    filter_feed,
    format_age_string,
    format_score_badge,
    provider_icon,
    safe_markdown_text,
    safe_url,
)


def render(feed: list[dict[str, Any]], *, current_session: str) -> None:
    """Render the Live Feed tab."""
    # Search + filter controls
    fcol1, fcol2, fcol3 = st.columns([3, 2, 2])
    with fcol1:
        search_q = st.text_input(
            "🔍 Search headlines", value="", placeholder="e.g. AAPL earnings",
            key="feed_search",
        )
    with fcol2:
        filter_sentiment = st.selectbox(
            "Sentiment", ["all", "bullish", "bearish", "neutral"],
            key="feed_sent",
        )
    with fcol3:
        filter_category = st.selectbox(
            "Category",
            ["all", *sorted({d.get("category", "other") for d in feed})],
            key="feed_cat",
        )

    # Date range filter
    dcol1, dcol2 = st.columns(2)
    with dcol1:
        date_from = st.date_input(
            "From",
            value=datetime.now(UTC).date() - timedelta(days=7),
            key="feed_date_from",
        )
    with dcol2:
        date_to = st.date_input(
            "To", value=datetime.now(UTC).date(), key="feed_date_to",
        )

    # Apply filters
    from_epoch = datetime.combine(date_from, datetime.min.time(), tzinfo=UTC).timestamp()
    to_epoch = datetime.combine(date_to, datetime.max.time(), tzinfo=UTC).timestamp()
    filtered = filter_feed(
        feed,
        search_q=search_q,
        sentiment=filter_sentiment,
        category=filter_category,
        from_epoch=from_epoch,
        to_epoch=to_epoch,
    )

    st.caption(f"Showing {len(filtered)} of {len(feed)} items")

    # NLP Sentiment enrichment (NewsAPI.ai)
    feed_nlp: dict[str, NLPSentiment] = {}
    if newsapi_available():
        tickers = list({
            d.get("ticker", "").upper()
            for d in filtered[:50]
            if d.get("ticker") and d.get("ticker") != "MARKET"
        })
        if tickers:
            feed_nlp = fetch_nlp_sentiment(tickers[:30], hours=24)

    # Column headers with info popovers
    _hdr_cols = st.columns([1, 4, 1, 1, 1, 1, 1])
    with _hdr_cols[0]:
        with st.popover("**Ticker** ℹ️"):
            st.markdown(
                "**Stock symbol** — The ticker symbol of the company mentioned "
                "in the article (e.g. AAPL, TSLA, NVDA)."
            )
    with _hdr_cols[1]:
        with st.popover("**Headline** ℹ️"):
            st.markdown(
                "**News headline** with sentiment icon "
                "(🟢 positive / 🔴 negative / ⚪ neutral). "
                "Click the link to open the full article."
            )
    with _hdr_cols[2]:
        with st.popover("**Category** ℹ️"):
            st.markdown(
                "**News category** — Classifies the type of news.\n\n"
                "Common values:\n"
                "- `mna` — Mergers & Acquisitions\n"
                "- `earnings` — Earnings reports\n"
                "- `macro` — Macroeconomic news\n"
                "- `analyst` — Analyst actions\n"
                "- `crypto` — Cryptocurrency\n"
                "- `guidance` — Company guidance\n"
                "- `insider` — Insider trading\n"
                "- `govt` — Government/regulation"
            )
    with _hdr_cols[3]:
        with st.popover("**Score** ℹ️"):
            st.markdown(
                "**News importance score** (0–1) computed by the scoring engine "
                "based on source tier, relevance, materiality, and sentiment strength.\n\n"
                "Higher = more market-moving.\n\n"
                "The 🔍 badge means **WIIM** (Why It Matters) — a short explanation "
                "of the article's market relevance."
            )
    with _hdr_cols[4]:
        with st.popover("**Age** ℹ️"):
            st.markdown(
                "**Time since publication** — How long ago the article was published.\n\n"
                "Recency icons:\n"
                "- 🟢 Fresh (< 1 hour)\n"
                "- 🟡 Recent (1–4 hours)\n"
                "- ⚪ Older (> 4 hours)"
            )
    with _hdr_cols[5]:
        with st.popover("**Event** ℹ️"):
            st.markdown(
                "**Event classification label** — Describes the type of market event.\n\n"
                "Examples:\n"
                "- `ma deal` — M&A transaction\n"
                "- `earnings beat` — Earnings surprise\n"
                "- `analyst upgrade` — Rating change\n"
                "- `guidance raised` — Outlook revision\n"
                "- `stock split` — Corporate action\n\n"
                "The provider icon shows the data source."
            )
    with _hdr_cols[6]:
        with st.popover("**NLP** ℹ️"):
            st.markdown(
                "**NLP sentiment cross-validation** from NewsAPI.ai — An independent "
                "sentiment score computed via natural language processing on recent articles.\n\n"
                "Compares against the keyword-based sentiment to spot divergences. "
                "A large gap between NLP and keyword sentiment may indicate the article's "
                "true tone differs from its headline."
            )
    st.divider()

    for d in filtered[:50]:
        sent_icon = SENTIMENT_COLORS.get(d.get("sentiment_label", ""), "")

        # Recompute recency live from published_ts
        pub = d.get("published_ts")
        if pub and pub > 0:
            live_rec = _classify_recency(datetime.fromtimestamp(pub, tz=UTC))
            rec_icon = RECENCY_COLORS.get(live_rec["recency_bucket"], "")
        else:
            rec_icon = RECENCY_COLORS.get(d.get("recency_bucket", ""), "")

        ticker = d.get("ticker", "?")
        score = d.get("news_score", 0)
        category = d.get("category", "other")
        headline = d.get("headline", "")
        event_label = d.get("event_label", "")
        _provider = d.get("provider", "")
        url = d.get("url", "")

        age_str = format_age_string(d.get("published_ts"))
        score_badge = format_score_badge(score)
        prov_icon = provider_icon(_provider)
        _safe_url = safe_url(url)
        wiim_badge = " 🔍" if d.get("is_wiim") else ""

        with st.container():
            cols = st.columns([1, 4, 1, 1, 1, 1, 1])
            with cols[0]:
                st.markdown(f"**{ticker}**")
            with cols[1]:
                safe_hl = safe_markdown_text(headline[:100])
                link = f"[{safe_hl}]({_safe_url})" if _safe_url else headline[:100]
                st.markdown(f"{sent_icon} {link}")
            with cols[2]:
                st.markdown(f"`{category}`")
            with cols[3]:
                st.markdown(score_badge + wiim_badge)
            with cols[4]:
                st.markdown(f"{rec_icon} {age_str}")
            with cols[5]:
                st.markdown(f"{prov_icon} {event_label}")
            with cols[6]:
                nlp_data = feed_nlp.get(ticker.upper())
                if nlp_data and nlp_data.article_count > 0:
                    st.markdown(f"{nlp_data.icon} `NLP {nlp_data.nlp_score:+.2f}`")
                elif feed_nlp:
                    st.markdown("⚪ `NLP —`")
