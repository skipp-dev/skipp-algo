from __future__ import annotations

import importlib
import sys


def test_streamlit_terminal_import_smoke_in_test_mode(monkeypatch) -> None:
    monkeypatch.setenv("_SMC_TERMINAL_TEST_MODE", "1")
    sys.modules.pop("streamlit_terminal", None)

    module = importlib.import_module("streamlit_terminal")

    assert module._SMC_TERMINAL_TEST_MODE is True
    assert isinstance(module.st.session_state.get("feed"), list)
    assert module.st.session_state.get("auto_refresh") is False


def test_streamlit_terminal_import_initializes_expected_test_state(monkeypatch) -> None:
    monkeypatch.setenv("_SMC_TERMINAL_TEST_MODE", "1")
    sys.modules.pop("streamlit_terminal", None)

    module = importlib.import_module("streamlit_terminal")

    expected_keys = {
        "cfg",
        "cursor",
        "provider_cursors",
        "feed",
        "live_story_state",
        "ticker_catalyst_state",
        "ticker_reaction_state",
        "ticker_resolution_state",
        "ticker_posture_state",
        "ticker_attention_state",
        "poll_count",
        "last_poll_ts",
        "last_resync_ts",
        "auto_refresh",
        "use_bg_poller",
        "intel_toggle",
    }

    assert expected_keys.issubset(set(module.st.session_state.keys()))


def test_streamlit_terminal_import_sets_all_expected_session_state_types(monkeypatch) -> None:
    monkeypatch.setenv("_SMC_TERMINAL_TEST_MODE", "1")
    sys.modules.pop("streamlit_terminal", None)

    module = importlib.import_module("streamlit_terminal")

    assert isinstance(module.st.session_state.get("provider_cursors"), dict)
    assert isinstance(module.st.session_state.get("feed"), list)
    assert isinstance(module.st.session_state.get("live_story_state"), dict)
    assert isinstance(module.st.session_state.get("poll_count"), int)
    assert isinstance(module.st.session_state.get("last_poll_ts"), float)
    assert isinstance(module.st.session_state.get("last_resync_ts"), float)


def test_streamlit_terminal_import_test_mode_does_not_require_api_keys(monkeypatch) -> None:
    monkeypatch.setenv("_SMC_TERMINAL_TEST_MODE", "1")
    monkeypatch.delenv("BENZINGA_API_KEY", raising=False)
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.delenv("NEWSAPI_KEY", raising=False)
    sys.modules.pop("streamlit_terminal", None)

    module = importlib.import_module("streamlit_terminal")

    assert module._SMC_TERMINAL_TEST_MODE is True
    assert module.st.session_state.get("cfg") is not None
