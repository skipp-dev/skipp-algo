from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo
from typing import Any, cast

import streamlit as st

from open_prep.run_open_prep import (
    GAP_MODE_CHOICES,
    GAP_MODE_PREMARKET_INDICATIVE,
    generate_open_prep_result,
)

DEFAULT_REFRESH_SECONDS = 10
MAX_STATUS_HISTORY = 20
BERLIN_TZ = ZoneInfo("Europe/Berlin")
MIN_AUTO_REFRESH_SECONDS = 20
RATE_LIMIT_COOLDOWN_SECONDS = 120
MIN_LIVE_FETCH_INTERVAL_SECONDS = 45


def _parse_symbols(raw: str) -> list[str]:
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


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
        updated_raw = str(updated_at).replace("Z", "+00:00")
        updated_dt = datetime.fromisoformat(updated_raw)
        if updated_dt.tzinfo is None:
            updated_dt = updated_dt.replace(tzinfo=UTC)
        updated_berlin = updated_dt.astimezone(BERLIN_TZ)
        age_seconds = max(int((datetime.now(UTC) - updated_dt).total_seconds()), 0)
        if prev and prev != curr:
            st.success(
                "Daten aktualisiert"
                + f" · Berlin {updated_berlin.strftime('%Y-%m-%d %H:%M:%S %Z')}"
                + f" · UTC {updated_dt.strftime('%Y-%m-%d %H:%M:%S')}"
                + f" · vor {age_seconds}s"
            )
        else:
            st.info(
                "Datenstand stabil"
                + f" · Berlin {updated_berlin.strftime('%Y-%m-%d %H:%M:%S %Z')}"
                + f" · UTC {updated_dt.strftime('%Y-%m-%d %H:%M:%S')}"
                + f" · vor {age_seconds}s"
            )
    except ValueError:
        st.info(f"Datenstand: {curr}")


def _format_utc_berlin(updated_at: str | None) -> tuple[str, str]:
    if not updated_at:
        return "n/a", "n/a"
    try:
        updated_raw = str(updated_at).replace("Z", "+00:00")
        updated_dt = datetime.fromisoformat(updated_raw)
        if updated_dt.tzinfo is None:
            updated_dt = updated_dt.replace(tzinfo=UTC)
        updated_berlin = updated_dt.astimezone(BERLIN_TZ)
        return (
            updated_dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
            updated_berlin.strftime("%Y-%m-%d %H:%M:%S %Z"),
        )
    except ValueError:
        return str(updated_at), str(updated_at)


