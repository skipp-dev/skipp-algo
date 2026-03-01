"""Tab: Alerts — user-defined alert rules with evaluation log."""

from __future__ import annotations

from typing import Any

import streamlit as st

from terminal_notifications import render_alert_manager


def render(feed: list[dict[str, Any]], *, current_session: str) -> None:
    """Render the Alerts tab."""
    st.subheader("🔔 Alert Rules")
    st.caption("Define custom alert rules. Alerts fire on each poll cycle.")
    render_alert_manager()
