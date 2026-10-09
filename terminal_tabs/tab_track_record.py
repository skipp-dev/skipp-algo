"""Tab: Track Record — C7/T3 dashboard tab.

This module is split into:

* :func:`build_summary` — pure-Python function that turns a dashboard
  payload (from :func:`scripts.build_dashboard_payload.build_dashboard_payload`)
  into the ready-to-render summary blocks.  Has no Streamlit imports
  and is fully unit-testable.
* :func:`render` — Streamlit entry point.  Only imported when Streamlit
  is available so the rest of the codebase / test suite is not forced
  to install it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

__all__ = [
    "GATE_BADGE",
    "build_summary",
    "format_variant_row",
    "render",
]

# UI-agnostic gate → emoji badge mapping.  Used by :func:`render` and
# pinned by tests so a downstream rename can't silently change the
# dashboard colour-coding.
GATE_BADGE: dict[str, str] = {
    "green": "🟢",
    "amber": "🟡",
    "red": "🔴",
    "unknown": "⚪",
}

_TABLE_COLUMNS: tuple[str, ...] = (
    "variant",
    "n",
    "hit_rate",
    "sharpe",
    "sharpe_ci_low",
    "sharpe_ci_high",
    "permutation_p",
    "psr",
    "wfe",
    "max_dd",
    "gate_status",
)


def _coerce_optional_float(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None  # filter NaN


def _coerce_optional_int(x: Any) -> int | None:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def format_variant_row(variant: Mapping[str, Any]) -> dict[str, Any]:
    """Project a payload variant down to the table-friendly columns.

    Missing keys become ``None`` rather than raising — the dashboard
    must keep rendering even when an upstream artifact is partial.
    """
    return {
        "variant": str(variant.get("variant", "")),
        "n": _coerce_optional_int(variant.get("n_trades")),
        "hit_rate": _coerce_optional_float(variant.get("hit_rate")),
        "sharpe": _coerce_optional_float(variant.get("sharpe")),
        "sharpe_ci_low": _coerce_optional_float(variant.get("sharpe_ci_low")),
        "sharpe_ci_high": _coerce_optional_float(variant.get("sharpe_ci_high")),
        "permutation_p": _coerce_optional_float(variant.get("permutation_p_value")),
        "psr": _coerce_optional_float(variant.get("psr")),
        "wfe": _coerce_optional_float(variant.get("walk_forward_efficiency")),
        "max_dd": _coerce_optional_float(variant.get("max_drawdown")),
        "gate_status": str(variant.get("gate_status") or "unknown"),
    }


def _gate_failures(variant: Mapping[str, Any]) -> list[str]:
    """Return the human-readable reasons why a variant is gated red."""
    failures = variant.get("gate_failures") or variant.get("failures")
    if isinstance(failures, list):
        return [str(f) for f in failures if isinstance(f, (str, Mapping))]
    return []


def build_summary(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Build the table + headline blocks the dashboard renders.

    Returns a dict with keys ``status`` (``ok`` or ``empty``),
    ``as_of_date``, ``totals``, ``rows`` and ``red_failures``.  The
    ``ok`` branch always carries a non-empty ``rows`` list when at
    least one variant is present.
    """
    if not payload or not payload.get("variants"):
        return {
            "status": "empty",
            "as_of_date": None if not payload else payload.get("as_of_date"),
            "totals": {"green": 0, "amber": 0, "red": 0, "unknown": 0, "total": 0},
            "rows": [],
            "red_failures": [],
            "warnings": list((payload or {}).get("warnings") or []),
        }

    variants = list(payload.get("variants") or [])
    rows = [format_variant_row(v) for v in variants]
    totals = _totals(variants)
    red_failures = [
        {"variant": str(v.get("variant", "")), "failures": _gate_failures(v)}
        for v in variants
        if str(v.get("gate_status") or "").lower() == "red"
    ]

    return {
        "status": "ok",
        "as_of_date": payload.get("as_of_date"),
        "totals": totals,
        "rows": rows,
        "red_failures": red_failures,
        "warnings": list(payload.get("warnings") or []),
    }


def _totals(variants: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {"green": 0, "amber": 0, "red": 0, "unknown": 0, "total": 0}
    for v in variants:
        status = str(v.get("gate_status") or "unknown").lower()
        if status not in counts:
            status = "unknown"
        counts[status] += 1
        counts["total"] += 1
    return counts


# ── Streamlit entry point ──────────────────────────────────────────


def render(payload: Mapping[str, Any] | None) -> None:  # pragma: no cover
    """Render the Track-Record tab inside a Streamlit app.

    Imports Streamlit lazily so the rest of the codebase stays
    importable in environments without it.
    """
    import streamlit as st

    summary = build_summary(payload)
    st.subheader("📊 Track Record")
    if summary["status"] == "empty":
        st.info("No track-record artifact available yet.")
        for w in summary["warnings"]:
            st.caption(f"⚠️ {w}")
        return

    st.caption(f"As of: {summary['as_of_date']}")
    totals = summary["totals"]
    cols = st.columns(4)
    cols[0].metric("Total", totals["total"])
    cols[1].metric(f"{GATE_BADGE['green']} Green", totals["green"])
    cols[2].metric(f"{GATE_BADGE['amber']} Amber", totals["amber"])
    cols[3].metric(f"{GATE_BADGE['red']} Red", totals["red"])

    st.dataframe(summary["rows"], use_container_width=True)

    if summary["red_failures"]:
        st.subheader("Gate failures (red)")
        for entry in summary["red_failures"]:
            st.markdown(f"**{entry['variant']}**")
            for f in entry["failures"]:
                st.markdown(f"- {f}")

    for w in summary["warnings"]:
        st.caption(f"⚠️ {w}")
