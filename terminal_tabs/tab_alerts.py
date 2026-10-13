"""Tab: Alerts — user-defined alert rules with evaluation log."""

from __future__ import annotations

from typing import Any

import streamlit as st

from terminal_notifications import NotifyConfig


def render(feed: list[dict[str, Any]], *, current_session: str) -> None:
    """Render the Alerts tab."""
    st.subheader("🔔 Alert Rules")
    st.caption("Notification channels configured in `.env`. Alerts fire on each poll cycle.")

    cfg = NotifyConfig()

    # Show configured channels
    channels: list[str] = []
    if cfg.telegram_bot_token and cfg.telegram_chat_id:
        channels.append("✅ Telegram")
    else:
        channels.append("⬜ Telegram (not configured)")
    if cfg.discord_webhook_url:
        channels.append("✅ Discord")
    else:
        channels.append("⬜ Discord (not configured)")
    if cfg.pushover_app_token and cfg.pushover_user_key:
        channels.append("✅ Pushover")
    else:
        channels.append("⬜ Pushover (not configured)")

    st.markdown("**Notification Channels:**")
    for ch in channels:
        st.markdown(f"- {ch}")

    st.divider()
    st.markdown(
        "**How it works:** High-score news items (above the configured threshold) "
        "are automatically sent to your notification channels during market hours. "
        "Configure via environment variables in `.env`:\n\n"
        "- `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`\n"
        "- `DISCORD_WEBHOOK_URL`\n"
        "- `PUSHOVER_APP_TOKEN` + `PUSHOVER_USER_KEY`\n\n"
        f"Current score threshold: **{cfg.min_score}** · "
        f"Throttle: **{cfg.throttle_s}s** per symbol"
    )
