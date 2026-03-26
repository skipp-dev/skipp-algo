from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from scripts.explicit_structure_aux import (
    build_ipda_operating_range,
    build_session_pivots,
    build_session_ranges,
    compute_broken_fractal_signals,
    compute_htf_fvg_bias,
)
from scripts.explicit_structure_detectors import (
    detect_bos_choch_events,
    detect_fvg_classic,
    detect_liquidity_lines_pivot3,
    detect_liquidity_sweeps_from_lines,
    detect_orderblocks_makuchaku,
)
from scripts.smc_price_action_engine import canonical_timeframe, normalize_bars


@dataclass
class ProfileResult:
    bos: list[dict[str, Any]]
    orderblocks: list[dict[str, Any]]
    fvg: list[dict[str, Any]]
    liquidity_sweeps: list[dict[str, Any]]
    auxiliary: dict[str, Any]
    diagnostics: dict[str, Any]


def _dedupe_by_id(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        row_id = str(row.get("id", "")).strip()
        if not row_id or row_id in seen:
            continue
        seen.add(row_id)
        out.append(row)
    return out


def _empty_result() -> ProfileResult:
    return ProfileResult(
        bos=[],
        orderblocks=[],
        fvg=[],
        liquidity_sweeps=[],
        auxiliary={},
        diagnostics={},
    )


def _compose_common(bars: pd.DataFrame, symbol: str, timeframe: str, pivot_lookup: int) -> ProfileResult:
    if bars.empty:
        return _empty_result()

    bos = _dedupe_by_id(detect_bos_choch_events(bars, symbol=symbol, timeframe=timeframe, pivot_lookup=pivot_lookup))
    orderblocks, ob_diag = detect_orderblocks_makuchaku(bars, symbol=symbol, timeframe=timeframe)
    fvg, fvg_diag = detect_fvg_classic(bars, symbol=symbol, timeframe=timeframe)
    liquidity_lines = detect_liquidity_lines_pivot3(bars, symbol=symbol, timeframe=timeframe)
    liquidity_sweeps = detect_liquidity_sweeps_from_lines(bars, liquidity_lines=liquidity_lines, symbol=symbol, timeframe=timeframe)

    session_ranges = build_session_ranges(bars)
    session_pivots = build_session_pivots(session_ranges)
    ipda_range = build_ipda_operating_range(bars, timeframe=timeframe)
    htf_bias = compute_htf_fvg_bias(bars)
    broken_fractals = compute_broken_fractal_signals(bars)

    return ProfileResult(
        bos=_dedupe_by_id(bos),
        orderblocks=_dedupe_by_id(orderblocks),
        fvg=_dedupe_by_id(fvg),
        liquidity_sweeps=_dedupe_by_id(liquidity_sweeps),
        auxiliary={
            "session_ranges": session_ranges,
            "session_pivots": session_pivots,
            "liquidity_lines": liquidity_lines,
            "ipda_operating_range": ipda_range,
            "htf_fvg_bias": htf_bias,
            "broken_fractal_signals": broken_fractals,
        },
        diagnostics={
            "profile": "base",
            "orderblock_diagnostics": ob_diag,
            "fvg_diagnostics": fvg_diag,
            "liquidity_levels_count": len(liquidity_lines),
        },
    )


def _filter_confirmed_only(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if bool(row.get("valid", True)):
            out.append(row)
    return out


def _take_recent(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    if len(rows) <= limit:
        return rows
    return rows[-limit:]


def build_structure_profile(
    df: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    profile: str = "hybrid_default",
    pivot_lookup: int = 1,
) -> ProfileResult:
    bars = normalize_bars(df)
    if bars.empty:
        return _empty_result()

    tf = canonical_timeframe(timeframe)
    profile_name = str(profile).strip().lower() or "hybrid_default"

    base = _compose_common(bars, symbol=symbol, timeframe=tf, pivot_lookup=pivot_lookup)

    if profile_name == "classic_makuchaku":
        base.diagnostics["profile"] = "classic_makuchaku"
        return base

    if profile_name == "session_liquidity":
        base.orderblocks = []
        base.fvg = _take_recent(base.fvg, limit=50)
        base.liquidity_sweeps = _take_recent(base.liquidity_sweeps, limit=75)
        base.diagnostics["profile"] = "session_liquidity"
        return base

    if profile_name == "conservative":
        base.orderblocks = _filter_confirmed_only(base.orderblocks)
        base.fvg = _filter_confirmed_only(base.fvg)
        base.liquidity_sweeps = _take_recent(base.liquidity_sweeps, limit=50)
        base.diagnostics["profile"] = "conservative"
        return base

    # hybrid_default keeps all canonical families while trimming tail-heavy sweep noise.
    base.liquidity_sweeps = _take_recent(base.liquidity_sweeps, limit=100)
    base.diagnostics["profile"] = "hybrid_default"
    return base
