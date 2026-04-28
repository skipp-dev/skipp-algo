"""Lightweight auth guard for the hosted SkippALGO Terminal.

When ``STREAMLIT_AUTH_TOKEN`` is set, the terminal requires a valid
token before rendering.  Users provide the token once via a password
input; it is stored in ``st.session_state`` for the session duration.

Usage in streamlit_terminal.py::

    from terminal_auth import require_auth
    if not require_auth():
        st.stop()

When no token is configured (local dev), ``require_auth`` returns True
immediately — zero friction for local usage.
"""
from __future__ import annotations

import hmac
import os


def _get_required_token() -> str | None:
    """Return the expected auth token from the environment, or None if unset."""
    token = os.environ.get("STREAMLIT_AUTH_TOKEN", "").strip()
    return token if token else None


def _constant_time_compare(a: str, b: str) -> bool:
    """Timing-safe comparison to prevent side-channel leakage."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def require_auth() -> bool:
    """Check auth and render login form if needed.

    Returns True if the user is authenticated (or no token is required).
    Returns False if the user has not yet authenticated — caller should
    ``st.stop()`` to prevent rendering the main app.

    Note: the caller must call ``st.set_page_config()`` before this
    function, as Streamlit requires it to be the first command.
    """
    required = _get_required_token()
    if required is None:
        return True

    import streamlit as st

    if st.session_state.get("_auth_ok") is True:
        return True

    st.title("🔒 SkippALGO Terminal")
    st.caption("Enter your access token to continue.")

    token_input = st.text_input("Access Token", type="password", key="_auth_token_input")
    if st.button("Login", type="primary"):
        if _constant_time_compare(token_input, required):
            st.session_state["_auth_ok"] = True
            st.rerun()
        else:
            st.error("Invalid token.")
    return False
