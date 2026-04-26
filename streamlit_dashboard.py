"""C7/T8 — Slim Streamlit entry for the Track-Record Dashboard.

This file is the **only** Streamlit entry shipped in
``Dockerfile.dashboard``.  It is intentionally separated from the
trader-terminal app (``streamlit_terminal.py``) so the dashboard image
does not need to import ``httpx`` / databento / ML deps.

Surface (read-only):

* Track Record  — per-variant gate verdicts
* Calibration Detail — walk-forward / bootstrap / permutation / regime / PSR
* Live Incubation — drift artifact viewer
* Methodology — sidebar drawer with thresholds + freshness badge

The four C7 sub-modules (``tab_track_record``, ``tab_calibration_detail``,
``tab_live_incubation``, ``methodology_drawer``) are pure Python plus
numpy/pandas/plotly; they do **not** transitively import the trader-side
providers, so importing them here is safe inside the slim image.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import streamlit as st

from scripts.build_dashboard_payload import build_dashboard_payload

# Import C7 sub-modules directly (NOT via ``from terminal_tabs import …``)
# so the slim Docker image does not trigger the trader-tab re-exports
# in ``terminal_tabs/__init__.py`` which depend on httpx/databento.
from terminal_tabs import methodology_drawer
from terminal_tabs import tab_calibration_detail
from terminal_tabs import tab_live_incubation
from terminal_tabs import tab_track_record
from terminal_tabs.dashboard_cache import DEFAULT_TTL_SECONDS, TTLCache
from terminal_tabs.drift_loader import list_drift_dates, load_drift_artifact

DEFAULT_CACHE_DIR = Path(
    os.environ.get("SKIPP_DASHBOARD_CACHE_DIR", "cache")
).resolve()


@st.cache_resource
def _payload_cache() -> TTLCache:
    return TTLCache(ttl_seconds=DEFAULT_TTL_SECONDS)


def _load_payload(cache_dir: Path, as_of_date: str | None) -> dict[str, Any] | None:
    cache = _payload_cache()
    key = (str(cache_dir), as_of_date)
    return cache.get_or_compute(
        key,
        lambda: build_dashboard_payload(cache_dir, as_of_date=as_of_date),
    )


def _load_drift(cache_dir: Path, as_of_date: str | None) -> dict[str, Any] | None:
    return load_drift_artifact(cache_dir, as_of_date=as_of_date)


def main() -> None:
    st.set_page_config(
        page_title="SkippALGO — Track-Record Dashboard",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    cache_dir = DEFAULT_CACHE_DIR
    st.sidebar.caption(f"Cache: `{cache_dir}`")

    payload = _load_payload(cache_dir, as_of_date=None)

    methodology_drawer.render_sidebar(payload)

    drift_dates = list_drift_dates(cache_dir)
    drift_payload = (
        _load_drift(cache_dir, as_of_date=drift_dates[-1]) if drift_dates else None
    )

    tab_tr, tab_cal, tab_live = st.tabs(
        ["Track Record", "Calibration Detail", "Live Incubation"]
    )
    with tab_tr:
        tab_track_record.render(payload)
    with tab_cal:
        variants = (payload or {}).get("variants") or []
        names = [str(v.get("variant", "")) for v in variants if isinstance(v, dict)]
        if not names:
            st.info("No variants in current payload.")
        else:
            chosen = st.selectbox("Variant", names, index=0)
            tab_calibration_detail.render(payload, chosen)
    with tab_live:
        tab_live_incubation.render(drift_payload)


if __name__ == "__main__":
    main()
