"""Amendment A1.C — Pine codegen for the tri-axis FVG health dashboard.

Consumes the JSON output of
:func:`smc_core.benchmark.stratified_fvg_report` and produces a
deterministic Pine v5 snippet of ``export const string`` declarations
that the ``SMC_Core_Engine.pine`` dashboard can reference for the
``show_fvg_tri_axis`` toggle.

Token scheme (one constant per session × vol_regime cell, htf_bias
collapsed to KEY_ALL because the existing dashboard only has room for
two-axis cells):

    string FVG_HEALTH_<SESSION>_<VOLREGIME> = "<HR_PCT>% (n=<N>)"
    string FVG_HEALTH_<SESSION>_<VOLREGIME>_STATUS = "<OK|WARN|INSUF>"

Determinism contract: identical input report → byte-identical output.
The function never raises on partial input; missing buckets fall back
to ``"insufficient (n=<N>)"`` strings that the dashboard can choose to
hide via the existing ``show_fvg_tri_axis`` toggle.

This module ONLY emits text — it never touches the
``SMC_Core_Engine.pine`` source file. Wiring the constants into the
dashboard's label rows is a separate (manual) Pine change so it can go
through TradingView's compile-only preflight.
"""

from __future__ import annotations

from typing import Any

PINE_PREFIX = "FVG_HEALTH"


def _safe_token(raw: object) -> str:
    """Normalise a context value to a Pine identifier-safe token.

    Accepts any input; ``str(raw)`` is called to coerce non-string values
    (``int``, ``bool``, ``None``, ...) before normalisation.
    """
    cleaned = "".join(ch for ch in str(raw).upper() if ch.isalnum() or ch == "_")
    return cleaned or "UNKNOWN"


def _aggregate_session_vol(report: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """Collapse the tri-axis report to (session × vol_regime) cells."""
    by_cell: dict[tuple[str, str], dict[str, Any]] = {}
    for bucket in report.get("buckets") or []:
        session = _safe_token(bucket.get("session", "UNKNOWN"))
        vol = _safe_token(bucket.get("vol_regime", "UNKNOWN"))
        n_events = int(bucket.get("n_events", 0) or 0)
        hits = int(bucket.get("hits", 0) or 0)
        cell = by_cell.setdefault(
            (session, vol),
            {"n_events": 0, "hits": 0, "buckets": 0},
        )
        cell["n_events"] += n_events
        cell["hits"] += hits
        cell["buckets"] += 1
    return by_cell


def _status_for(hit_rate: float | None, n_events: int, *, min_events: int) -> str:
    if n_events < min_events or hit_rate is None:
        return "INSUF"
    if hit_rate >= 0.70:
        return "OK"
    if hit_rate >= 0.55:
        return "WARN"
    return "WEAK"


def emit_fvg_pine_constants(report: dict[str, Any]) -> list[str]:
    """Return a deterministic list of Pine const declarations.

    The list is sorted by ``(session, vol_regime)`` so two runs against
    the same report produce byte-identical output.
    """
    min_events = int(report.get("min_events", 12))
    cells = _aggregate_session_vol(report)
    lines: list[str] = ["// ── FVG Tri-Axis Health (Amendment A1.C) ──"]
    for (session, vol), cell in sorted(cells.items()):
        n_events = cell["n_events"]
        hits = cell["hits"]
        hit_rate = (hits / n_events) if n_events > 0 else None
        if n_events < min_events or hit_rate is None:
            value = f"insufficient (n={n_events})"
        else:
            value = f"{round(hit_rate * 100):d}% (n={n_events})"
        status = _status_for(hit_rate, n_events, min_events=min_events)
        ident = f"{PINE_PREFIX}_{session}_{vol}"
        lines.append(f'export const string {ident} = "{value}"')
        lines.append(f'export const string {ident}_STATUS = "{status}"')
    return lines


def emit_fvg_pine_block(report: dict[str, Any]) -> str:
    """Convenience: ``emit_fvg_pine_constants`` joined with newlines."""
    return "\n".join(emit_fvg_pine_constants(report))
