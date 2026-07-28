"""ATR-based trade context for realtime breakout signals — display guidance.

Computes an entry/stop/target/R bracket from a signal's price, ATR%, and
direction so every consumer (Slack push via ``rt_notify``, Pine overlay via the
daemon's ``/smc_live`` payload) shows the SAME numbers — one computation, two
consumers.

Bracket convention mirrors C13 (2:1 reward:risk): stop = 1.0×ATR against the
signal, target = 2.0×ATR with it (env-tunable). These are *display* levels for
a human deciding on the alert — NOT order placement: the C13 execution path
computes its own levels from open_prep setups and snaps them to the exchange
min tick (see scripts/execute_ibkr_watchlist.py).

Fail-soft by construction: no price, no ATR, or an unknown direction yields no
context (``None``), never an exception.
"""
from __future__ import annotations

import os
from typing import Any

_BULLISH = frozenset({"LONG", "B_UP", "UP"})
_BEARISH = frozenset({"SHORT", "B_DOWN", "DOWN"})

_DEFAULT_STOP_ATR_MULT = 1.0
_DEFAULT_TARGET_ATR_MULT = 2.0


def _env_mult(name: str, default: float) -> float:
    """Positive float from env; silently falls back on garbage/absence."""
    try:
        value = float(os.environ.get(name, "") or default)
    except ValueError:
        return default
    return value if value > 0 else default


def trade_context(
    price: float, atr_pct: float, direction: str
) -> dict[str, float] | None:
    """Return ``{trade_entry, trade_stop, trade_target, trade_r}`` or ``None``.

    ``atr_pct`` is a percentage (2.5 == 2.5%), the scale the realtime engine
    carries on its signals. Values are rounded to cents for display.
    """
    from .atr_quality import actionable_atr_pct
    safe_atr_pct = actionable_atr_pct(atr_pct)
    if not (price > 0.0 and safe_atr_pct is not None):
        return None
    direction_key = str(direction or "").upper()
    if direction_key in _BULLISH:
        sign = 1.0
    elif direction_key in _BEARISH:
        sign = -1.0
    else:
        return None
    stop_mult = _env_mult("RT_TRADE_STOP_ATR_MULT", _DEFAULT_STOP_ATR_MULT)
    target_mult = _env_mult("RT_TRADE_TARGET_ATR_MULT", _DEFAULT_TARGET_ATR_MULT)
    atr_abs = price * (safe_atr_pct / 100.0)
    return {
        "trade_entry": round(price, 2),
        "trade_stop": round(price - sign * stop_mult * atr_abs, 2),
        "trade_target": round(price + sign * target_mult * atr_abs, 2),
        "trade_r": round(target_mult / stop_mult, 1),
    }


def attach(signal: Any) -> None:
    """Set the four ``trade_*`` fields on a (mutable) signal in place.

    Reads ``price`` / ``atr_pct`` / ``direction`` via getattr; a signal without
    usable inputs keeps its defaults (None). Never raises.
    """
    try:
        ctx = trade_context(
            float(getattr(signal, "price", 0.0) or 0.0),
            float(getattr(signal, "atr_pct", 0.0) or 0.0),
            str(getattr(signal, "direction", "")),
        )
    except (TypeError, ValueError):
        ctx = None
    if not ctx:
        return
    for key, value in ctx.items():
        setattr(signal, key, value)
