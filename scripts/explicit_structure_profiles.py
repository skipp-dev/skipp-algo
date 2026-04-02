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

SUPPORTED_STRUCTURE_PROFILES = {
    "classic_makuchaku",
    "session_liquidity",
    "hybrid_default",
    "conservative",
}
EVENT_LOGIC_VERSION = "v2"


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
    diagnostics = {
        "structure_profile_used": "hybrid_default",
        "event_logic_version": EVENT_LOGIC_VERSION,
        "counts": {
            "bos": 0,
            "orderblocks": 0,
            "fvg": 0,
            "liquidity_sweeps": 0,
            "liquidity_lines": 0,
            "session_ranges": 0,
            "session_pivots": 0,
            "broken_fractal_signals": 0,
        },
        "warnings": [],
        "notes": [],
        "orderblock_diagnostics": [],
        "fvg_diagnostics": [],
        "liquidity_levels_count": 0,
    }
    return ProfileResult(
        bos=[],
        orderblocks=[],
        fvg=[],
        liquidity_sweeps=[],
        auxiliary={},
        diagnostics=diagnostics,
    )


def validate_structure_profile(profile: str) -> str:
    normalized = str(profile).strip().lower() or "hybrid_default"
    if normalized not in SUPPORTED_STRUCTURE_PROFILES:
        known = ", ".join(sorted(SUPPORTED_STRUCTURE_PROFILES))
        raise ValueError(f"unknown structure profile {profile!r}; expected one of: {known}")
    return normalized


def _diagnostics_counts(
    *,
    bos: list[dict[str, Any]],
    orderblocks: list[dict[str, Any]],
    fvg: list[dict[str, Any]],
    liquidity_sweeps: list[dict[str, Any]],
    liquidity_lines: list[dict[str, Any]],
    session_ranges: list[dict[str, Any]],
    session_pivots: list[dict[str, Any]],
    broken_fractals: list[dict[str, Any]],
) -> dict[str, int]:
    return {
        "bos": len(bos),
        "orderblocks": len(orderblocks),
        "fvg": len(fvg),
        "liquidity_sweeps": len(liquidity_sweeps),
        "liquidity_lines": len(liquidity_lines),
        "session_ranges": len(session_ranges),
        "session_pivots": len(session_pivots),
        "broken_fractal_signals": len(broken_fractals),
    }


