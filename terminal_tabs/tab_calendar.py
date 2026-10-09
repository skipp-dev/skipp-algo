"""Tab: Calendar — economic calendar from FMP."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
import streamlit as st

from terminal_tabs._shared import cached_econ_calendar


def render(feed: list[dict[str, Any]], *, current_session: str) -> None:
    """Render the Calendar tab."""
    cfg = st.session_state.cfg
    fmp_key = cfg.fmp_api_key

    if not fmp_key:
        st.info("Set `FMP_API_KEY` in `.env` for the economic calendar.")
        return

    st.subheader("📅 Economic Calendar")
    st.caption("Upcoming macro events from FMP (7-day window).")

    today = datetime.now(UTC).date()
    from_date = today.isoformat()
    to_date = (today + timedelta(days=7)).isoformat()

    events = cached_econ_calendar(fmp_key, from_date, to_date)
    if not events:
        st.info("No upcoming economic events found.")
        return

    # Build table
    rows: list[dict[str, Any]] = []
    for ev in events:
        date_str = ev.get("date", "")
        event_name = ev.get("event", ev.get("name", ""))
        country = ev.get("country", "")
        impact = ev.get("impact", ev.get("importance", ""))
        actual = ev.get("actual", "")
        estimate = ev.get("estimate", ev.get("forecast", ""))
        previous = ev.get("previous", "")

        impact_icon = {
            "High": "🔴", "high": "🔴",
            "Medium": "🟡", "medium": "🟡",
            "Low": "🟢", "low": "🟢",
        }.get(str(impact), "⚪")

        rows.append({
            "Date": date_str,
            "Event": event_name[:60],
            "Country": country,
            "Impact": f"{impact_icon} {impact}",
            "Actual": actual,
            "Estimate": estimate,
            "Previous": previous,
        })

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        width="stretch",
        height=min(600, 40 + 35 * len(df)),
        hide_index=True,
    )
