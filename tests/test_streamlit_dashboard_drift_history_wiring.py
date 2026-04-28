"""Smoke test for ``streamlit_dashboard`` drift-history panel wiring (T2-dash).

Verifies that:
  * ``streamlit_dashboard`` imports cleanly.
  * Its ``main`` references ``tab_live_incubation`` exactly as the wiring
    contract requires (defensive ``hasattr`` guard around
    ``render_drift_history``).
  * When ``render_drift_history`` is present on the tab module, ``main``
    invokes it with the resolved ``cache_dir`` and the documented
    ``DRIFT_HISTORY_DEFAULT_N`` constant.

The streamlit runtime is monkey-patched to no-op stubs so we don't pull
in the full Streamlit machinery during pytest.
"""

from __future__ import annotations

import importlib
import inspect
import sys
import types
from contextlib import contextmanager
from unittest.mock import MagicMock


def test_streamlit_dashboard_imports_cleanly() -> None:
    mod = importlib.import_module("streamlit_dashboard")
    assert hasattr(mod, "main")


def test_streamlit_dashboard_wires_render_drift_history_with_hasattr_guard() -> None:
    """Source-level check: hasattr guard + render_drift_history call exist."""
    mod = importlib.import_module("streamlit_dashboard")
    src = inspect.getsource(mod.main)
    assert 'hasattr(tab_live_incubation, "render_drift_history")' in src
    assert "tab_live_incubation.render_drift_history(" in src
    assert "DRIFT_HISTORY_DEFAULT_N" in src


def test_streamlit_dashboard_main_calls_render_drift_history_when_available(
    monkeypatch,
) -> None:
    """Behavioural check: when the symbol is present, main calls it."""
    import streamlit_dashboard as sd

    # Stub streamlit primitives used in main() so it executes headless.
    fake_st = types.SimpleNamespace()
    fake_st.set_page_config = MagicMock()
    fake_st.sidebar = types.SimpleNamespace(caption=MagicMock())
    fake_st.info = MagicMock()
    fake_st.selectbox = MagicMock(return_value="x")

    @contextmanager
    def _ctx():
        yield None

    fake_st.tabs = MagicMock(return_value=(_ctx(), _ctx(), _ctx()))
    monkeypatch.setattr(sd, "st", fake_st)

    # Stub payload + drift loaders.
    monkeypatch.setattr(sd, "_load_payload", lambda *a, **kw: {"variants": []})
    monkeypatch.setattr(sd, "_load_drift", lambda *a, **kw: None)
    monkeypatch.setattr(sd, "list_drift_dates", lambda *a, **kw: [])

    # Stub tab modules.
    sd.methodology_drawer.render_sidebar = MagicMock()
    sd.tab_track_record.render = MagicMock()
    sd.tab_calibration_detail.render = MagicMock()
    sd.tab_live_incubation.render = MagicMock()

    # Inject the symbol-under-test.
    render_drift_history = MagicMock()
    sd.tab_live_incubation.render_drift_history = render_drift_history
    sd.tab_live_incubation.DRIFT_HISTORY_DEFAULT_N = 7

    sd.main()

    render_drift_history.assert_called_once()
    _, kwargs = render_drift_history.call_args
    assert kwargs.get("n") == 7
    assert "cache_dir" in kwargs


def test_streamlit_dashboard_main_skips_panel_when_symbol_absent(
    monkeypatch,
) -> None:
    """Defensive: if PR #407 not yet merged, main() must still run."""
    import streamlit_dashboard as sd

    fake_st = types.SimpleNamespace()
    fake_st.set_page_config = MagicMock()
    fake_st.sidebar = types.SimpleNamespace(caption=MagicMock())
    fake_st.info = MagicMock()
    fake_st.selectbox = MagicMock(return_value="x")

    @contextmanager
    def _ctx():
        yield None

    fake_st.tabs = MagicMock(return_value=(_ctx(), _ctx(), _ctx()))
    monkeypatch.setattr(sd, "st", fake_st)

    monkeypatch.setattr(sd, "_load_payload", lambda *a, **kw: {"variants": []})
    monkeypatch.setattr(sd, "_load_drift", lambda *a, **kw: None)
    monkeypatch.setattr(sd, "list_drift_dates", lambda *a, **kw: [])

    sd.methodology_drawer.render_sidebar = MagicMock()
    sd.tab_track_record.render = MagicMock()
    sd.tab_calibration_detail.render = MagicMock()
    sd.tab_live_incubation.render = MagicMock()

    # Make sure render_drift_history is *absent* on the stub.
    if hasattr(sd.tab_live_incubation, "render_drift_history"):
        delattr(sd.tab_live_incubation, "render_drift_history")

    # Should not raise.
    sd.main()


def teardown_module(_module: object) -> None:
    """Drop the cached streamlit_dashboard import so other tests get a clean slate."""
    sys.modules.pop("streamlit_dashboard", None)
