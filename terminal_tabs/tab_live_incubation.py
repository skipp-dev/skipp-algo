"""Tab: Live Incubation — C7/T6 stub for the C8 live data feed.

Pure-Python :func:`build_live_view` projects the C8 drift artifact
(``cache/live/drift_<date>.json``) into the placeholder table the
dashboard renders.  The schema is locked here so the C8 sprint can
fill in the data without re-touching the UI.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

__all__ = [
    "VERDICT_BADGE",
    "build_live_view",
    "format_live_row",
    "render",
]

VERDICT_BADGE: dict[str, str] = {
    "pass": "🟢",
    "acceptable": "🟡",
    "concerning": "🟠",
    "fail": "🔴",
    "insufficient_sample": "⚪",
}


def _coerce_optional_float(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _coerce_optional_int(x: Any) -> int | None:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def format_live_row(variant: Mapping[str, Any]) -> dict[str, Any]:
    """Project one drift-artifact variant onto the table-friendly columns."""
    live_sharpe = _coerce_optional_float(variant.get("live_sharpe"))
    backtest_sharpe = _coerce_optional_float(variant.get("backtest_sharpe"))
    drift_pp: float | None
    if live_sharpe is not None and backtest_sharpe is not None:
        drift_pp = live_sharpe - backtest_sharpe
    else:
        drift_pp = None
    return {
        "variant": str(variant.get("variant", "")),
        "backtest_sharpe": backtest_sharpe,
        "live_sharpe": live_sharpe,
        "drift_pp": drift_pp,
        "live_trades": _coerce_optional_int(variant.get("n_live_trades")),
        "verdict": str(variant.get("verdict") or "insufficient_sample"),
    }


def _verdict_totals(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counts = {k: 0 for k in VERDICT_BADGE}
    counts["total"] = 0
    for r in rows:
        verdict = str(r.get("verdict") or "insufficient_sample")
        if verdict not in counts:
            verdict = "insufficient_sample"
        counts[verdict] += 1
        counts["total"] += 1
    return counts


def build_live_view(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Build the placeholder + (eventual) live-data view block.

    When ``payload`` is empty or missing variants the view returns
    ``status="awaiting_c8"`` plus the static notice the C7-stub
    should display.
    """
    if not payload or not payload.get("variants"):
        return {
            "status": "awaiting_c8",
            "computed_at": (payload or {}).get("computed_at"),
            "notice": (
                "Live-Inkubation startet in Sprint C8. "
                "Aktuell keine Live-Daten."
            ),
            "rows": [],
            "totals": {k: 0 for k in VERDICT_BADGE} | {"total": 0},
        }

    variants = list(payload.get("variants") or [])
    rows = [format_live_row(v) for v in variants]
    return {
        "status": "ok",
        "computed_at": payload.get("computed_at"),
        "live_window_days": payload.get("live_window_days"),
        "rows": rows,
        "totals": _verdict_totals(variants),
    }


def render(payload: Mapping[str, Any] | None) -> None:  # pragma: no cover
    """Render the Live-Incubation tab inside a Streamlit app."""
    import streamlit as st

    view = build_live_view(payload)
    st.subheader("🛰️ Live Incubation")
    if view["status"] == "awaiting_c8":
        st.info(view["notice"])
        return
    st.caption(f"Computed at: {view['computed_at']} (window {view['live_window_days']}d)")
    cols = st.columns(len(VERDICT_BADGE))
    for i, (verdict, badge) in enumerate(VERDICT_BADGE.items()):
        cols[i].metric(f"{badge} {verdict}", view["totals"].get(verdict, 0))
    st.dataframe(view["rows"], use_container_width=True)
