"""Methodology drawer — C7/T5 sticky-sidebar content.

Pure-Python :func:`build_methodology` returns the source-link list,
the gate threshold table, and the data-freshness indicator the
dashboard sidebar renders.  Has no Streamlit imports so the link
catalogue can be unit-tested for URL hygiene.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

# Single-source the PSR threshold from the gate module so the sidebar
# rationale and the gate decision can never drift apart (C6 deep-review
# finding: hardcoded 0.95 here was a literal duplicate of
# scripts.track_record_gate.MIN_PSR).
try:
    from scripts.track_record_gate import MIN_PSR as _MIN_PSR_FROM_GATE
except Exception:  # pragma: no cover - import-shim safety
    _MIN_PSR_FROM_GATE = 0.95

__all__ = [
    "GATE_THRESHOLDS",
    "SOURCE_LINKS",
    "SPRINT_PLAN_LINKS",
    "build_methodology",
    "freshness_label",
    "render_sidebar",
]

# Locked source catalogue.  Any change here is visible on the public
# dashboard, so it stays test-pinned.
SOURCE_LINKS: tuple[tuple[str, str], ...] = (
    (
        "Bailey & López de Prado (2012) — Sharpe Indeterminacy",
        "http://boston.qwafafew.org/wp-content/uploads/sites/4/2017/01/Lopez_de_Prado_Sharpe.pdf",
    ),
    (
        "Bailey & López de Prado (2014) — Deflated Sharpe Ratio",
        "https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf",
    ),
    (
        "Politis & Romano — Stationary Bootstrap",
        "https://en.wikipedia.org/wiki/Bootstrapping_(statistics)",
    ),
)

SPRINT_PLAN_LINKS: tuple[tuple[str, str], ...] = (
    ("C2 — Walk-Forward", "docs/SPRINT_PLAN_C2_WALK_FORWARD_2026-04-26.md"),
    ("C3 — Bootstrap CIs", "docs/SPRINT_PLAN_C3_BOOTSTRAP_CI_2026-04-26.md"),
    ("C4 — Permutation Null", "docs/SPRINT_PLAN_C4_PERMUTATION_TEST_2026-04-26.md"),
    (
        "C5 — Regime Stratification",
        "docs/SPRINT_PLAN_C5_REGIME_STRATIFICATION_2026-04-26.md",
    ),
    ("C6 — PSR + MinTRL", "docs/SPRINT_PLAN_C6_PSR_MINTRL_2026-04-26.md"),
    ("C7 — Dashboard", "docs/SPRINT_PLAN_C7_DASHBOARD_2026-04-26.md"),
    ("C8 — Live Incubation", "docs/SPRINT_PLAN_C8_LIVE_INCUBATION_2026-04-26.md"),
    ("C9 — Drift Alerts", "docs/SPRINT_PLAN_C9_DRIFT_ALERT_2026-04-26.md"),
)

GATE_THRESHOLDS: tuple[dict[str, Any], ...] = (
    {"name": "min_trades", "value": 30, "rationale": "C8 minimum sample size"},
    {"name": "min_sharpe", "value": 0.5, "rationale": "live ÷ backtest ≥ 0.5"},
    # min_psr value sourced from scripts.track_record_gate.MIN_PSR
    # (single source of truth — keep in sync if the constant changes).
    {
        "name": "min_psr",
        "value": _MIN_PSR_FROM_GATE,
        "rationale": "Bailey-LdP 2012 threshold",
    },
    {"name": "perm_p_max", "value": 0.05, "rationale": "C4 default α"},
    {
        "name": "drift_score_min_acceptable",
        "value": 0.65,
        "rationale": "C8/T4 verdict band",
    },
)


def freshness_label(
    *,
    computed_at: str | None,
    now: datetime | None = None,
    stale_after: timedelta = timedelta(hours=24),
) -> str:
    """Return a fresh / stale indicator string for the sidebar.

    Returns ``"unknown"`` if ``computed_at`` is missing or unparseable,
    ``"stale"`` if the artifact is older than ``stale_after``, otherwise
    ``"fresh"``.
    """
    if not computed_at:
        return "unknown"
    try:
        ts = datetime.fromisoformat(computed_at)
    except ValueError:
        return "unknown"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    moment = now or datetime.now(UTC)
    return "fresh" if (moment - ts) < stale_after else "stale"


def build_methodology(
    payload: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assemble the sidebar payload.

    Returns a dict with ``sources``, ``sprint_plans``, ``thresholds``,
    ``computed_at`` and ``freshness``.
    """
    computed_at = (payload or {}).get("computed_at")
    return {
        "sources": [{"label": lbl, "url": url} for lbl, url in SOURCE_LINKS],
        "sprint_plans": [
            {"label": lbl, "path": path} for lbl, path in SPRINT_PLAN_LINKS
        ],
        "thresholds": [dict(t) for t in GATE_THRESHOLDS],
        "computed_at": computed_at,
        "freshness": freshness_label(computed_at=computed_at, now=now),
    }


def render_sidebar(payload: Mapping[str, Any] | None) -> None:  # pragma: no cover
    """Render the methodology drawer in the Streamlit sidebar."""
    import streamlit as st

    drawer = build_methodology(payload)
    with st.sidebar:
        st.markdown("### Methodology")
        st.markdown(
            f"**Data freshness:** `{drawer['freshness']}` "
            f"({drawer['computed_at'] or '—'})",
        )
        st.markdown("**Sprint plans**")
        for sp in drawer["sprint_plans"]:
            st.markdown(f"- [{sp['label']}]({sp['path']})")
        st.markdown("**Sources**")
        for s in drawer["sources"]:
            st.markdown(f"- [{s['label']}]({s['url']})")
        st.markdown("**Gate thresholds**")
        for t in drawer["thresholds"]:
            st.markdown(
                f"- `{t['name']} = {t['value']}` — {t['rationale']}",
            )
