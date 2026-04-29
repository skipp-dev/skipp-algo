"""Tab: Live Incubation — C7/T6 stub for the C8 live data feed.

Pure-Python :func:`build_live_view` projects the C8 drift artifact
(``cache/live/drift_<date>.json``) into the placeholder table the
dashboard renders.  The schema is locked here so the C8 sprint can
fill in the data without re-touching the UI.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

__all__ = [
    "DRIFT_HISTORY_DEFAULT_N",
    "VERDICT_BADGE",
    "build_drift_history_view",
    "build_live_view",
    "format_drift_history_row",
    "format_live_row",
    "render",
]

# Local default to keep this module importable even if the
# (newer) ``terminal_tabs.drift_loader.load_recent_drift_artifacts``
# helper has not yet landed. Mirrors the constant exported by that
# loader so the two stay in sync.
DRIFT_HISTORY_DEFAULT_N = 7

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
    """Project one drift-artifact variant onto the table-friendly columns.

    The C-sprint deep-review surfaced ``slippage_ks_reference_type`` here
    so dashboard operators can see whether a row's slippage K-S was
    computed against real backtest samples or the ``synthetic_normal``
    fallback. Phase-B sign-off requires ``backtest_samples``; the row
    keeps the literal so the UI can render a warning badge for
    synthetic-only rows instead of silently letting them look healthy.
    """
    live_sharpe = _coerce_optional_float(variant.get("live_sharpe"))
    backtest_sharpe = _coerce_optional_float(variant.get("backtest_sharpe"))
    drift_pp: float | None
    drift_pp = live_sharpe - backtest_sharpe if live_sharpe is not None and backtest_sharpe is not None else None
    slippage_ref = variant.get("slippage_ks_reference_type")
    return {
        "variant": str(variant.get("variant", "")),
        "backtest_sharpe": backtest_sharpe,
        "live_sharpe": live_sharpe,
        "drift_pp": drift_pp,
        "live_trades": _coerce_optional_int(variant.get("n_live_trades")),
        "verdict": str(variant.get("verdict") or "insufficient_sample"),
        "slippage_ks_reference_type": (str(slippage_ref) if slippage_ref is not None else "unavailable"),
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
            "notice": ("Live-Inkubation startet in Sprint C8. Aktuell keine Live-Daten."),
            "rows": [],
            "totals": {k: 0 for k in VERDICT_BADGE} | {"total": 0},
        }

    variants = list(payload.get("variants") or [])
    rows = [format_live_row(v) for v in variants]
    # C-sprint deep-review pass-2: aggregate the slippage-reference flag
    # so the dashboard can render a single "Phase-A only — slippage uses
    # synthetic_normal fallback" banner. Phase-B sign-off is gated on
    # ``backtest_samples`` (machine-checked in PHASE_B_CRITERIA.extra).
    has_synthetic = any(r.get("slippage_ks_reference_type") == "synthetic_normal" for r in rows)
    has_unavailable = any(r.get("slippage_ks_reference_type") == "unavailable" for r in rows)
    return {
        "status": "ok",
        "computed_at": payload.get("computed_at"),
        "live_window_days": payload.get("live_window_days"),
        "rows": rows,
        "totals": _verdict_totals(variants),
        "slippage_reference_warning": (
            "synthetic_normal" if has_synthetic else ("unavailable" if has_unavailable else None)
        ),
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


# ---------------------------------------------------------------------------
# Drift history panel (C13/T2 dashboard wiring)
# ---------------------------------------------------------------------------


def format_drift_history_row(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Project one drift artifact into one row of the last-N history table.

    The history panel is per-day (one row = one ``cache/live/drift_<date>.json``).
    The columns are intentionally summary-grade — drill-down stays in the
    main per-variant table built by :func:`build_live_view`.
    """
    variants = artifact.get("variants") or []
    if not isinstance(variants, list):
        variants = []
    rows = [format_live_row(v) for v in variants if isinstance(v, Mapping)]
    totals = _verdict_totals(rows)
    failing = totals.get("fail", 0) + totals.get("concerning", 0)
    return {
        "as_of_date": str(artifact.get("as_of_date") or ""),
        "computed_at": artifact.get("computed_at"),
        "live_window_days": _coerce_optional_int(artifact.get("live_window_days")),
        "n_variants": totals.get("total", 0),
        "n_pass": totals.get("pass", 0),
        "n_acceptable": totals.get("acceptable", 0),
        "n_concerning": totals.get("concerning", 0),
        "n_fail": totals.get("fail", 0),
        "n_insufficient_sample": totals.get("insufficient_sample", 0),
        "n_failing": failing,
    }


