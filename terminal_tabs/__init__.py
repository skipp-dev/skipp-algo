"""Terminal tab modules — extracted from streamlit_terminal.py for maintainability.

Each sub-module exposes a ``render(feed, *, current_session)`` function
that renders one Streamlit tab.  Shared helpers live in ``_shared.py``.
"""

from terminal_tabs.tab_feed import render as render_feed  # noqa: F401
from terminal_tabs.tab_movers import render as render_movers  # noqa: F401
from terminal_tabs.tab_rankings import render as render_rankings  # noqa: F401
from terminal_tabs.tab_segments import render as render_segments  # noqa: F401
from terminal_tabs.tab_rt_spikes import render as render_rt_spikes  # noqa: F401
from terminal_tabs.tab_spikes import render as render_spikes  # noqa: F401
from terminal_tabs.tab_heatmap import render as render_heatmap  # noqa: F401
from terminal_tabs.tab_calendar import render as render_calendar  # noqa: F401
from terminal_tabs.tab_outlook import render as render_outlook  # noqa: F401
from terminal_tabs.tab_bz_movers import render as render_bz_movers  # noqa: F401
from terminal_tabs.tab_bitcoin import render as render_bitcoin  # noqa: F401
from terminal_tabs.tab_defense import render as render_defense  # noqa: F401
from terminal_tabs.tab_breaking import render as render_breaking  # noqa: F401
from terminal_tabs.tab_trending import render as render_trending  # noqa: F401
from terminal_tabs.tab_social import render as render_social  # noqa: F401
from terminal_tabs.tab_alerts import render as render_alerts  # noqa: F401
from terminal_tabs.tab_data_table import render as render_data_table  # noqa: F401
from terminal_tabs.tab_ai import render as render_ai  # noqa: F401
