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