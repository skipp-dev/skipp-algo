from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from .types import BosDir, BosEventKind, FvgDir, ObDir, SweepSide

_TIMEFRAME_TO_SECONDS = {
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1H": 60 * 60,
    "4H": 240 * 60,
    "1D": 1440 * 60,
}


def _norm_symbol(symbol: str) -> str:
    return symbol.upper().strip()


def _validate_timeframe(timeframe: str) -> int:
    try:
        return _TIMEFRAME_TO_SECONDS[timeframe]
    except KeyError as exc:
        raise ValueError(f"unsupported timeframe: {timeframe}") from exc


def quantize_price(price: float, decimals: int = 2) -> float:
    if decimals < 0:
        raise ValueError("decimals must be >= 0")
    quantum = Decimal(1).scaleb(-decimals)
    return float(Decimal(str(price)).quantize(quantum, rounding=ROUND_HALF_UP))


def quantize_time_to_tf(epoch_sec: float, timeframe: str) -> float:
    # TODO: 1D currently uses UTC block anchoring in Phase 1.
    # Exchange/session-aware daily anchoring can be introduced later.
    block = _validate_timeframe(timeframe)
    seconds = int(epoch_sec)
    return float(seconds - (seconds % block))


def bos_id(
    symbol: str,
    timeframe: str,
    anchor_ts: float,
    kind: BosEventKind,
    dir: BosDir,
    price: float,
) -> str:
    sym = _norm_symbol(symbol)
    t_anchor = int(quantize_time_to_tf(anchor_ts, timeframe))
    p = quantize_price(price, 2)
    return f"bos:{sym}:{timeframe}:{t_anchor}:{kind}:{dir}:{p:.2f}"


def ob_id(
    symbol: str,
    timeframe: str,
    anchor_ts: float,
    dir: ObDir,
    low: float,
    high: float,
) -> str:
    sym = _norm_symbol(symbol)
    t_anchor = int(quantize_time_to_tf(anchor_ts, timeframe))
    lo = quantize_price(low, 2)
    hi = quantize_price(high, 2)
    return f"ob:{sym}:{timeframe}:{t_anchor}:{dir}:{lo:.2f}:{hi:.2f}"


def fvg_id(
    symbol: str,
    timeframe: str,
    anchor_ts: float,
    dir: FvgDir,
    low: float,
    high: float,
) -> str:
    sym = _norm_symbol(symbol)
    t_anchor = int(quantize_time_to_tf(anchor_ts, timeframe))
    lo = quantize_price(low, 2)
    hi = quantize_price(high, 2)
    return f"fvg:{sym}:{timeframe}:{t_anchor}:{dir}:{lo:.2f}:{hi:.2f}"


def sweep_id(
    symbol: str,
    timeframe: str,
    anchor_ts: float,
    side: SweepSide,
    price: float,
) -> str:
    sym = _norm_symbol(symbol)
    t_anchor = int(quantize_time_to_tf(anchor_ts, timeframe))
    p = quantize_price(price, 2)
    return f"sweep:{sym}:{timeframe}:{t_anchor}:{side}:{p:.2f}"