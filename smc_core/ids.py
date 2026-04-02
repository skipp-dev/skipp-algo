"""Deterministic event-ID generation with symbol-aware price quantization.

Price quantization resolution order (same for all ID functions):
1. Explicit ``ticksize`` kwarg → snap to nearest multiple.
2. Symbol lookup in ``SYMBOL_TICKSIZE`` → derive decimals from tick.
3. Explicit or inferred asset class → shared class ticksize.
4. Fall back to 2 decimals.

This means known futures/crypto symbols quantize to their contract tick,
forex pairs can infer 4-decimal pip precision, and callers can still force
asset-class defaults or explicit tick sizes end-to-end.
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

_FOREX_CODES = {"AUD", "CAD", "CHF", "EUR", "GBP", "JPY", "NZD", "USD"}

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


def _normalize_asset_class(asset_class: str) -> str:
    normalized = str(asset_class).strip().lower()
    if normalized not in _ASSET_CLASS_TICKSIZE:
        known = ", ".join(sorted(_ASSET_CLASS_TICKSIZE))
        raise ValueError(f"unsupported asset class: {asset_class!r}; expected one of: {known}")
    return normalized


def _infer_asset_class(symbol: str) -> str | None:
    compact = _norm_symbol(symbol).replace("/", "")
    if len(compact) == 6 and compact.isalpha() and compact[:3] in _FOREX_CODES and compact[3:] in _FOREX_CODES:
        return "forex"
    return None


def _resolve_ticksize(
    *,
    ticksize: float | None = None,
    symbol: str | None = None,
    asset_class: str | None = None,
) -> float | None:
    if ticksize is not None:
        if ticksize <= 0:
            raise ValueError("ticksize must be > 0")
        return ticksize

    if symbol is not None:
        sym = _norm_symbol(symbol)
        resolved = SYMBOL_TICKSIZE.get(sym)
        if resolved is not None:
            return resolved

    if asset_class is not None:
        return _ASSET_CLASS_TICKSIZE[_normalize_asset_class(asset_class)]

    if symbol is not None:
        inferred = _infer_asset_class(symbol)
        if inferred is not None:
            return _ASSET_CLASS_TICKSIZE[inferred]

    return None


def quantize_price(
    price: float,
    decimals: int = 2,
    *,
    ticksize: float | None = None,
    symbol: str | None = None,
    asset_class: str | None = None,
) -> float:
    """Quantize *price* to the nearest tick or decimal.

    Resolution order:
    1. Explicit *ticksize* parameter  →  snap to nearest multiple.
    2. *symbol* lookup in SYMBOL_TICKSIZE  →  derive decimals.
    3. *asset_class* default or inferred asset class  →  use class ticksize.
    4. Fall back to *decimals* parameter (backward-compatible default).
    """
    resolved_ticksize = _resolve_ticksize(ticksize=ticksize, symbol=symbol, asset_class=asset_class)
    if resolved_ticksize is not None:
        d = _decimals_for_ticksize(resolved_ticksize)
        tick_d = Decimal(str(resolved_ticksize))
        quantized = (Decimal(str(price)) / tick_d).quantize(Decimal(1), rounding=ROUND_HALF_UP) * tick_d
        return float(quantized.quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP))

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
    asset_class: str | None = None,
) -> str:
    """Quantize *price* for use in event IDs.

    Resolution order:
    1. Explicit *ticksize*  →  ``quantize_price(price, ticksize=ticksize)``
    2. *symbol* lookup      →  ``quantize_price(price, symbol=symbol)``
    3. *asset_class* or inferred asset class → shared default ticksize.
    4. Fall back to 2 decimals (backward-compatible default).

    Returns a string representation with appropriate decimal precision.
    """
    resolved_ticksize = _resolve_ticksize(ticksize=ticksize, symbol=symbol, asset_class=asset_class)
    if resolved_ticksize is not None:
        q = quantize_price(price, ticksize=resolved_ticksize)
        d = _decimals_for_ticksize(resolved_ticksize)
        return f"{q:.{d}f}"
    q = quantize_price(price, 2)
    return f"{q:.2f}"


def liquidity_id(
    symbol: str,
    timeframe: str,
    anchor_ts: float,
    side: SweepSide,
    price: float,
    *,
    ticksize: float | None = None,
    asset_class: str | None = None,
    session_tz: str | None = None,
) -> str:
    sym = _norm_symbol(symbol)
    _validate_timeframe(timeframe)
    t_anchor = int(anchor_ts)
    if timeframe == "1D":
        t_anchor = int(quantize_time_to_tf(anchor_ts, timeframe, session_tz=session_tz))
    p = _quantize_for_id(price, symbol=sym, ticksize=ticksize, asset_class=asset_class)
    return f"liq:{sym}:{timeframe}:{t_anchor}:{side}:{p}"


def bos_id(
    symbol: str,
    timeframe: str,
    anchor_ts: float,
    kind: BosEventKind,
    dir: BosDir,
    price: float,
    *,
    ticksize: float | None = None,
    asset_class: str | None = None,
    session_tz: str | None = None,
) -> str:
    sym = _norm_symbol(symbol)
    t_anchor = int(quantize_time_to_tf(anchor_ts, timeframe, session_tz=session_tz))
    p = _quantize_for_id(price, symbol=sym, ticksize=ticksize, asset_class=asset_class)
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
    asset_class: str | None = None,
    session_tz: str | None = None,
) -> str:
    sym = _norm_symbol(symbol)
    t_anchor = int(quantize_time_to_tf(anchor_ts, timeframe, session_tz=session_tz))
    lo = _quantize_for_id(low, symbol=sym, ticksize=ticksize, asset_class=asset_class)
    hi = _quantize_for_id(high, symbol=sym, ticksize=ticksize, asset_class=asset_class)
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
    asset_class: str | None = None,
    session_tz: str | None = None,
) -> str:
    sym = _norm_symbol(symbol)
    t_anchor = int(quantize_time_to_tf(anchor_ts, timeframe, session_tz=session_tz))
    lo = _quantize_for_id(low, symbol=sym, ticksize=ticksize, asset_class=asset_class)
    hi = _quantize_for_id(high, symbol=sym, ticksize=ticksize, asset_class=asset_class)
    return f"fvg:{sym}:{timeframe}:{t_anchor}:{dir}:{lo}:{hi}"


def sweep_id(
    symbol: str,
    timeframe: str,
    anchor_ts: float,
    side: SweepSide,
    price: float,
    *,
    ticksize: float | None = None,
    asset_class: str | None = None,
    session_tz: str | None = None,
) -> str:
    sym = _norm_symbol(symbol)
    t_anchor = int(quantize_time_to_tf(anchor_ts, timeframe, session_tz=session_tz))
    p = _quantize_for_id(price, symbol=sym, ticksize=ticksize, asset_class=asset_class)
    return f"sweep:{sym}:{timeframe}:{t_anchor}:{side}:{p}"