def build_drift_history_view(
    artifacts: Sequence[Mapping[str, Any]] | None,
    *,
    n: int = DRIFT_HISTORY_DEFAULT_N,
) -> dict[str, Any]:
    """Project a list of drift artifacts into the history-panel view block.

    Input contract mirrors
    :func:`terminal_tabs.drift_loader.load_recent_drift_artifacts`:
    *newest first*, each item carries ``as_of_date`` (string) plus the
    full drift-artifact payload. ``None`` / empty input renders the
    awaiting-data state — same UX as :func:`build_live_view`.

    The output ``rows`` list is also newest-first so the dashboard
    can render the most-recent day on top without further sorting.
    """
    if not artifacts:
        return {
            "status": "awaiting_c8",
            "n_requested": int(n),
            "rows": [],
            "notice": ("Live-Inkubation startet in Sprint C8. Aktuell keine Drift-Historie."),
        }
    # Defensive truncation — if the caller passed more than ``n`` we
    # still respect the panel size.
    rows = [format_drift_history_row(a) for a in list(artifacts)[: int(n)]]
    return {
        "status": "ok",
        "n_requested": int(n),
        "n_rendered": len(rows),
        "rows": rows,
    }


def _load_recent_drift_artifacts_from_disk(
    cache_dir: str,
    *,
    n: int,
) -> list[dict[str, Any]]:
    """Self-sufficient fallback that mirrors
    :func:`terminal_tabs.drift_loader.load_recent_drift_artifacts`.

    Used when the (newer) loader helper has not yet landed on the
    consumer's branch — keeps this PR mergable independently.
    """
    from terminal_tabs.drift_loader import (
        list_drift_dates,
        load_drift_artifact,
    )

    dates = list_drift_dates(cache_dir)
    if not dates:
        return []
    out: list[dict[str, Any]] = []
    # ``list_drift_dates`` returns ASC; we want newest first.
    for d in reversed(dates[-int(n) :]):
        payload = load_drift_artifact(cache_dir, as_of_date=d)
        if payload is None:
            continue
        # Augment with as_of_date so the panel can render it without
        # re-deriving from the filename.
        payload = dict(payload)
        payload.setdefault("as_of_date", d)
        out.append(payload)
    return out


def render_drift_history(  # pragma: no cover
    cache_dir: str = "cache",
    *,
    n: int = DRIFT_HISTORY_DEFAULT_N,
) -> None:
    """Render the last-``n`` drift-history panel inside a Streamlit app.

    Prefers the dedicated
    :func:`terminal_tabs.drift_loader.load_recent_drift_artifacts`
    helper when present; otherwise falls back to a local equivalent
    so this panel is usable on any branch where the loader's older
    primitives (``list_drift_dates`` + ``load_drift_artifact``) are
    available.
    """
    import streamlit as st

    try:
        from terminal_tabs.drift_loader import (  # type: ignore[attr-defined]
            load_recent_drift_artifacts,
        )

        artifacts = load_recent_drift_artifacts(cache_dir, n=n)
    except ImportError:
        artifacts = _load_recent_drift_artifacts_from_disk(cache_dir, n=n)

    view = build_drift_history_view(artifacts, n=n)
    st.subheader("📜 Drift-Historie (letzte 7 Tage)")
    if view["status"] == "awaiting_c8":
        st.info(view["notice"])
        return
    st.caption(f"Zeige {view['n_rendered']} von angeforderten {view['n_requested']} Tagen (neueste zuerst).")
    st.dataframe(view["rows"], use_container_width=True)
