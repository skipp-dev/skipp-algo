"""A-3: Tests for the session_state schema-version invalidation guard.

The guard drops *derived* session_state keys (feed, ticker_*_state, cursors,
live_story_state) when the in-process ``_SESSION_SCHEMA_VERSION`` constant
no longer matches the version stored in the user's session. User inputs
(api keys, sidebar toggles, manually entered symbols) must be preserved.
"""
from __future__ import annotations

import importlib
import sys


def _reload_terminal(monkeypatch):
    monkeypatch.setenv("_SMC_TERMINAL_TEST_MODE", "1")
    sys.modules.pop("streamlit_terminal", None)
    return importlib.import_module("streamlit_terminal")


def test_schema_version_constant_is_set(monkeypatch) -> None:
    module = _reload_terminal(monkeypatch)
    assert isinstance(module._SESSION_SCHEMA_VERSION, str)
    assert module._SESSION_SCHEMA_VERSION  # non-empty


def test_invalidation_is_noop_when_version_matches(monkeypatch) -> None:
    module = _reload_terminal(monkeypatch)
    state = module.st.session_state
    state["_session_schema_ver"] = module._SESSION_SCHEMA_VERSION
    state["feed"] = [{"id": "x"}]
    state["live_story_state"] = {"a": 1}

    module._invalidate_session_state_on_schema_change()

    assert state["feed"] == [{"id": "x"}]
    assert state["live_story_state"] == {"a": 1}


def test_invalidation_drops_derived_keys_on_version_change(monkeypatch) -> None:
    module = _reload_terminal(monkeypatch)
    state = module.st.session_state
    # Pretend the user's session is from an older deploy.
    state["_session_schema_ver"] = "1900-01-01.0"
    # Pre-populate every derived key with sentinel values.
    sentinel_keys = list(module._SESSION_DERIVED_STATE_KEYS)
    for key in sentinel_keys:
        state[key] = "sentinel"
    # And one user-input key that must survive.
    state["dvs_databento_api_key"] = "user-secret"
    state["auto_refresh"] = True

    module._invalidate_session_state_on_schema_change()

    for key in sentinel_keys:
        assert key not in state, f"derived key {key!r} should have been dropped"
    assert state["_session_schema_ver"] == module._SESSION_SCHEMA_VERSION
    # User inputs preserved.
    assert state["dvs_databento_api_key"] == "user-secret"
    assert state["auto_refresh"] is True


def test_invalidation_is_idempotent(monkeypatch) -> None:
    module = _reload_terminal(monkeypatch)
    state = module.st.session_state
    state["_session_schema_ver"] = "1900-01-01.0"
    state["feed"] = [{"id": "x"}]

    module._invalidate_session_state_on_schema_change()
    state["feed"] = [{"id": "post-invalidation"}]
    # Second call must not re-drop the freshly populated state.
    module._invalidate_session_state_on_schema_change()

    assert state["feed"] == [{"id": "post-invalidation"}]


def test_derived_keys_excludes_user_input_keys(monkeypatch) -> None:
    """Regression guard: never list user-input keys in DERIVED set."""
    module = _reload_terminal(monkeypatch)
    forbidden = {
        "cfg",
        "auto_refresh",
        "intel_toggle",
        "dvs_databento_api_key",
        "dvs_fmp_api_key",
        "dvs_bullish_score_profile",
        "_auth_ok",
    }
    derived = set(module._SESSION_DERIVED_STATE_KEYS)
    overlap = forbidden & derived
    assert not overlap, f"user-input keys must not be in DERIVED set: {overlap}"
