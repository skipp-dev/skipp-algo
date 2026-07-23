"""Central visual language for the Skipp Terminal.

One rule: **green and red mean market direction only** (up/down, bullish/
bearish, long/short). Everything else — attention, reaction, resolution,
provider status, session — is plain neutral text. No emoji in data cells.

Use :func:`dir_glyph` for a monochrome direction marker and
:func:`style_directional` to tint only the columns that carry a sign.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd

# Palette shared with the access gate so login and terminal are one system.
UP = "#56d0a2"    # bullish / up / long
DOWN = "#ff6b6b"  # bearish / down / short


def _num(val: Any) -> float | None:
    try:
        return float(str(val).replace("%", "").replace("+", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def dir_glyph(chg: Any) -> str:
    """Monochrome direction marker for a signed change (no colour, no emoji)."""
    c = _num(chg)
    if c is None or c == 0:
        return "–"
    return "▲" if c > 0 else "▼"


def label(value: Any) -> str:
    """Neutral, title-cased label for a state string ('WATCH_LONG' -> 'Watch Long')."""
    s = str(value or "").strip()
    if not s:
        return ""
    return s.replace("_", " ").title()


def _sign_colour(val: Any) -> str:
    """CSS colour for a cell whose text starts with a direction sign."""
    s = str(val).strip()
    if s.startswith(("▲", "+")):
        return f"color: {UP}"
    if s.startswith(("▼", "-", "−")):
        return f"color: {DOWN}"
    return ""


def style_directional(df: pd.DataFrame, cols: Iterable[str]) -> Any:
    """Return a Styler that tints *only* the given columns by their sign.

    Colour is reserved for direction; the rest of the table stays neutral.
    Compatible with both pandas >=2.1 (Styler.map) and older (applymap).
    """
    present = [c for c in cols if c in df.columns]
    styler = df.style
    if not present:
        return styler
    apply_cell = getattr(styler, "map", None) or styler.applymap
    return apply_cell(_sign_colour, subset=present)
