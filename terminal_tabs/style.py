"""Central visual language for the Skipp Terminal.

Colour is a *quiet* signal here. Muted green / amber / red hint at a value's
state — bullish/neutral/bearish, ok/degraded/down, high/medium/low, fresh/old —
without the glare of a saturated dot. Direction markers stay monochrome; tables
receive their colour through the Styler helpers below (never emoji in cells), so
the same restrained palette applies everywhere.

Palette rule: green/red still mean up/down, but every tone here is deliberately
desaturated so it reads as a gentle hint on the dark (#0b1020) terminal.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd

# Muted palette — desaturated on purpose ("dezent"), tuned for readability on
# the dark background without shouting. UP/DOWN are softer than a pure signal
# green/red; WARN is a calm amber; NEUTRAL a blue-grey.
UP = "#7fb093"       # bullish · long · up · ok · pass · fresh · risk-on
DOWN = "#cf8b8b"     # bearish · short · down · fail · stale · high-attention
WARN = "#c9ab74"     # neutral-attention · medium · recent · degraded · watch
NEUTRAL = "#8b93a6"  # no signal · low · background

# State token -> palette bucket. Curated across the terminal's vocabularies
# (sentiment, posture, attention, reaction, resolution, materiality, recency,
# provider/gate health). Unknown tokens get no colour.
_UP = {
    "bullish", "long", "buy", "strong_buy", "up", "ok", "pass", "green",
    "fresh", "risk_on", "follow_through", "confirmed", "live", "healthy",
    "current", "gain", "gainer", "oversold", "positive",
}
_DOWN = {
    "bearish", "short", "sell", "strong_sell", "down", "fail", "red", "stale",
    "unavailable", "invalid", "reversal", "failed", "risk_off", "avoid",
    "high", "alert", "loss", "loser", "overbought", "negative", "suppress",
    "conflicted",
}
_WARN = {
    "neutral", "watch", "monitor", "medium", "recent", "degraded", "amber",
    "retry", "mixed", "idle", "open", "stalled", "acceptable", "warn",
    "moderate", "background",
}


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


def _token(value: Any) -> str:
    """Normalise a cell/state to a lookup token (glyphs, signs, spacing stripped)."""
    s = str(value or "").strip().lower()
    s = s.lstrip("▲▼–-−+ ").strip()
    return s.replace(" ", "_").replace("-", "_")


def semantic_color(value: Any) -> str:
    """Muted CSS ``color:`` for a state token; '' when unknown or neutral-low."""
    t = _token(value)
    if not t:
        return ""
    for bucket, css in ((_UP, UP), (_DOWN, DOWN), (_WARN, WARN)):
        if t in bucket:
            return f"color: {css}"
    head = t.split("_", 1)[0]  # "fresh_(<1h)", "high_impact" -> "fresh"/"high"
    for bucket, css in ((_UP, UP), (_DOWN, DOWN), (_WARN, WARN)):
        if head in bucket:
            return f"color: {css}"
    return ""


def _cell_colour_sign(val: Any) -> str:
    """Muted CSS colour for a cell whose text starts with a direction sign."""
    s = str(val).strip()
    if s.startswith(("▲", "+")):
        return f"color: {UP}"
    if s.startswith(("▼", "-", "−")):
        return f"color: {DOWN}"
    return ""


def _apply(styler: Any, fn: Any, cols: list[str]) -> None:
    if not cols:
        return
    apply_cell = getattr(styler, "map", None) or styler.applymap
    apply_cell(fn, subset=cols)


def style_directional(df: pd.DataFrame, cols: Iterable[str]) -> Any:
    """Styler that tints the given columns by their +/-/▲/▼ sign (muted)."""
    styler = df.style
    _apply(styler, _cell_colour_sign, [c for c in cols if c in df.columns])
    return styler


def style_semantic(df: pd.DataFrame, cols: Iterable[str]) -> Any:
    """Styler that tints the given state columns with the muted palette."""
    styler = df.style
    _apply(styler, semantic_color, [c for c in cols if c in df.columns])
    return styler


def style_table(
    df: pd.DataFrame,
    *,
    directional: Iterable[str] = (),
    semantic: Iterable[str] = (),
) -> Any:
    """Styler applying sign-colour to ``directional`` columns and state-colour to
    ``semantic`` columns in one pass — the common case for a mixed table."""
    styler = df.style
    _apply(styler, _cell_colour_sign, [c for c in directional if c in df.columns])
    _apply(styler, semantic_color, [c for c in semantic if c in df.columns])
    return styler


def color_text(value: Any, text: str | None = None) -> str:
    """Inline HTML span tinting *text* by the state of *value* (for st.markdown).

    Returns plain text when the state is unknown so callers stay emoji-free and
    uncoloured rather than forcing a hue.
    """
    shown = str(value if text is None else text)
    css = semantic_color(value)
    if not css:
        return shown
    return f'<span style="{css}">{shown}</span>'
