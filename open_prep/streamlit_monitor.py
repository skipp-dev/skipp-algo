from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import streamlit as st
from streamlit_autorefresh import st_autorefresh

from open_prep.run_open_prep import (
    DEFAULT_UNIVERSE,
    GAP_MODE_CHOICES,
    GAP_MODE_PREMARKET_INDICATIVE,
    generate_open_prep_result,
)

DEFAULT_REFRESH_SECONDS = 10
MAX_STATUS_HISTORY = 20


def _parse_symbols(raw: str) -> list[str]:
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def _inject_auto_refresh(seconds: int) -> None:
    # Browser-level refresh keeps dependency footprint small (no extra plugin).
    st.markdown(
        f"<meta http-equiv='refresh' content='{max(int(seconds), 1)}'>",
        unsafe_allow_html=True,
    )


def _show_runtime_warnings(run_status: dict[str, Any]) -> None:
    warnings = run_status.get("warnings") or []
    if not warnings:
        st.success("Keine Runtime-Warnungen gemeldet.")
        return

    for warning in warnings:
        stage = warning.get("stage", "unknown")
        code = warning.get("code", "UNKNOWN")
        message = warning.get("message", "")
        symbols = warning.get("symbols") or []
        suffix = f" | Symbole: {', '.join(symbols)}" if symbols else ""
        st.warning(f"[{stage}] {code}: {message}{suffix}")


def _traffic_light_status(run_status: dict[str, Any]) -> tuple[str, str, str]:
    fatal_stage = run_status.get("fatal_stage")
    warnings = run_status.get("warnings") or []

    if fatal_stage:
        return "🔴 KRITISCH", "red", f"Fatal stage: {fatal_stage}"
    if warnings:
        return "🟡 DEGRADED", "orange", f"{len(warnings)} Warnung(en) aktiv"
    return "🟢 OK", "green", "Alle Datenquellen liefern ohne Warnungen"


def _status_symbol(traffic_label: str) -> str:
    if "KRITISCH" in traffic_label:
        return "🔴"
    if "DEGRADED" in traffic_label:
        return "🟡"
    return "🟢"


def _update_status_history(traffic_label: str, updated_at: str) -> list[str]:
    history: list[str] = st.session_state.get("status_history", [])
    entry = f"{_status_symbol(traffic_label)} {updated_at}"
    if not history or history[-1] != entry:
        history.append(entry)
    st.session_state["status_history"] = history[-MAX_STATUS_HISTORY:]
    return st.session_state["status_history"]


def _render_soft_refresh_status(updated_at: str | None) -> None:
    prev = st.session_state.get("last_successful_update_utc")
    curr = str(updated_at or "n/a")
    st.session_state["last_successful_update_utc"] = curr

    if not updated_at:
        st.info("Datenstand: n/a")
        return

    try:
        updated_dt = datetime.fromisoformat(str(updated_at))
        age_seconds = max(int((datetime.now(UTC) - updated_dt).total_seconds()), 0)
        if prev and prev != curr:
            st.success(f"Daten aktualisiert · UTC {curr} · vor {age_seconds}s")
        else:
            st.info(f"Datenstand stabil · UTC {curr} · vor {age_seconds}s")
    except ValueError:
        st.info(f"Datenstand: {curr}")


