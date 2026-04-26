"""Terminal tab modules — extracted from streamlit_terminal.py for maintainability.

Each trader sub-module exposes ``render(feed, *, current_session)``.
The C7 dashboard sub-modules (``tab_track_record``, ``tab_live_incubation``,
``tab_calibration_detail``, ``methodology_drawer``, ``dashboard_cache``,
``drift_loader``) expose their own ``build_*``/``render`` API and have
no provider-client dependencies.

Trader-tab re-exports are guarded so this package can be imported in
environments that ship only the slim dashboard surface (no httpx,
databento, ML deps). Missing trader tabs become ``None``; the trader
``streamlit_terminal.py`` imports the sub-modules directly so the
re-exports here are convenience-only.
"""

from __future__ import annotations

from typing import Any

__all__: list[str] = []


def _try_export(name: str, module: str, attr: str = "render") -> None:
    try:
        mod = __import__(module, fromlist=[attr])
    except Exception:  # noqa: BLE001 — missing optional trader deps
        globals()[name] = None
        return
    globals()[name] = getattr(mod, attr, None)
    __all__.append(name)


_TRADER_TABS: tuple[tuple[str, str], ...] = (
    ("render_movers", "terminal_tabs.tab_movers"),
    ("render_rankings", "terminal_tabs.tab_rankings"),
    ("render_segments", "terminal_tabs.tab_segments"),
    ("render_rt_spikes", "terminal_tabs.tab_rt_spikes"),
    ("render_spikes", "terminal_tabs.tab_spikes"),
    ("render_heatmap", "terminal_tabs.tab_heatmap"),
    ("render_calendar", "terminal_tabs.tab_calendar"),
    ("render_outlook", "terminal_tabs.tab_outlook"),
    ("render_bz_movers", "terminal_tabs.tab_bz_movers"),
    ("render_bitcoin", "terminal_tabs.tab_bitcoin"),
    ("render_defense", "terminal_tabs.tab_defense"),
    ("render_breaking", "terminal_tabs.tab_breaking"),
    ("render_trending", "terminal_tabs.tab_trending"),
    ("render_social", "terminal_tabs.tab_social"),
    ("render_alerts", "terminal_tabs.tab_alerts"),
    ("render_data_table", "terminal_tabs.tab_data_table"),
    ("render_fmp_ai", "terminal_tabs.tab_fmp_ai"),
)

for _name, _module in _TRADER_TABS:
    _try_export(_name, _module)


def __getattr__(name: str) -> Any:
    if name in {n for n, _ in _TRADER_TABS} and name not in globals():
        return None
    raise AttributeError(name)