def _format_berlin_only(timestamp_utc: str | None) -> str:
    if not timestamp_utc:
        return "n/a"
    try:
        ts_raw = str(timestamp_utc).replace("Z", "+00:00")
        ts_dt = datetime.fromisoformat(ts_raw)
        if ts_dt.tzinfo is None:
            ts_dt = ts_dt.replace(tzinfo=UTC)
        return ts_dt.astimezone(BERLIN_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    except ValueError:
        return str(timestamp_utc)


def _universe_reload_freshness(timestamp_utc: str | None) -> str:
    if not timestamp_utc:
        return "⚪ Status: kein manueller Reload"
    try:
        ts_raw = str(timestamp_utc).replace("Z", "+00:00")
        ts_dt = datetime.fromisoformat(ts_raw)
        if ts_dt.tzinfo is None:
            ts_dt = ts_dt.replace(tzinfo=UTC)
        age_seconds = max(int((datetime.now(UTC) - ts_dt).total_seconds()), 0)
        age_minutes = age_seconds // 60
        if age_seconds < 5 * 60:
            return f"🟢 Status: frisch ({age_minutes} min)"
        if age_seconds < 15 * 60:
            return f"🟡 Status: mittel-alt ({age_minutes} min)"
        return f"🔴 Status: veraltet ({age_minutes} min)"
    except ValueError:
        return "⚪ Status: Zeitformat unbekannt"


def _is_rate_limited(run_status: dict[str, Any]) -> bool:
    warnings = run_status.get("warnings") or []
    for warning in warnings:
        message = str(warning.get("message", "")).lower()
        code = str(warning.get("code", "")).lower()
        if "429" in message or "limit" in message or "rate" in message or "429" in code or code == "rate_limit":
            return True
    return False


def _remaining_cooldown_seconds(now_utc: datetime) -> int:
    cooldown_until_raw = st.session_state.get("rate_limit_cooldown_until_utc")
    if not cooldown_until_raw:
        return 0
    try:
        cooldown_until = datetime.fromisoformat(str(cooldown_until_raw).replace("Z", "+00:00"))
        if cooldown_until.tzinfo is None:
            cooldown_until = cooldown_until.replace(tzinfo=UTC)
        return max(int((cooldown_until - now_utc).total_seconds()), 0)
    except ValueError:
        return 0


def _prediction_side(row: dict[str, Any], macro_bias: float) -> str:
    long_allowed = bool(row.get("long_allowed", True))
    gap_pct = float(row.get("gap_pct") or 0.0)
    momentum_z = float(row.get("momentum_z_score") or 0.0)

    if long_allowed and macro_bias >= -0.25:
        return "🟢 LONG"
    if (not long_allowed) and (macro_bias <= -0.25 or gap_pct <= -1.0 or momentum_z < 0.0):
        return "🔴 SHORT-BIAS"
    return "🟡 NEUTRAL"


def _reorder_ranked_columns(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    priority = [
        "symbol",
        "score",
        "price",
        "long_allowed",
        "no_trade_reason",
        "prediction_side",
        "gap_pct",
    ]

    for row in rows:
        if not isinstance(row, dict):
            continue
        reordered: dict[str, Any] = {}
        for key in priority:
            if key in row:
                reordered[key] = row.get(key)
        for key, value in row.items():
            if key not in reordered:
                reordered[key] = value
        ordered.append(reordered)
    return ordered


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
    st.session_state.setdefault("auto_universe", True)
    st.session_state.setdefault("symbols_raw", "")
    st.session_state.setdefault("last_universe_reload_utc", None)
    st.session_state.setdefault("rate_limit_cooldown_until_utc", None)
    st.session_state.setdefault("latest_result_cache", None)
    st.session_state.setdefault("last_live_fetch_utc", None)
    st.session_state.setdefault("force_live_fetch", False)

    def _on_force_refresh() -> None:
        st.session_state["force_live_fetch"] = True

    def _on_reload_universe() -> None:
        st.session_state["auto_universe"] = True
        st.session_state["symbols_raw"] = ""
        st.session_state["last_universe_reload_utc"] = datetime.now(UTC).isoformat()
        st.session_state["force_live_fetch"] = True

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
        requested_refresh_seconds = int(refresh_seconds)
        now_utc = datetime.now(UTC)
        cooldown_remaining = _remaining_cooldown_seconds(now_utc)
        effective_refresh_seconds = max(requested_refresh_seconds, MIN_AUTO_REFRESH_SECONDS)
        if cooldown_remaining > 0:
            effective_refresh_seconds = max(effective_refresh_seconds, cooldown_remaining)

        st.caption(
            f"Auto-Refresh: {'an' if auto_refresh_enabled else 'aus'}"
            + (
                f" · Intervall: {requested_refresh_seconds}s"
                + (
                    f" · effektiv: {effective_refresh_seconds}s"
                    if auto_refresh_enabled
                    else ""
                )
                if auto_refresh_enabled
                else ""
            )
        )
        if auto_refresh_enabled and requested_refresh_seconds < MIN_AUTO_REFRESH_SECONDS:
            st.info(f"API-Schutz aktiv: Mindestintervall {MIN_AUTO_REFRESH_SECONDS}s.")
        if auto_refresh_enabled and cooldown_remaining > 0:
            st.warning(f"Rate-Limit Cooldown aktiv: nächster Auto-Refresh in ca. {cooldown_remaining}s.")
        auto_universe = st.toggle(
            "🌐 Auto-Universum verwenden",
            value=bool(st.session_state.get("auto_universe", True)),
            help="Wenn aktiv, wird das FMP-Universum (US Mid/Large + Movers) genutzt.",
            key="auto_universe",
        )
        symbols_raw = st.text_area(
            "Symbole (comma-separated)",
            value=str(st.session_state.get("symbols_raw", "")),
            height=120,
            help="Leer lassen = Auto-Universum (FMP US Mid/Large + Movers).",
            disabled=auto_universe,
            key="symbols_raw",
        )
        days_ahead = st.number_input("Days ahead", min_value=1, max_value=14, value=3)
        top_n = st.number_input("Top candidates", min_value=1, max_value=50, value=10)
        trade_cards = st.number_input("Trade cards", min_value=1, max_value=50, value=5)
        max_macro_events = st.number_input("Max macro events", min_value=1, max_value=100, value=15)
        pre_open_only = st.checkbox("Pre-open only", value=False)
        pre_open_cutoff_time = st.time_input(
            "Pre-open cutoff UTC",
            value=time(16, 0, 0),
            step=60,
            help="UTC cutoff time used when 'Pre-open only' is enabled.",
            key="pre_open_cutoff_time_utc",
        )
        pre_open_cutoff_utc = pre_open_cutoff_time.strftime("%H:%M:%S")
        gap_mode = st.selectbox(
            "Gap mode",
            options=list(GAP_MODE_CHOICES),
            index=list(GAP_MODE_CHOICES).index(GAP_MODE_PREMARKET_INDICATIVE),
            key="gap_mode",
        )
        atr_lookback_days = st.number_input("ATR lookback days", min_value=20, max_value=1000, value=250)
        atr_period = st.number_input("ATR period", min_value=1, max_value=200, value=14)
        atr_parallel_workers = st.number_input("ATR parallel workers", min_value=1, max_value=20, value=5)

        if st.button("🔄 Sofort aktualisieren", width="stretch", on_click=_on_force_refresh):
            if not auto_refresh_enabled:
                st.rerun()
        if st.button("🔎 Nur Universum neu laden", width="stretch", on_click=_on_reload_universe):
            if not auto_refresh_enabled:
                st.rerun()
        last_universe_reload_utc = st.session_state.get("last_universe_reload_utc")
        last_universe_reload = _format_berlin_only(last_universe_reload_utc)
        last_universe_reload_freshness = _universe_reload_freshness(last_universe_reload_utc)
        st.caption(f"Letzter Universum-Reload (Berlin): {last_universe_reload}")
        st.caption(last_universe_reload_freshness)
        if st.button("🧹 Verlauf zurücksetzen", width="stretch"):
            st.session_state["status_history"] = []
            st.rerun()

    def _render_open_prep_snapshot() -> None:
        symbols = _parse_symbols(symbols_raw)
        use_auto_universe = bool(auto_universe)

        if not use_auto_universe and not symbols:
            st.error("Bitte Symbole eingeben oder Auto-Universum aktivieren.")
            return

        force_live_fetch = bool(st.session_state.get("force_live_fetch", False))
        cached_result = st.session_state.get("latest_result_cache")
        last_live_fetch_raw = st.session_state.get("last_live_fetch_utc")
        now_utc = datetime.now(UTC)
        live_fetch_interval = max(int(effective_refresh_seconds), MIN_LIVE_FETCH_INTERVAL_SECONDS)
        use_cached_result = False

        if auto_refresh_enabled and not force_live_fetch and isinstance(cached_result, dict) and last_live_fetch_raw:
            try:
                last_live_fetch = datetime.fromisoformat(str(last_live_fetch_raw).replace("Z", "+00:00"))
                if last_live_fetch.tzinfo is None:
                    last_live_fetch = last_live_fetch.replace(tzinfo=UTC)
                elapsed = max(int((now_utc - last_live_fetch).total_seconds()), 0)
                if elapsed < live_fetch_interval:
                    use_cached_result = True
            except ValueError:
                use_cached_result = False

        if use_cached_result:
            result = dict(cast(dict[str, Any], cached_result))
            st.caption(
                f"Auto-Refresh Anzeige aus Cache · Live-Fetch alle ~{live_fetch_interval}s zur Entlastung"
            )
        else:
            try:
                result = generate_open_prep_result(
                    symbols=(None if use_auto_universe else symbols),
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
                    now_utc=now_utc,
                )
            except Exception as exc:
                st.exception(exc)
                return
            st.session_state["latest_result_cache"] = dict(result)
            st.session_state["last_live_fetch_utc"] = now_utc.isoformat()
            st.session_state["force_live_fetch"] = False

        if use_auto_universe:
            st.info("Auto-Universum aktiv (FMP US Mid/Large + Movers).")

        updated_at = result.get("run_datetime_utc")
        updated_utc_label, updated_berlin_label = _format_utc_berlin(str(updated_at) if updated_at is not None else None)
        run_status = result.get("run_status") or {}
        if _is_rate_limited(run_status):
            st.session_state["rate_limit_cooldown_until_utc"] = (
                datetime.now(UTC).replace(microsecond=0)
                + timedelta(seconds=RATE_LIMIT_COOLDOWN_SECONDS)
            ).isoformat()
        traffic_label, traffic_color, traffic_text = _traffic_light_status(run_status)

        ranked_candidates = list(result.get("ranked_candidates") or [])
        for row in ranked_candidates:
            row["prediction_side"] = _prediction_side(row, float(result.get("macro_bias", 0.0)))
        ranked_candidates = _reorder_ranked_columns(ranked_candidates)

        st.subheader("Ranked Candidates")
        st.dataframe(ranked_candidates, width="stretch", height=360)

        st.subheader("Trade Cards")
        st.dataframe(result.get("trade_cards") or [], width="stretch", height=320)

        st.subheader("US High Impact Events (today)")
        st.dataframe(result.get("macro_us_high_impact_events_today") or [], width="stretch", height=280)

        _render_soft_refresh_status(str(updated_at) if updated_at is not None else None)
        st.subheader("Status")
        cols = st.columns(4)
        cols[0].metric("Letztes Update (Berlin)", updated_berlin_label)
        cols[1].metric("Macro Bias", f"{float(result.get('macro_bias', 0.0)):.4f}")
        cols[2].metric("US High Impact", int(result.get("macro_us_high_impact_event_count_today", 0)))
        cols[3].metric("Kandidaten", len(ranked_candidates))
        if float(result.get("macro_bias", 0.0)) >= 0.0:
            st.caption("Signalrichtung: 🟢 LONG-BIAS")
        else:
            st.caption("Signalrichtung: 🔴 SHORT-BIAS")
        st.caption(f"Zeitreferenz (UTC): {updated_utc_label}")

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

    if auto_refresh_enabled and hasattr(st, "fragment"):
        @st.fragment(run_every=f"{int(effective_refresh_seconds)}s")
        def _live_snapshot_fragment() -> None:
            _render_open_prep_snapshot()

        _live_snapshot_fragment()
        st.caption(
            f"Soft-Refresh aktiv · effektiv alle {int(effective_refresh_seconds)}s · weniger Seiten-Flackern"
        )
    else:
        _render_open_prep_snapshot()
        if auto_refresh_enabled:
            st.info("Auto-Refresh im Kompatibilitätsmodus: bitte Streamlit aktualisieren für Soft-Refresh.")
        else:
            st.caption("Auto-Refresh deaktiviert · Aktualisierung nur über „🔄 Sofort aktualisieren“")


if __name__ == "__main__":
    main()
