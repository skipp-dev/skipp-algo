"""Tab: Social — social-media buzz from NewsAPI.ai + Finnhub."""

from __future__ import annotations

from typing import Any

import streamlit as st

from terminal_newsapi import (
    fetch_social_ranked_articles,
    is_available as newsapi_available,
)
from terminal_finnhub import (
    fetch_social_sentiment_batch,
    is_available as finnhub_available,
)
from terminal_ui_helpers import safe_markdown_text, safe_url


def render(feed: list[dict[str, Any]], *, current_session: str) -> None:
    """Render the Social Buzz tab."""
    st.subheader("💬 Social Buzz")
    st.caption("Social-media sentiment — Reddit & Twitter mentions + most-shared news.")

    # ── Section 1: Finnhub Reddit + Twitter Sentiment ────────────
    if finnhub_available():
        # Extract unique tickers from the live feed
        _feed_tickers: list[str] = []
        _seen: set[str] = set()
        for item in feed:
            for sym in item.get("tickers", []):
                s = sym.upper().strip()
                if s and s not in _seen and len(s) <= 5:
                    _seen.add(s)
                    _feed_tickers.append(s)
        _feed_tickers = _feed_tickers[:20]  # cap at 20 lookups

        if _feed_tickers:
            st.markdown("### 📡 Reddit & Twitter Sentiment")
            st.caption(
                f"Live social-media mentions for {len(_feed_tickers)} trending tickers · "
                "Source: Finnhub (free tier, real-time)."
            )
            fh_data = fetch_social_sentiment_batch(_feed_tickers)
            if fh_data:
                # Sort by total mentions descending
                _sorted = sorted(fh_data.values(), key=lambda s: s.total_mentions, reverse=True)

                # Top 5 cards
                _top = _sorted[:5]
                _cols = st.columns(min(5, len(_top)))
                for _i, _s in enumerate(_top):
                    with _cols[_i]:
                        st.markdown(f"**{_s.symbol}** {_s.emoji}")
                        st.metric("Mentions", f"{_s.total_mentions:,}")
                        st.caption(
                            f"Reddit {_s.reddit_mentions:,} · Twitter {_s.twitter_mentions:,}\n\n"
                            f"Score: {_s.score:+.2f}"
                        )

                # Full table
                _rows = []
                for _s in _sorted:
                    _rows.append({
                        "Symbol": _s.symbol,
                        "Sentiment": _s.emoji,
                        "Total Mentions": _s.total_mentions,
                        "Reddit": _s.reddit_mentions,
                        "Twitter/X": _s.twitter_mentions,
                        "Score": f"{_s.score:+.4f}",
                        "Label": _s.sentiment_label.title(),
                    })
                if _rows:
                    import pandas as pd
                    st.dataframe(
                        pd.DataFrame(_rows),
                        hide_index=True,
                        height=min(40 * len(_rows) + 50, 500),
                    )
            else:
                st.caption("No social sentiment data available for current tickers.")
            st.markdown("---")
    elif not finnhub_available() and not newsapi_available():
        st.info("Set `FINNHUB_API_KEY` and/or `NEWSAPI_AI_KEY` in `.env` for social buzz data.")
        return

    # ── Section 2: NewsAPI.ai Most-Shared Articles ───────────────
    if newsapi_available():
        st.markdown("### 🔥 Most-Shared News")
        articles = fetch_social_ranked_articles(count=20)
        if not articles:
            st.info("No social buzz data available.")
        else:
            for art in articles:
                safe_title = safe_markdown_text((art.title or "(no title)")[:120])
                link = f"[{safe_title}]({safe_url(art.url)})" if art.url else safe_title

                with st.container():
                    cols = st.columns([4, 1, 1])
                    with cols[0]:
                        st.markdown(f"{art.sentiment_icon} **{link}**")
                        parts: list[str] = []
                        if art.source:
                            parts.append(f"*{art.source}*")
                        if art.date:
                            parts.append(art.date[:16])
                        if parts:
                            st.caption(" · ".join(parts))
                    with cols[1]:
                        if art.sentiment is not None:
                            st.metric("Sentiment", f"{art.sentiment:+.2f}")
                    with cols[2]:
                        if art.social_score:
                            st.metric("Buzz", f"{art.social_score:,}")
    elif not finnhub_available():
        st.info("Set `NEWSAPI_AI_KEY` in `.env` for social buzz data.")
