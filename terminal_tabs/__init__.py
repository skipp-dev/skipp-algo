"""Terminal tab modules — extracted from streamlit_terminal.py for maintainability.

Each trader sub-module exposes ``render(feed, *, current_session)``.
The C7 dashboard sub-modules (``tab_track_record``, ``tab_live_incubation``,
``tab_calibration_detail``, ``methodology_drawer``, ``dashboard_cache``,
``drift_loader``) expose their own ``build_*``/``render`` API and have
no provider-client dependencies.

Trader-tab re-exports are resolved **lazily on first attribute access**
so this package can be imported in environments that ship only the slim
dashboard surface (no httpx, databento, ML deps).  Missing trader tabs
resolve to ``None``; the trader ``streamlit_terminal.py`` imports the
sub-modules directly so the re-exports here are convenience-only.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__: list[str] = []

# Name -> dotted module path for trader-tab convenience re-exports.
# Resolved on first access via :func:`__getattr__`; never eagerly
# imported (the slim dashboard image lacks several of these modules
# and any eager import would cascade ImportErrors at package load).
_TRADER_TABS: dict[str, str] = {
    "render_movers": "terminal_tabs.tab_movers",
    "render_rankings": "terminal_tabs.tab_rankings",
    "render_segments": "terminal_tabs.tab_segments",
    "render_rt_spikes": "terminal_tabs.tab_rt_spikes",
    "render_spikes": "terminal_tabs.tab_spikes",
    "render_heatmap": "terminal_tabs.tab_heatmap",
    "render_calendar": "terminal_tabs.tab_calendar",
    "render_outlook": "terminal_tabs.tab_outlook",
    "render_bz_movers": "terminal_tabs.tab_bz_movers",
    "render_bitcoin": "terminal_tabs.tab_bitcoin",
    "render_defense": "terminal_tabs.tab_defense",
    "render_breaking": "terminal_tabs.tab_breaking",
    "render_trending": "terminal_tabs.tab_trending",
    "render_social": "terminal_tabs.tab_social",
    "render_alerts": "terminal_tabs.tab_alerts",
    "render_data_table": "terminal_tabs.tab_data_table",
    "render_fmp_ai": "terminal_tabs.tab_fmp_ai",
}


def __getattr__(name: str) -> Any:
    module_path = _TRADER_TABS.get(name)
    if module_path is None:
        raise AttributeError(name)
    try:
        mod = importlib.import_module(module_path)
    except (ImportError, ModuleNotFoundError):
        # Trader dep missing in slim image: cache None so subsequent
        # accesses skip the import attempt.
        globals()[name] = None
        return None
    value = getattr(mod, "render", None)
    globals()[name] = value
    if value is not None and name not in __all__:
        __all__.append(name)
    return value