def _compose_common(
    bars: pd.DataFrame,
    symbol: str,
    timeframe: str,
    pivot_lookup: int,
    *,
    ticksize: float | None = None,
    asset_class: str | None = None,
    session_tz: str | None = None,
) -> ProfileResult:
    if bars.empty:
        return _empty_result()

    bos = _dedupe_by_id(
        detect_bos_choch_events(
            bars,
            symbol=symbol,
            timeframe=timeframe,
            pivot_lookup=pivot_lookup,
            ticksize=ticksize,
            asset_class=asset_class,
            session_tz=session_tz,
        )
    )
    orderblocks, ob_diag = detect_orderblocks_makuchaku(
        bars,
        symbol=symbol,
        timeframe=timeframe,
        ticksize=ticksize,
        asset_class=asset_class,
        session_tz=session_tz,
    )
    fvg, fvg_diag = detect_fvg_classic(
        bars,
        symbol=symbol,
        timeframe=timeframe,
        ticksize=ticksize,
        asset_class=asset_class,
        session_tz=session_tz,
    )
    liquidity_lines = detect_liquidity_lines_pivot3(
        bars,
        symbol=symbol,
        timeframe=timeframe,
        ticksize=ticksize,
        asset_class=asset_class,
        session_tz=session_tz,
    )
    liquidity_sweeps = detect_liquidity_sweeps_from_lines(
        bars,
        liquidity_lines=liquidity_lines,
        symbol=symbol,
        timeframe=timeframe,
        ticksize=ticksize,
        asset_class=asset_class,
        session_tz=session_tz,
    )

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
            "ipda_range": ipda_range,
            "htf_fvg_bias": htf_bias,
            "broken_fractal_signals": broken_fractals,
        },
        diagnostics={
            "structure_profile_used": "base",
            "event_logic_version": EVENT_LOGIC_VERSION,
            "counts": _diagnostics_counts(
                bos=bos,
                orderblocks=orderblocks,
                fvg=fvg,
                liquidity_sweeps=liquidity_sweeps,
                liquidity_lines=liquidity_lines,
                session_ranges=session_ranges,
                session_pivots=session_pivots,
                broken_fractals=broken_fractals,
            ),
            "warnings": [],
            "notes": [],
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
    ticksize: float | None = None,
    asset_class: str | None = None,
    session_tz: str | None = None,
) -> ProfileResult:
    bars = normalize_bars(df)
    if bars.empty:
        return _empty_result()

    tf = canonical_timeframe(timeframe)
    profile_name = validate_structure_profile(profile)

    base = _compose_common(
        bars,
        symbol=symbol,
        timeframe=tf,
        pivot_lookup=pivot_lookup,
        ticksize=ticksize,
        asset_class=asset_class,
        session_tz=session_tz,
    )

    if profile_name == "classic_makuchaku":
        base.diagnostics["structure_profile_used"] = "classic_makuchaku"
        return base

    if profile_name == "session_liquidity":
        base.orderblocks = []
        base.fvg = _take_recent(base.fvg, limit=50)
        base.liquidity_sweeps = _take_recent(base.liquidity_sweeps, limit=75)
        base.diagnostics["structure_profile_used"] = "session_liquidity"
        base.diagnostics["counts"] = _diagnostics_counts(
            bos=base.bos,
            orderblocks=base.orderblocks,
            fvg=base.fvg,
            liquidity_sweeps=base.liquidity_sweeps,
            liquidity_lines=list(base.auxiliary.get("liquidity_lines", [])),
            session_ranges=list(base.auxiliary.get("session_ranges", [])),
            session_pivots=list(base.auxiliary.get("session_pivots", [])),
            broken_fractals=list(base.auxiliary.get("broken_fractal_signals", [])),
        )
        return base

    if profile_name == "conservative":
        base.orderblocks = _filter_confirmed_only(base.orderblocks)
        base.fvg = _filter_confirmed_only(base.fvg)
        base.liquidity_sweeps = _take_recent(base.liquidity_sweeps, limit=50)
        base.diagnostics["structure_profile_used"] = "conservative"
        base.diagnostics["counts"] = _diagnostics_counts(
            bos=base.bos,
            orderblocks=base.orderblocks,
            fvg=base.fvg,
            liquidity_sweeps=base.liquidity_sweeps,
            liquidity_lines=list(base.auxiliary.get("liquidity_lines", [])),
            session_ranges=list(base.auxiliary.get("session_ranges", [])),
            session_pivots=list(base.auxiliary.get("session_pivots", [])),
            broken_fractals=list(base.auxiliary.get("broken_fractal_signals", [])),
        )
        return base

    # hybrid_default keeps all canonical families while trimming tail-heavy sweep noise.
    base.liquidity_sweeps = _take_recent(base.liquidity_sweeps, limit=100)
    base.diagnostics["structure_profile_used"] = "hybrid_default"
    base.diagnostics["counts"] = _diagnostics_counts(
        bos=base.bos,
        orderblocks=base.orderblocks,
        fvg=base.fvg,
        liquidity_sweeps=base.liquidity_sweeps,
        liquidity_lines=list(base.auxiliary.get("liquidity_lines", [])),
        session_ranges=list(base.auxiliary.get("session_ranges", [])),
        session_pivots=list(base.auxiliary.get("session_pivots", [])),
        broken_fractals=list(base.auxiliary.get("broken_fractal_signals", [])),
    )
    return base
