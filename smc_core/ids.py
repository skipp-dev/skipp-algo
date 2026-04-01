"""Deterministic event-ID generation with symbol-aware price quantization.

Price quantization resolution order (same for all ID functions):
1. Explicit ``ticksize`` kwarg → snap to nearest multiple.
2. Symbol lookup in ``SYMBOL_TICKSIZE`` → derive decimals from tick.
3. Fall back to 2 decimals (backward-compatible default for equities).

This means ``bos_id("ES", ...)`` automatically snaps to 0.25 ticks,
``bos_id("BTC", ...)`` snaps to whole dollars, and unknown symbols
fall back to 2 decimals.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo
from datetime import datetime, timezone

from .types import BosDir, BosEventKind, FvgDir, ObDir, SweepSide

_TIMEFRAME_TO_SECONDS = {
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1H": 60 * 60,
    "4H": 240 * 60,
    "1D": 1440 * 60,
}

# Default tick sizes per asset class.  Specific symbols override via SYMBOL_TICKSIZE.
_ASSET_CLASS_TICKSIZE: dict[str, float] = {
    "equity": 0.01,
    "futures": 0.25,
    "crypto": 0.01,
    "forex": 0.0001,
}

# Per-symbol tick-size overrides (extend as needed).
SYMBOL_TICKSIZE: dict[str, float] = {
    "ES": 0.25,
    "NQ": 0.25,
    "MES": 0.25,
    "MNQ": 0.25,
    "CL": 0.01,
    "GC": 0.10,
    "BTC": 1.0,
    "ETH": 0.01,
}

# Default exchange session timezone for daily anchoring.
DEFAULT_SESSION_TZ = "America/New_York"


def _norm_symbol(symbol: str) -> str:
    return symbol.upper().strip()


def _validate_timeframe(timeframe: str) -> int:
    try:
        return _TIMEFRAME_TO_SECONDS[timeframe]
    except KeyError as exc:
        raise ValueError(f"unsupported timeframe: {timeframe}") from exc


def _decimals_for_ticksize(ticksize: float) -> int:
    """Derive the number of decimals from a tick size."""
    s = f"{ticksize:.10f}".rstrip("0")
    if "." not in s:
        return 0
    return len(s.split(".")[1])


def quantize_price(
    price: float,
    decimals: int = 2,
    *,
    ticksize: float | None = None,
    symbol: str | None = None,
) -> float:
    """Quantize *price* to the nearest tick or decimal.

    Resolution order:
    1. Explicit *ticksize* parameter  →  snap to nearest multiple.
    2. *symbol* lookup in SYMBOL_TICKSIZE  →  derive decimals.
    3. Fall back to *decimals* parameter (backward-compatible default).
    """
    if ticksize is not None:
        if ticksize <= 0:
            raise ValueError("ticksize must be > 0")
        d = _decimals_for_ticksize(ticksize)
        tick_d = Decimal(str(ticksize))
        quantized = (Decimal(str(price)) / tick_d).quantize(Decimal(1), rounding=ROUND_HALF_UP) * tick_d
        return float(quantized.quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP))

    if symbol is not None:
        sym = _norm_symbol(symbol)
        ts = SYMBOL_TICKSIZE.get(sym)
        if ts is not None:
            return quantize_price(price, ticksize=ts)

    if decimals < 0:
        raise ValueError("decimals must be >= 0")
    quantum = Decimal(1).scaleb(-decimals)
    return float(Decimal(str(price)).quantize(quantum, rounding=ROUND_HALF_UP))


def quantize_time_to_tf(
    epoch_sec: float,
    timeframe: str,
    *,
    session_tz: str | None = None,
) -> float:
    """Floor *epoch_sec* to the start of the timeframe block.

    For sub-daily timeframes, simple modular arithmetic is used.
    For ``1D``, the anchor is the start of the *exchange session day*
    (midnight in *session_tz*, defaulting to ``America/New_York``).
    """
    block = _validate_timeframe(timeframe)
    seconds = int(epoch_sec)

    if timeframe == "1D":
        tz = ZoneInfo(session_tz or DEFAULT_SESSION_TZ)
        dt = datetime.fromtimestamp(seconds, tz=timezone.utc).astimezone(tz)
        midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        return float(int(midnight.astimezone(timezone.utc).timestamp()))

    return float(seconds - (seconds % block))


def _quantize_for_id(
    price: float,
    *,
    symbol: str | None = None,
    ticksize: float | None = None,
) -> str:
    """Quantize *price* for use in event IDs.

    Resolution order:
    1. Explicit *ticksize*  →  ``quantize_price(price, ticksize=ticksize)``
    2. *symbol* lookup      →  ``quantize_price(price, symbol=symbol)``
    3. Fall back to 2 decimals (backward-compatible default).

    Returns a string representation with appropriate decimal precision.
    """
    if ticksize is not None:
        q = quantize_price(price, ticksize=ticksize)
        d = _decimals_for_ticksize(ticksize)
        return f"{q:.{d}f}"
    if symbol is not None:
        sym = _norm_symbol(symbol)
        ts = SYMBOL_TICKSIZE.get(sym)
        if ts is not None:
            q = quantize_price(price, ticksize=ts)
            d = _decimals_for_ticksize(ts)
            return f"{q:.{d}f}"
    q = quantize_price(price, 2)
    return f"{q:.2f}"


def bos_id(
    symbol: str,
    timeframe: str,
    anchor_ts: float,
    kind: BosEventKind,
    dir: BosDir,
    price: float,
    *,
    ticksize: float | None = None,
) -> str:
    sym = _norm_symbol(symbol)
    t_anchor = int(quantize_time_to_tf(anchor_ts, timeframe))
    p = _quantize_for_id(price, symbol=sym, ticksize=ticksize)
    return f"bos:{sym}:{timeframe}:{t_anchor}:{kind}:{dir}:{p}"


def ob_id(
    symbol: str,
    timeframe: str,
    anchor_ts: float,
    dir: ObDir,
    low: float,
    high: float,
    *,
    ticksize: float | None = None,
) -> str:
    sym = _norm_symbol(symbol)
    t_anchor = int(quantize_time_to_tf(anchor_ts, timeframe))
    lo = _quantize_for_id(low, symbol=sym, ticksize=ticksize)
    hi = _quantize_for_id(high, symbol=sym, ticksize=ticksize)
    return f"ob:{sym}:{timeframe}:{t_anchor}:{dir}:{lo}:{hi}"


def fvg_id(
    symbol: str,
    timeframe: str,
    anchor_ts: float,
    dir: FvgDir,
    low: float,
    high: float,
    *,
    ticksize: float | None = None,
) -> str:
    sym = _norm_symbol(symbol)
    t_anchor = int(quantize_time_to_tf(anchor_ts, timeframe))
    lo = _quantize_for_id(low, symbol=sym, ticksize=ticksize)
    hi = _quantize_for_id(high, symbol=sym, ticksize=ticksize)
    return f"fvg:{sym}:{timeframe}:{t_anchor}:{dir}:{lo}:{hi}"


def sweep_id(
    symbol: str,
    timeframe: str,
    anchor_ts: float,
    side: SweepSide,
    price: float,
    *,
    ticksize: float | None = None,
) -> str:
    sym = _norm_symbol(symbol)
    t_anchor = int(quantize_time_to_tf(anchor_ts, timeframe))
    p = _quantize_for_id(price, symbol=sym, ticksize=ticksize)
    return f"sweep:{sym}:{timeframe}:{t_anchor}:{side}:{p}"