def main() -> None:
    st.set_page_config(page_title="Open Prep Monitor", page_icon="📈", layout="wide")
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 1.5rem;
            padding-bottom: 1rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.session_state.setdefault("auto_refresh_enabled", False)
    st.session_state.setdefault("refresh_seconds", DEFAULT_REFRESH_SECONDS)

    refresh_count = 0

    with st.sidebar:
        st.header("Parameter")
        auto_refresh_enabled = st.toggle(
            "🔁 Auto-Refresh starten",
            value=bool(st.session_state.get("auto_refresh_enabled", False)),
            key="auto_refresh_enabled",
        )
        refresh_seconds = st.number_input(
            "Intervall (Sekunden)",
            min_value=1,
            max_value=3600,
            value=int(st.session_state.get("refresh_seconds", DEFAULT_REFRESH_SECONDS)),
            step=1,
            key="refresh_seconds",
            disabled=not auto_refresh_enabled,
        )
        st.caption(
            f"Auto-Refresh: {'an' if auto_refresh_enabled else 'aus'}"
            + (f" · alle {int(refresh_seconds)}s" if auto_refresh_enabled else "")
        )
        symbols_raw = st.text_area(
            "Symbole (comma-separated)",
            value=",".join(DEFAULT_UNIVERSE),
            height=120,
        )
        days_ahead = st.number_input("Days ahead", min_value=1, max_value=14, value=3)
        top_n = st.number_input("Top candidates", min_value=1, max_value=50, value=10)
        trade_cards = st.number_input("Trade cards", min_value=1, max_value=50, value=5)
        max_macro_events = st.number_input("Max macro events", min_value=1, max_value=100, value=15)
        pre_open_only = st.checkbox("Pre-open only", value=False)
        pre_open_cutoff_utc = st.text_input("Pre-open cutoff UTC", value="16:00:00")
        gap_mode = st.selectbox("Gap mode", options=list(GAP_MODE_CHOICES), index=list(GAP_MODE_CHOICES).index(GAP_MODE_PREMARKET_INDICATIVE))
        atr_lookback_days = st.number_input("ATR lookback days", min_value=20, max_value=1000, value=250)
        atr_period = st.number_input("ATR period", min_value=1, max_value=200, value=14)
        atr_parallel_workers = st.number_input("ATR parallel workers", min_value=1, max_value=20, value=5)

        if st.button("🔄 Sofort aktualisieren", use_container_width=True):
            st.rerun()
        if st.button("🧹 Verlauf zurücksetzen", use_container_width=True):
            st.session_state["status_history"] = []
            st.rerun()

    if auto_refresh_enabled:
        refresh_count = st_autorefresh(
            interval=int(refresh_seconds) * 1000,
            key="open_prep_autorefresh",
        )

    symbols = _parse_symbols(symbols_raw)
    if not symbols:
        st.error("Bitte mindestens ein Symbol angeben.")
        st.stop()

    try:
        result = generate_open_prep_result(
            symbols=symbols,
            days_ahead=int(days_ahead),
            top=int(top_n),
            trade_cards=int(trade_cards),
            max_macro_events=int(max_macro_events),
            pre_open_only=bool(pre_open_only),
            pre_open_cutoff_utc=pre_open_cutoff_utc,
            gap_mode=str(gap_mode),
            atr_lookback_days=int(atr_lookback_days),
            atr_period=int(atr_period),
            atr_parallel_workers=int(atr_parallel_workers),
            now_utc=datetime.now(UTC),
        )
    except Exception as exc:
        st.exception(exc)
        st.stop()

    updated_at = result.get("run_datetime_utc")
    run_status = result.get("run_status") or {}
    traffic_label, traffic_color, traffic_text = _traffic_light_status(run_status)

    st.subheader("Ranked Candidates")
    st.dataframe(result.get("ranked_candidates") or [], use_container_width=True, height=360)

    st.subheader("Trade Cards")
    st.dataframe(result.get("trade_cards") or [], use_container_width=True, height=320)

    st.subheader("US High Impact Events (today)")
    st.dataframe(result.get("macro_us_high_impact_events_today") or [], use_container_width=True, height=280)

    _render_soft_refresh_status(str(updated_at) if updated_at is not None else None)
    st.subheader("Status")
    cols = st.columns(4)
    cols[0].metric("Letztes Update (UTC)", str(updated_at or "n/a"))
    cols[1].metric("Macro Bias", f"{float(result.get('macro_bias', 0.0)):.4f}")
    cols[2].metric("US High Impact", int(result.get("macro_us_high_impact_event_count_today", 0)))
    cols[3].metric("Kandidaten", len(result.get("ranked_candidates") or []))
    if auto_refresh_enabled:
        st.caption(f"Auto-Refresh Zyklen: {refresh_count}")
    else:
        st.caption("Auto-Refresh deaktiviert · Aktualisierung nur über „🔄 Sofort aktualisieren“")

    st.subheader("System-Ampel")
    st.markdown(
        f"<div style='padding:0.7rem 1rem;border-radius:0.6rem;background:{traffic_color};color:white;font-weight:700'>{traffic_label}</div>",
        unsafe_allow_html=True,
    )
    st.caption(traffic_text)

    history = _update_status_history(traffic_label, str(updated_at or "n/a"))
    st.caption("Verlauf (neueste rechts, letzte 20 Refreshes)")
    st.markdown(" ".join(item.split(" ")[0] for item in history))

    st.subheader("Runtime-Warnungen")
    _show_runtime_warnings(run_status)

    with st.expander("Raw JSON (Debug)"):
        st.json(result)


if __name__ == "__main__":
    main()
