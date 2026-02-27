from __future__ import annotations

import copy
import logging
import os
import sys
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import streamlit as st

logger = logging.getLogger("open_prep.streamlit_monitor")

# Ensure package imports work even when Streamlit is started outside project root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_env_file(env_path: Path) -> None:
    """Load KEY=VALUE pairs from .env into process env (without overriding existing vars)."""
    if not env_path.exists():
        return
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)
    except Exception as exc:
        logger.debug("Could not load .env file %s: %s", env_path, exc)


_load_env_file(PROJECT_ROOT / ".env")

from open_prep.run_open_prep import (  # noqa: E402
    GAP_MODE_CHOICES,
    GAP_MODE_PREMARKET_INDICATIVE,
    GAP_SCOPE_CHOICES,
    GAP_SCOPE_DAILY,
    build_gap_scanner,
    generate_open_prep_result,
)

DEFAULT_REFRESH_SECONDS = 60
MAX_STATUS_HISTORY = 20
BERLIN_TZ = ZoneInfo("Europe/Berlin")
MIN_AUTO_REFRESH_SECONDS = 20
RATE_LIMIT_COOLDOWN_SECONDS = 120
MIN_LIVE_FETCH_INTERVAL_SECONDS = 45

# ── Market session awareness (optional — may be unavailable on Streamlit Cloud)
try:
    from terminal_spike_scanner import SESSION_ICONS as _SESSION_ICONS, market_session as _market_session
except ImportError:  # pragma: no cover
    _market_session = None  # type: ignore[assignment]
    _SESSION_ICONS = {
        "pre-market": "🌅 Pre-Market",
        "regular": "🟢 Regular Session",
        "after-hours": "🌙 After-Hours",
        "closed": "⚫ Market Closed",
    }

try:
    from terminal_poller import fetch_benzinga_delayed_quotes as _fetch_bz_quotes
except ImportError:  # pragma: no cover
    _fetch_bz_quotes = None  # type: ignore[assignment]


@st.cache_data(ttl=60, show_spinner=False)
def _cached_bz_quotes_op(api_key: str, symbols_csv: str) -> list[dict[str, Any]]:
    """Cache Benzinga delayed quotes for 60 s (open_prep)."""
    if _fetch_bz_quotes is None:
        return []
    syms = [s.strip() for s in symbols_csv.split(",") if s.strip()]
    return _fetch_bz_quotes(api_key, syms) or []


def _get_bz_quotes_for_symbols(
    symbols: list[str],
    *,
    max_symbols: int = 50,
) -> dict[str, dict[str, Any]]:
    """Fetch Benzinga delayed quotes keyed by uppercase symbol.

    Returns empty dict when the API key is not set or the import
    is unavailable.  Results are cached for 60 s via Streamlit.
    """
    if _fetch_bz_quotes is None or not symbols:
        return {}
    bz_key = os.environ.get("BENZINGA_API_KEY", "")
    if not bz_key:
        return {}
    try:
        syms = sorted(set(symbols))[:max_symbols]
        quotes = _cached_bz_quotes_op(bz_key, ",".join(syms))
        return {
            (q.get("symbol") or "").upper().strip(): q
            for q in quotes
            if q.get("symbol")
        }
    except Exception as exc:
        logger.debug("Benzinga delayed quotes unavailable: %s", exc)
        return {}


def _overlay_bz_prices(
    rows: list[dict[str, Any]],
    bz_map: dict[str, dict[str, Any]],
    sym_key: str = "symbol",
) -> list[dict[str, Any]]:
    """Overlay Benzinga delayed quote prices onto candidate rows.

    Adds ``bz_price`` and ``bz_chg_pct`` columns when the symbol has
    a Benzinga quote.  Returns *rows* for chaining.
    """
    if not bz_map:
        return rows
    for row in rows:
        sym = str(row.get(sym_key, "")).upper().strip()
        bq = bz_map.get(sym)
        if bq:
            bz_last = bq.get("last")
            if bz_last is not None:
                try:
                    row["bz_price"] = round(float(bz_last), 2)
                except (ValueError, TypeError):
                    row["bz_price"] = None
            bz_chg = bq.get("changePercent")
            if bz_chg is not None:
                try:
                    row["bz_chg_pct"] = round(float(bz_chg), 2)
                except (ValueError, TypeError):
                    row["bz_chg_pct"] = None
    return rows


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


def promote_a0a1_signals(
    ranked_v2: list[dict],
    filtered_out_v2: list[dict],
    rt_signals: list[dict],
) -> tuple[list[dict], list[dict], set[str], dict[str, dict]]:
    """Auto-promote A0/A1 realtime signals that fell below the top-n cutoff.

    This bridges the gap between the pipeline scorer (point-in-time snapshot)
    and the realtime engine (continuous breakout detection).  Symbols with
    active A0/A1 signals that were scored but landed just below the cutoff
    are promoted into ``ranked_v2`` with an ``rt_promoted=True`` marker.

    Args:
        ranked_v2: Mutable list of ranked candidate dicts from the pipeline.
        filtered_out_v2: Mutable list of filtered-out candidate dicts.
        rt_signals: List of realtime signal dicts (from disk/engine).

    Returns:
        A 4-tuple of ``(ranked_v2, filtered_out_v2, promoted_syms, a0a1_map)``.
        ``promoted_syms`` is the set of symbol strings that were promoted.
        ``a0a1_map`` maps uppercase symbol → signal dict for all A0/A1 signals
        (used by the cross-reference section later).
    """
    a0a1_map: dict[str, dict] = {
        str(s.get("symbol", "")).upper(): s
        for s in rt_signals
        if s.get("level") in ("A0", "A1")
    }
    promoted_syms: set[str] = set()

    if not a0a1_map:
        return ranked_v2, filtered_out_v2, promoted_syms, a0a1_map

    v2_symbols = {str(r.get("symbol", "")).upper() for r in ranked_v2}
    below_cutoff_map: dict[str, dict] = {}
    for fo in filtered_out_v2:
        if fo.get("filter_reasons") == ["below_top_n_cutoff"]:
            sym = str(fo.get("symbol", "")).upper()
            below_cutoff_map[sym] = fo

    for sym, sig in a0a1_map.items():
        if sym in v2_symbols:
            continue  # already ranked
        cutoff_entry = below_cutoff_map.get(sym)
        if cutoff_entry is None:
            continue  # hard-filtered or not in universe
        promoted_row = {
            "symbol": sym,
            "score": cutoff_entry.get("score", 0.0),
            "gap_pct": cutoff_entry.get("gap_pct", 0.0),
            "price": cutoff_entry.get("price", sig.get("price", 0.0)),
            "confidence_tier": cutoff_entry.get("confidence_tier", ""),
            "rt_promoted": True,
            "rt_level": sig.get("level", ""),
            "rt_direction": sig.get("direction", ""),
            "rt_pattern": sig.get("pattern", ""),
            "rt_change_pct": sig.get("change_pct", 0.0),
            "rt_volume_ratio": sig.get("volume_ratio", 0.0),
        }
        ranked_v2.append(promoted_row)
        promoted_syms.add(sym)
        filtered_out_v2 = [
            fo for fo in filtered_out_v2
            if str(fo.get("symbol", "")).upper() != sym
        ]

    return ranked_v2, filtered_out_v2, promoted_syms, a0a1_map


def _update_status_history(traffic_label: str, updated_at: str) -> list[str]:
    history: list[str] = st.session_state.get("status_history", [])
    entry = f"{_status_symbol(traffic_label)} {updated_at}"
    if not history or history[-1] != entry:
        history.append(entry)
    st.session_state["status_history"] = history[-MAX_STATUS_HISTORY:]
    return list(st.session_state["status_history"])


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
        "N",
        "news_sentiment_emoji",
        "upgrade_downgrade_emoji",
        "score",
        "price",
        "bz_price",
        "bz_chg_pct",
        "gap_bucket",
        "gap_grade",
        "gap_pct",
        "symbol_sector",
        "sector_change_pct",
        "sector_relative_gap",
        "atr_pct",
        "ext_hours_score",
        "premarket_high",
        "premarket_low",
        "premarket_spread_bps",
        "premarket_stale",
        "warn_flags",
        "no_trade_reason",
        "long_allowed",
        "prediction_side",
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
            padding-top: 2.5rem;
            padding-bottom: 1rem;
        }
        /* Stabilise fragment re-renders: prevent layout shifts and flicker */
        [data-testid="stVerticalBlock"],
        [data-testid="stHorizontalBlock"],
        .element-container,
        .stDataFrame {
            transition: none !important;
            animation: none !important;
        }
        /* Lock minimum height on dataframe containers so they don't collapse
           to zero briefly between re-renders, which causes the visible "jump". */
        .stDataFrame iframe,
        .stDataFrame > div {
            min-height: 200px;
        }
        /* Prevent the entire fragment area from flashing white during re-render */
        [data-testid="stExpander"],
        section[data-testid="stSidebar"] {
            opacity: 1 !important;
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
        gap_scope = st.selectbox(
            "Gap scope",
            options=list(GAP_SCOPE_CHOICES),
            index=list(GAP_SCOPE_CHOICES).index(GAP_SCOPE_DAILY),
            key="gap_scope",
            help="DAILY = Overnight-Gaps jeden Handelstag. STRETCH_ONLY = nur nach Wochenende/Feiertag.",
        )
        atr_lookback_days = st.number_input("ATR lookback days", min_value=20, max_value=1000, value=250)
        atr_period = st.number_input("ATR period", min_value=1, max_value=200, value=14)
        atr_parallel_workers = st.number_input("ATR parallel workers", min_value=1, max_value=20, value=8)

        if st.button("🔄 Sofort aktualisieren", width="stretch", on_click=_on_force_refresh):
            if not auto_refresh_enabled:
                st.rerun()

        # Reset cache (forces a complete fresh pipeline run)
        if st.button("🔃 Cache leeren", width="stretch",
                     help="Verwirft den Cache und erzwingt einen vollständigen Pipeline-Lauf "
                          "beim nächsten Refresh. Nutzen wenn Daten veraltet erscheinen."):
            st.session_state["latest_result_cache"] = None
            st.session_state["last_live_fetch_utc"] = None
            st.session_state["force_live_fetch"] = True
            st.toast("Cache geleert — nächster Refresh holt frische Daten", icon="🔃")
            st.rerun()

        if st.button("🔎 Nur Universum neu laden", width="stretch", on_click=_on_reload_universe):
            if not auto_refresh_enabled:
                st.rerun()

        # ── Data freshness diagnostics ──────────────────────
        _diag_last_fetch_raw = st.session_state.get("last_live_fetch_utc")
        if _diag_last_fetch_raw:
            try:
                _diag_last_fetch = datetime.fromisoformat(
                    str(_diag_last_fetch_raw).replace("Z", "+00:00")
                )
                if _diag_last_fetch.tzinfo is None:
                    _diag_last_fetch = _diag_last_fetch.replace(tzinfo=UTC)
                _diag_age_s = max((datetime.now(UTC) - _diag_last_fetch).total_seconds(), 0)
                _diag_age_min = _diag_age_s / 60
                _diag_label = f"Daten-Alter: {_diag_age_min:.0f}m"
                _diag_is_market = callable(_market_session) and _market_session() in ("regular", "pre-market", "after-hours")
                if _diag_age_min > 30 and _diag_is_market:
                    st.warning(_diag_label)
                else:
                    st.caption(_diag_label)
            except (ValueError, TypeError):
                pass
        else:
            st.caption("Daten-Alter: (kein Fetch)")
        _diag_cached = st.session_state.get("latest_result_cache")
        st.caption(f"Cache: {'aktiv' if _diag_cached else 'leer'}")

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
            # Show a live status panel while fetching data so users can
            # track pipeline progress (instead of an opaque spinner).
            status_container = st.status("Pipeline wird ausgeführt …", expanded=True)
            _pipeline_start = __import__("time").monotonic()

            def _on_progress(stage: int, total: int, label: str) -> None:
                elapsed = __import__("time").monotonic() - _pipeline_start
                status_container.update(label=f"Stage {stage}/{total}: {label} ({elapsed:.0f}s)")

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
                    gap_scope=str(gap_scope),
                    atr_lookback_days=int(atr_lookback_days),
                    atr_period=int(atr_period),
                    atr_parallel_workers=int(atr_parallel_workers),
                    now_utc=now_utc,
                    progress_callback=_on_progress,
                )
            except Exception as exc:
                status_container.update(label="Pipeline fehlgeschlagen", state="error", expanded=False)
                logger.error("Pipeline error: %s", exc, exc_info=True)
                st.error(f"Pipeline fehlgeschlagen: {type(exc).__name__}: {exc}")
                return
            total_elapsed = __import__("time").monotonic() - _pipeline_start
            status_container.update(
                label=f"Pipeline abgeschlossen ({total_elapsed:.0f}s)",
                state="complete",
                expanded=False,
            )
            st.session_state["latest_result_cache"] = copy.deepcopy(result)
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
        # Mark new entrants with 🆕 column
        _diff = result.get("diff") or {}
        _new_entrant_set: set[str] = set(_diff.get("new_entrants") or [])
        for row in ranked_candidates:
            row["prediction_side"] = _prediction_side(row, float(result.get("macro_bias", 0.0)))
            row["N"] = "🆕" if str(row.get("symbol", "")).upper() in _new_entrant_set else ""

        # Prepare common data first
        ranked_gap_go = list(result.get("ranked_gap_go") or [])
        for row in ranked_gap_go:
            row["prediction_side"] = _prediction_side(row, float(result.get("macro_bias", 0.0)))
            row["N"] = "🆕" if str(row.get("symbol", "")).upper() in _new_entrant_set else ""

        ranked_gap_watch = list(result.get("ranked_gap_watch") or [])
        for row in ranked_gap_watch:
            row["prediction_side"] = _prediction_side(row, float(result.get("macro_bias", 0.0)))
            row["N"] = "🆕" if str(row.get("symbol", "")).upper() in _new_entrant_set else ""

        ranked_gap_go_earn = list(result.get("ranked_gap_go_earnings") or [])
        for row in ranked_gap_go_earn:
            row["prediction_side"] = _prediction_side(row, float(result.get("macro_bias", 0.0)))
            row["N"] = "🆕" if str(row.get("symbol", "")).upper() in _new_entrant_set else ""

        earnings_symbols_set = {r.get("symbol") for r in ranked_gap_go_earn}
        for row in ranked_candidates:
            if row.get("earnings_today") and row.get("symbol") not in earnings_symbols_set:
                ranked_gap_go_earn.append(row)
                earnings_symbols_set.add(row.get("symbol"))
        # Only include earnings_calendar entries for symbols in our ranked universe
        ranked_symbols_set = {r.get("symbol") for r in ranked_candidates if r.get("symbol")}
        earnings_calendar = result.get("earnings_calendar") or []
        for entry in earnings_calendar:
            sym = entry.get("symbol")
            if sym and sym not in earnings_symbols_set and sym in ranked_symbols_set:
                ranked_gap_go_earn.append(entry)
                earnings_symbols_set.add(sym)

        # ── Market session indicator (applies to all FMP-sourced data) ──
        _session = _market_session() if callable(_market_session) else "regular"
        _session_label = _SESSION_ICONS.get(_session, _session)
        if _session in ("pre-market", "after-hours"):
            st.info(
                f"**{_session_label}** — FMP price/sector data shows previous close. "
                "Benzinga delayed quotes are overlaid where available for fresher prices."
            )
        elif _session == "closed":
            st.caption(f"**{_session_label}** — Showing last session data.")

        # Fetch Benzinga delayed quotes for all candidate symbols (fallback).
        # Overlay BEFORE _reorder_ranked_columns so bz_price/bz_chg_pct
        # appear in the correct column position (priority list slot).
        _all_syms = sorted({str(r.get("symbol", "")).upper() for r in ranked_candidates if r.get("symbol")})
        _bz_map: dict[str, dict[str, Any]] = {}
        if _session in ("pre-market", "after-hours"):
            _bz_map = _get_bz_quotes_for_symbols(_all_syms)

        if _bz_map:
            _overlay_bz_prices(ranked_candidates, _bz_map)
            _overlay_bz_prices(ranked_gap_go, _bz_map)
            _overlay_bz_prices(ranked_gap_watch, _bz_map)
            _overlay_bz_prices(ranked_gap_go_earn, _bz_map)

        # Reorder columns (bz_price/bz_chg_pct now placed after "price")
        ranked_candidates = _reorder_ranked_columns(ranked_candidates)
        ranked_gap_go = _reorder_ranked_columns(ranked_gap_go)
        ranked_gap_watch = _reorder_ranked_columns(ranked_gap_watch)
        ranked_gap_go_earn = _reorder_ranked_columns(ranked_gap_go_earn)

        # ===================================================================
        # 0. REALTIME SIGNALS (A0/A1 — top of page)
        # ===================================================================
        _tier_emojis_rt = {"HIGH_CONVICTION": "🟢", "STANDARD": "🟡", "WATCHLIST": "🔵"}
        try:
            from .realtime_signals import RealtimeEngine
            rt_data = RealtimeEngine.load_signals_from_disk()
            rt_signals = rt_data.get("signals") or []
            a0_signals = [s for s in rt_signals if s.get("level") == "A0"]
            a1_signals = [s for s in rt_signals if s.get("level") == "A1"]
            rt_updated = rt_data.get("updated_at", "")
            rt_watched = rt_data.get("watched_symbols", [])

            if rt_signals:
                st.subheader(f"🔴 Realtime Signals  ({len(a0_signals)} A0 · {len(a1_signals)} A1)")
                if rt_updated:
                    st.caption(f"Letzte Aktualisierung: {rt_updated}")

                if a0_signals:
                    st.markdown("**🔴 A0 — IMMEDIATE ACTION**")
                    for s in a0_signals:
                        sym = s.get("symbol", "?")
                        direction = s.get("direction", "?")
                        pattern = s.get("pattern", "")
                        price = s.get("price", 0)
                        change = s.get("change_pct", 0)
                        vol_r = s.get("volume_ratio", 0)
                        fresh = s.get("freshness", 0)
                        tier_e = _tier_emojis_rt.get(s.get("confidence_tier", ""), "")
                        ns = s.get("news_score", 0)
                        ns_cat = s.get("news_category", "")
                        ns_hl = s.get("news_headline", "")
                        news_txt = f" · 📰 {ns_cat} ({ns:.2f})" if ns > 0 else ""
                        st.markdown(
                            f"  🔴 **{sym}** {direction} — {pattern} · "
                            f"${price:.2f} ({change:+.1f}%) · vol×{vol_r:.1f} · "
                            f"fresh {fresh:.0%} {tier_e}{news_txt}"
                        )
                        if ns_hl:
                            st.caption(f"    📰 {ns_hl[:120]}")

                if a1_signals:
                    st.markdown("**🟠 A1 — WATCH CLOSELY**")
                    for s in a1_signals:
                        sym = s.get("symbol", "?")
                        direction = s.get("direction", "?")
                        pattern = s.get("pattern", "")
                        price = s.get("price", 0)
                        change = s.get("change_pct", 0)
                        vol_r = s.get("volume_ratio", 0)
                        fresh = s.get("freshness", 0)
                        ns = s.get("news_score", 0)
                        ns_cat = s.get("news_category", "")
                        ns_hl = s.get("news_headline", "")
                        news_txt = f" · 📰 {ns_cat} ({ns:.2f})" if ns > 0 else ""
                        st.markdown(
                            f"  🟠 {sym} {direction} — {pattern} · "
                            f"${price:.2f} ({change:+.1f}%) · vol×{vol_r:.1f} · "
                            f"fresh {fresh:.0%}{news_txt}"
                        )
                        if ns_hl:
                            st.caption(f"    📰 {ns_hl[:120]}")

                if rt_watched:
                    with st.expander(f"Überwachte Symbole ({len(rt_watched)})"):
                        st.write(", ".join(rt_watched))
            elif rt_watched:
                st.info(f"🟢 Realtime: {len(rt_watched)} Symbole überwacht — keine Signale aktiv")
        except Exception as exc:
            # Realtime engine not running or import error — log for diagnostics
            logger.debug("Realtime signals unavailable: %s", exc)

        # ===================================================================
        # 1. v2 TIERED CANDIDATES (primary — most important)
        # ===================================================================
        ranked_v2 = list(result.get("ranked_v2") or [])
        filtered_out_v2 = list(result.get("filtered_out_v2") or [])
        # --- Auto-promote A0/A1 signals that fell below top_n cutoff ---
        try:
            from .realtime_signals import RealtimeEngine as _RealtimeEngine
            _rt_sigs = (_RealtimeEngine.load_signals_from_disk().get("signals") or [])
        except Exception:
            _rt_sigs = []
        ranked_v2, filtered_out_v2, _rt_promoted_syms, _rt_a0a1 = (
            promote_a0a1_signals(ranked_v2, filtered_out_v2, _rt_sigs)
        )

        def _bo_badge(r: dict) -> str:
            """Format breakout/consolidation badge for a candidate row."""
            parts = []
            bo_dir = r.get("breakout_direction")
            if bo_dir:
                bo_pat = r.get("breakout_pattern", "")
                if bo_dir in ("LONG", "B_UP"):
                    parts.append(f"🚀 BO:{bo_dir}" + (f" ({bo_pat})" if bo_pat else ""))
                elif bo_dir in ("SHORT", "B_DOWN"):
                    parts.append(f"🔻 BO:{bo_dir}" + (f" ({bo_pat})" if bo_pat else ""))
            if r.get("is_consolidating"):
                cs = r.get("consolidation_score", 0)
                parts.append(f"📦 Cons({cs:.0%})")
            return " · ".join(parts)

        # Overlay BZ prices on v2 candidates during extended hours
        if _bz_map and ranked_v2:
            _overlay_bz_prices(ranked_v2, _bz_map)

        if ranked_v2:
            promoted = [r for r in ranked_v2 if r.get("rt_promoted")]
            high_conviction = [r for r in ranked_v2 if not r.get("rt_promoted") and r.get("confidence_tier") == "HIGH_CONVICTION"]
            standard = [r for r in ranked_v2 if not r.get("rt_promoted") and r.get("confidence_tier") == "STANDARD"]
            watchlist_tier = [r for r in ranked_v2 if not r.get("rt_promoted") and r.get("confidence_tier") == "WATCHLIST"]

            _n_pipeline = len(ranked_v2) - len(promoted)
            _promo_label = f" + {len(promoted)} RT-promoted" if promoted else ""
            st.subheader(f"v2 Tiered Candidates  ({_n_pipeline} scored{_promo_label})")
            # Show data freshness so the user can tell if v2 is stale
            _v2_source = "Cache" if use_cached_result else "Live"
            st.caption(
                f"Datenquelle: {_v2_source} · Pipeline-Lauf: {updated_berlin_label}"
            )
            if promoted:
                st.markdown(f"**🔥 RT-PROMOTED ({len(promoted)})** — active A0/A1 signals below pipeline cutoff")
                for r in promoted:
                    sym = r.get("symbol", "?")
                    score = r.get("score", 0)
                    gap = r.get("gap_pct", 0)
                    rt_lvl = r.get("rt_level", "?")
                    rt_dir = r.get("rt_direction", "?")
                    rt_pat = r.get("rt_pattern", "")
                    rt_chg = r.get("rt_change_pct", 0)
                    rt_vr = r.get("rt_volume_ratio", 0)
                    pat_txt = f" ({rt_pat})" if rt_pat else ""
                    st.markdown(
                        f"  🔥 **{sym}** ({rt_lvl}) {rt_dir}{pat_txt} · "
                        f"pipeline score {score:.2f} · gap {gap:+.1f}% · "
                        f"RT chg {rt_chg:+.1f}% · vol {rt_vr:.1f}x"
                    )
            if high_conviction:
                st.markdown(f"**🟢 HIGH CONVICTION ({len(high_conviction)})**")
                for r in high_conviction:
                    sym = r.get("symbol", "?")
                    score = r.get("score", 0)
                    gap = r.get("gap_pct", 0)
                    hr = r.get("historical_hit_rate")
                    hr_txt = f" · hist HR: {hr:.0%}" if hr is not None else ""
                    sec = r.get("symbol_sector", "")
                    sec_chg = r.get("sector_change_pct")
                    sec_rel = r.get("sector_relative_gap")
                    sec_txt = f" · {sec} {sec_chg:+.1f}%" if sec and sec_chg is not None else ""
                    rel_txt = f" (rel {sec_rel:+.1f}%)" if sec_rel is not None else ""
                    bo = _bo_badge(r)
                    bo_txt = f" · {bo}" if bo else ""
                    st.markdown(f"  🟢 **{sym}** — score {score:.2f} · gap {gap:+.1f}%{hr_txt}{sec_txt}{rel_txt}{bo_txt}")
            if standard:
                st.markdown(f"**🟡 STANDARD ({len(standard)})**")
                for r in standard:
                    sym = r.get("symbol", "?")
                    score = r.get("score", 0)
                    gap = r.get("gap_pct", 0)
                    sec = r.get("symbol_sector", "")
                    sec_chg = r.get("sector_change_pct")
                    sec_rel = r.get("sector_relative_gap")
                    sec_txt = f" · {sec} {sec_chg:+.1f}%" if sec and sec_chg is not None else ""
                    rel_txt = f" (rel {sec_rel:+.1f}%)" if sec_rel is not None else ""
                    bo = _bo_badge(r)
                    bo_txt = f" · {bo}" if bo else ""
                    st.markdown(f"  🟡 {sym} — score {score:.2f} · gap {gap:+.1f}%{sec_txt}{rel_txt}{bo_txt}")
            if watchlist_tier:
                st.markdown(f"**🔵 WATCHLIST ({len(watchlist_tier)})**")
                for r in watchlist_tier:
                    sym = r.get("symbol", "?")
                    score = r.get("score", 0)
                    gap = r.get("gap_pct", 0)
                    sec = r.get("symbol_sector", "")
                    sec_chg = r.get("sector_change_pct")
                    sec_rel = r.get("sector_relative_gap")
                    sec_txt = f" · {sec} {sec_chg:+.1f}%" if sec and sec_chg is not None else ""
                    rel_txt = f" (rel {sec_rel:+.1f}%)" if sec_rel is not None else ""
                    bo = _bo_badge(r)
                    bo_txt = f" · {bo}" if bo else ""
                    st.markdown(f"  🔵 {sym} — score {score:.2f} · gap {gap:+.1f}%{sec_txt}{rel_txt}{bo_txt}")
        else:
            st.subheader("v2 Tiered Candidates")
            _v2_source = "Cache" if use_cached_result else "Live"
            st.caption(
                f"Datenquelle: {_v2_source} · Pipeline-Lauf: {updated_berlin_label}"
            )
            st.info("Keine v2-Kandidaten (Pipeline hat keine scored).")

        # Filtered Out (v2 stage-1 rejects + below-cutoff)
        # NOTE: filtered_out_v2 was already loaded above (before promotion).
        # Promoted entries have been removed from it.
        _hard_rejected = [fo for fo in filtered_out_v2 if fo.get("filter_reasons") != ["below_top_n_cutoff"]]
        _below_cutoff = [fo for fo in filtered_out_v2 if fo.get("filter_reasons") == ["below_top_n_cutoff"]]
        if _hard_rejected:
            with st.expander(f"Filtered Out ({len(_hard_rejected)} hard-rejected + {len(_below_cutoff)} below cutoff)"):
                for fo in _hard_rejected:
                    sym = fo.get("symbol", "?")
                    reasons = fo.get("filter_reasons", [])
                    gap = fo.get("gap_pct", 0)
                    st.markdown(f"❌ **{sym}** (gap {gap:+.1f}%) — {', '.join(reasons)}")
                if _below_cutoff:
                    st.markdown("---")
                    st.caption(f"Below Top-{len(ranked_v2)} cutoff ({len(_below_cutoff)} symbols scored but not ranked):")
                    for fo in _below_cutoff[:20]:
                        sym = fo.get("symbol", "?")
                        sc = fo.get("score", 0)
                        gap = fo.get("gap_pct", 0)
                        tier = fo.get("confidence_tier", "")
                        st.markdown(f"⬇️ {sym} — score {sc:.2f} · gap {gap:+.1f}% · {tier}")
        elif _below_cutoff:
            with st.expander(f"Below Top-{len(ranked_v2)} cutoff ({len(_below_cutoff)} symbols)"):
                for fo in _below_cutoff[:20]:
                    sym = fo.get("symbol", "?")
                    sc = fo.get("score", 0)
                    gap = fo.get("gap_pct", 0)
                    tier = fo.get("confidence_tier", "")
                    st.markdown(f"⬇️ {sym} — score {sc:.2f} · gap {gap:+.1f}% · {tier}")

        # --- Cross-reference: A0/A1 signals missing from v2 ---
        # Promoted signals are already in ranked_v2, so _v2_symbols
        # includes them and they won't appear here.  This section only
        # shows hard-rejected or not-in-universe signals.
        _v2_symbols = {str(r.get("symbol", "")).upper() for r in ranked_v2}
        _fo_v2_map: dict[str, list[str]] = {
            str(fo.get("symbol", "")).upper(): fo.get("filter_reasons", [])
            for fo in filtered_out_v2
        }
        # Reuse pre-loaded RT signals (from promotion block above)
        _rt_important = [
            s for s in (_rt_a0a1.values() if _rt_a0a1 else [])
        ]
        _missing_from_v2 = [
            s for s in _rt_important
            if str(s.get("symbol", "")).upper() not in _v2_symbols
        ]
        if _missing_from_v2:
            with st.expander(
                f"⚠️ {len(_missing_from_v2)} Realtime-Signal(e) fehlen in v2",
                expanded=True,
            ):
                st.caption(
                    "Diese Symbole haben aktive A0/A1-Signale im Realtime-Engine, "
                    "erscheinen aber nicht in den v2-Kandidaten."
                )
                for ms in _missing_from_v2:
                    ms_sym = str(ms.get("symbol", "?")).upper()
                    ms_level = ms.get("level", "?")
                    ms_dir = ms.get("direction", "?")
                    ms_pat = ms.get("pattern", "")
                    ms_price = ms.get("price", 0)
                    ms_chg = ms.get("change_pct", 0)
                    # Determine reason for absence
                    _fo_reasons = _fo_v2_map.get(ms_sym)
                    if _fo_reasons is not None:
                        reason_txt = f"Hard-filtered: {', '.join(_fo_reasons)}"
                    else:
                        reason_txt = "Nicht im Pipeline-Universum (Auto-Universum enthält Symbol nicht)"
                    emoji = "🔴" if ms_level == "A0" else "🟠"
                    st.markdown(
                        f"  {emoji} **{ms_sym}** ({ms_level}) {ms_dir} — {ms_pat} · "
                        f"${ms_price:.2f} ({ms_chg:+.1f}%) · **{reason_txt}**"
                    )

        # ===================================================================
        # 2. GAP-GO + GAP-WATCHLIST
        # ===================================================================
        earn_warn = sum(
            1 for r in ranked_gap_go
            if "earnings_risk_window" in str(r.get("warn_flags", ""))
        )
        st.subheader(f"LONG GAP-GO  ({len(ranked_gap_go)} Trend-Kandidaten)")
        if earn_warn:
            st.caption(f"⚠️ Earnings-Warnungen in GAP-GO: {earn_warn}")
        if ranked_gap_go:
            st.dataframe(ranked_gap_go, width="stretch", height=320)
        else:
            st.info("Keine GAP-GO Kandidaten (strengere Kriterien nicht erfüllt).")

        with st.expander(f"GAP-WATCHLIST  ({len(ranked_gap_watch)} — prüfen im Chart)"):
            if ranked_gap_watch:
                st.dataframe(ranked_gap_watch, width="stretch", height=320)
            else:
                st.info("Keine Watch-Kandidaten (Gap zu klein oder Datenqualität).")

        # ===================================================================
        # 3. Earnings
        # ===================================================================
        st.subheader(f"Earnings  ({len(ranked_gap_go_earn)} Kandidaten)")
        if ranked_gap_go_earn:
            st.dataframe(ranked_gap_go_earn, width="stretch", height=280)
        else:
            st.info("Keine Earnings-Kandidaten gefunden.")

        # ===================================================================
        # 4. Market Regime
        # ===================================================================
        regime_data = result.get("regime") or {}
        regime_label = regime_data.get("regime", "NEUTRAL") if regime_data else "NEUTRAL"
        regime_colors = {
            "RISK_ON": "#2ecc40",
            "RISK_OFF": "#ff4136",
            "ROTATION": "#ff851b",
            "NEUTRAL": "#aaaaaa",
        }
        regime_color = regime_colors.get(regime_label, "#aaaaaa")
        regime_vix = regime_data.get("vix_level")
        regime_reasons = regime_data.get("reasons", [])
        st.subheader("Market Regime")
        st.markdown(
            f"<div style='padding:0.7rem 1rem;border-radius:0.6rem;background:{regime_color};"
            f"color:white;font-weight:700;font-size:1.2rem;display:inline-block'>"
            f"🏛️ {regime_label}</div>",
            unsafe_allow_html=True,
        )
        rcols = st.columns(3)
        rcols[0].metric("VIX", f"{regime_vix:.1f}" if regime_vix else "N/A")
        rcols[1].metric("Macro Bias", f"{regime_data.get('macro_bias', 0):.4f}")
        rcols[2].metric("Sector Breadth", f"{regime_data.get('sector_breadth', 0):.1f}%")
        if regime_reasons:
            st.caption("Regime factors: " + " · ".join(regime_reasons))

        # ===================================================================
        # 5. Sector Performance
        # ===================================================================
        sector_performance = result.get("sector_performance") or []
        if sector_performance:
            leading = [s for s in sector_performance if s.get("changesPercentage", 0.0) > 0.5]
            lagging = [s for s in sector_performance if s.get("changesPercentage", 0.0) < -0.5]
            neutral = [s for s in sector_performance if -0.5 <= s.get("changesPercentage", 0.0) <= 0.5]
            st.subheader(f"Sector Performance  ({len(sector_performance)} Sektoren)")
            if _session in ("pre-market", "after-hours"):
                st.caption(
                    f"**{_session_label}** — FMP Sektordaten zeigen vorherige Sitzung."
                )
            elif _session == "closed":
                st.caption("**⚫ Markt geschlossen** — Letzte Sitzungsdaten.")
            scols = st.columns(3)
            with scols[0]:
                st.markdown("**🟢 Leading**")
                for s in leading:
                    st.markdown(f"{s['sector_emoji']} **{s['sector']}** — {s['changesPercentage']:+.2f}%")
                if not leading:
                    st.caption("Keine führenden Sektoren")
            with scols[1]:
                st.markdown("**🟡 Neutral**")
                for s in neutral:
                    st.markdown(f"{s['sector_emoji']} {s['sector']} — {s['changesPercentage']:+.2f}%")
                if not neutral:
                    st.caption("—")
            with scols[2]:
                st.markdown("**🔴 Lagging**")
                for s in lagging:
                    st.markdown(f"{s['sector_emoji']} **{s['sector']}** — {s['changesPercentage']:+.2f}%")
                if not lagging:
                    st.caption("Keine zurückfallenden Sektoren")

        # ===================================================================
        # 6. Upgrades / Downgrades
        # ===================================================================
        upgrades_downgrades_data = result.get("upgrades_downgrades") or {}
        if upgrades_downgrades_data:
            ud_rows = []
            for sym, ud in upgrades_downgrades_data.items():
                ud_rows.append({
                    "symbol": sym,
                    "emoji": ud.get("upgrade_downgrade_emoji", "🟡"),
                    "action": ud.get("upgrade_downgrade_action", ""),
                    "firm": ud.get("upgrade_downgrade_firm", ""),
                    "prev_grade": ud.get("upgrade_downgrade_prev_grade") or "—",
                    "new_grade": ud.get("upgrade_downgrade_new_grade") or "—",
                    "date": ud.get("upgrade_downgrade_date") or "—",
                })
            ud_rows.sort(key=lambda r: r.get("date") or "", reverse=True)
            st.subheader(f"Upgrades / Downgrades  ({len(ud_rows)} Analyst Actions, letzte 3 Tage)")
            for r in ud_rows:
                st.markdown(
                    f"{r['emoji']} **{r['symbol']}** — {r['action']}  ·  {r['firm']}  "
                    f"·  {r['prev_grade']} → {r['new_grade']}  ·  {r['date']}"
                )

        # ===================================================================
        # 7. Trade Cards
        # ===================================================================
        st.subheader("Trade Cards")
        st.dataframe(result.get("trade_cards_v2") or result.get("trade_cards") or [], width="stretch", height=320)

        # ===================================================================
        # 8. News Catalyst
        # ===================================================================
        news_by_symbol = result.get("news_catalyst_by_symbol") or {}
        news_hits = [
            {"symbol": sym, "score": info.get("news_catalyst_score", 0.0), **info}
            for sym, info in news_by_symbol.items()
            if isinstance(info, dict) and float(info.get("news_catalyst_score", 0) or 0) > 0
        ]
        news_hits.sort(key=lambda x: -float(x.get("score", 0)))
        st.subheader(f"News Catalyst  ({len(news_hits)} Treffer)")
        if news_hits:
            for hit in news_hits:
                sym = hit.get("symbol", "?")
                score = hit.get("score", 0)
                articles = hit.get("articles") or []
                sent_emoji = hit.get("sentiment_emoji", "🟡")
                sent_label = hit.get("sentiment_label", "neutral")
                sent_score = hit.get("sentiment_score", 0.0)
                st.markdown(
                    f"{sent_emoji} **{sym}** — catalyst: {score:.2f}  ·  sentiment: {sent_label} ({sent_score:+.2f})  ·  {hit.get('mentions_24h', 0)} articles (24h)"
                )
                for art in articles[:5]:
                    title = art.get("title") or "—"
                    link = art.get("link") or ""
                    source = art.get("source") or ""
                    art_date = art.get("date") or ""
                    art_sent = art.get("sentiment", "neutral")
                    art_sent_emoji = {"bullish": "🟢", "bearish": "🔴"}.get(art_sent, "🟡")
                    link_md = f"[{title}]({link})" if link else title
                    st.markdown(f"  - {art_sent_emoji} {link_md}  ·  {source}  ·  {art_date}")
        else:
            st.info("Keine News-Katalysatoren erkannt.")

        # ===================================================================
        # 8b. News Stack (FMP + Benzinga — realtime polling)
        # ===================================================================
        try:
            from newsstack_fmp.config import Config as _NSConfig
            from newsstack_fmp.pipeline import poll_once as _newsstack_poll

            _ns_cfg = _NSConfig()
            ns_candidates = _newsstack_poll(_ns_cfg)

            _cat_emojis = {
                "halt": "🛑", "offering": "💰", "mna": "🤝",
                "guidance": "📊", "earnings": "📈", "fda": "💊",
                "analyst": "🏦", "lawsuit": "⚖️", "other": "📰",
            }
            _src_badge = {"fmp_stock_latest": "FMP", "fmp_press_latest": "FMP-PR",
                          "benzinga_rest": "BZ-REST", "benzinga_ws": "BZ-WS"}
            sources_str = ", ".join(_ns_cfg.active_sources) or "none"
            st.subheader(f"📰 News Stack  ({len(ns_candidates)} Kandidaten · {sources_str})")
            if ns_candidates:
                for nc in ns_candidates[:20]:
                    tk = nc.get("ticker", "?")
                    ns_score = nc.get("news_score", 0)
                    cat = nc.get("category", "other")
                    cat_e = _cat_emojis.get(cat, "📰")
                    hl = nc.get("headline", "")[:120]
                    prov = nc.get("news_provider", "")
                    prov_tag = _src_badge.get(prov, prov)
                    src = nc.get("news_source", "")
                    cluster_n = nc.get("novelty_cluster_count", 1)
                    pol = nc.get("polarity", 0)
                    pol_e = "🟢" if pol > 0 else ("🔴" if pol < 0 else "🟡")
                    url = nc.get("news_url", "")
                    flags = nc.get("warn_flags", [])
                    flags_txt = f"  ⚠️ {','.join(flags)}" if flags else ""
                    link_md = f"[{hl}]({url})" if url else hl
                    st.markdown(
                        f"{cat_e} **{tk}** — score {ns_score:.3f} · {cat} · "
                        f"cluster×{cluster_n} · {pol_e} pol={pol:+.1f} · "
                        f"`{prov_tag}`{flags_txt}\n"
                        f"  {link_md}  ·  {src}"
                    )
            else:
                st.info("Newsstack: keine neuen Kandidaten in diesem Zyklus.")
        except Exception as exc:
            _ns_log = logging.getLogger("open_prep.streamlit_monitor")
            _ns_log.warning("News Stack integration error: %s", exc)
            st.warning(f"News Stack nicht verfügbar: {exc}")

        # ===================================================================
        # 9. Gap Scanner
        # ===================================================================
        all_quotes = list(result.get("enriched_quotes") or result.get("ranked_candidates") or [])
        gap_scanner_results = build_gap_scanner(all_quotes)
        # Overlay BZ prices on gap scanner results during extended hours
        if _bz_map and gap_scanner_results:
            _overlay_bz_prices(gap_scanner_results, _bz_map)
        st.subheader(f"Gap Scanner ({len(gap_scanner_results)} Treffer)")
        if _session in ("pre-market", "after-hours") and _bz_map:
            st.caption(
                f"**{_session_label}** — `bz_price` / `bz_chg_pct` Spalten zeigen "
                "aktuelle Benzinga Delayed Quotes (frischer als FMP-Daten)."
            )
        if gap_scanner_results:
            st.dataframe(gap_scanner_results, width="stretch", height=320)
        else:
            st.info("Keine Gap-Kandidaten gefunden (Threshold / Stale / Spread).")

        # ===================================================================
        # 10. US High Impact Events + Macro
        # ===================================================================
        st.subheader("US High Impact Events (today)")
        st.dataframe(result.get("macro_us_high_impact_events_today") or [], width="stretch", height=280)

        # ===================================================================
        # 11. Earnings Calendar
        # ===================================================================
        st.subheader(f"Earnings Calendar  ({len(earnings_calendar)} Termine, nächste 6 Tage)")
        if earnings_calendar:
            st.dataframe(earnings_calendar, width="stretch", height=320)
        else:
            st.info("Keine Earnings im Kalender (heute + 5 Tage).")

        # ===================================================================
        # 12. Tomorrow Outlook
        # ===================================================================
        tomorrow_outlook = result.get("tomorrow_outlook") or {}
        if tomorrow_outlook:
            outlook_label = tomorrow_outlook.get("outlook_label", "🟡 NEUTRAL")
            outlook_color = tomorrow_outlook.get("outlook_color", "orange")
            next_td = tomorrow_outlook.get("next_trading_day", "—")
            earn_count = tomorrow_outlook.get("earnings_tomorrow_count", 0)
            earn_bmo = tomorrow_outlook.get("earnings_bmo_tomorrow_count", 0)
            hi_events = tomorrow_outlook.get("high_impact_events_tomorrow", 0)
            reasons = tomorrow_outlook.get("reasons") or []
            st.subheader(f"Tomorrow Outlook ({next_td})")
            st.markdown(
                f"<div style='padding:0.7rem 1rem;border-radius:0.6rem;background:{outlook_color};color:white;font-weight:700;font-size:1.1rem'>"
                f"{outlook_label}</div>",
                unsafe_allow_html=True,
            )
            ocols = st.columns(3)
            ocols[0].metric("Earnings Tomorrow", earn_count)
            ocols[1].metric("Earnings BMO", earn_bmo)
            ocols[2].metric("High-Impact Events", hi_events)
            hi_details = tomorrow_outlook.get("high_impact_events_tomorrow_details") or []
            if hi_details:
                detail_lines = [f"- **{d['event']}** ({d['country']}) — {d['date']}" for d in hi_details]
                st.markdown("**Scheduled High-Impact Events:**\n" + "\n".join(detail_lines))
            if reasons:
                st.caption("Factors: " + ", ".join(reasons))

        # ===================================================================
        # 13. Diff View
        # ===================================================================
        run_diff = result.get("diff") or {}
        diff_summary_txt = result.get("diff_summary") or ""
        if run_diff and run_diff.get("has_changes"):
            st.subheader("Changes Since Last Run")
            if diff_summary_txt:
                st.text(diff_summary_txt)
            diff_new = run_diff.get("new_entrants", [])
            diff_dropped = run_diff.get("dropped", [])
            diff_score_ch = run_diff.get("score_changes", [])
            diff_regime_ch = run_diff.get("regime_change")
            dcols = st.columns(3)
            dcols[0].metric("New Entrants", len(diff_new))
            dcols[1].metric("Dropped", len(diff_dropped))
            dcols[2].metric("Score Changes", len(diff_score_ch))
            if diff_new:
                st.markdown("🆕 **New Entrants:** " + ", ".join(diff_new[:20]))
            if diff_dropped:
                st.markdown("❌ **Dropped:** " + ", ".join(diff_dropped[:20]))
            if diff_regime_ch:
                st.warning(f"⚠️ Regime changed: {diff_regime_ch['from']} → {diff_regime_ch['to']}")

        # ===================================================================
        # 14. Watchlist
        # ===================================================================
        watchlist_data = result.get("watchlist") or []
        if watchlist_data:
            st.subheader(f"Watchlist  ({len(watchlist_data)} pinned)")
            for wl in watchlist_data:
                sym = wl.get("symbol", "?")
                note = wl.get("note", "")
                added_at = wl.get("added_at", "")
                source = wl.get("source", "manual")
                source_emoji = "🤖" if source == "auto" else "📌"
                st.markdown(f"{source_emoji} **{sym}** — {note}  ·  added {added_at}")

        # ===================================================================
        # 15. Historical Hit Rates
        # ===================================================================
        hit_rates_data = result.get("historical_hit_rates") or {}
        if hit_rates_data:
            with st.expander(f"Historical Hit Rates ({len(hit_rates_data)} buckets)"):
                for bucket_key, stats in sorted(hit_rates_data.items()):
                    total = stats.get("total", 0)
                    hr = stats.get("hit_rate", 0)
                    avg_pnl = stats.get("avg_pnl_pct", 0)
                    st.markdown(
                        f"**{bucket_key}** — {hr:.0%} hit rate · {total} samples · avg PnL {avg_pnl:+.2f}%"
                    )

        # ===================================================================
        # 16. Legacy Ranked Candidates (Debug)
        # ===================================================================
        with st.expander(f"Legacy Ranked (v1 — {len(ranked_candidates)} candidates, debug)"):
            st.dataframe(ranked_candidates, width="stretch", height=360)

        _render_soft_refresh_status(str(updated_at) if updated_at is not None else None)
        st.subheader("Status")
        cols = st.columns(4)
        cols[0].metric("Letztes Update (Berlin)", updated_berlin_label)
        cols[1].metric("Macro Bias", f"{float(result.get('macro_bias', 0.0)):.4f}")
        cols[2].metric("US High Impact", int(result.get("macro_us_high_impact_event_count_today", 0)))
        cols[3].metric("Kandidaten", len(ranked_candidates))
        cap_summary = result.get("data_capabilities_summary") or {}
        cap_total = int(cap_summary.get("total", 0) or 0)
        cap_unavailable = int(cap_summary.get("unavailable", 0) or 0)
        if cap_total > 0:
            if cap_unavailable == 0:
                st.caption(f"Endpoint-Coverage: ✅ {cap_total}/{cap_total} verfügbar")
            else:
                st.caption(
                    f"Endpoint-Coverage: ⚠️ {cap_unavailable}/{cap_total} optionale Endpoints nicht verfügbar "
                    f"(plan_limited={int(cap_summary.get('plan_limited', 0) or 0)}, "
                    f"not_available={int(cap_summary.get('not_available', 0) or 0)})"
                )
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

        # --- Endpoint Capability Probing ---
        data_capabilities = result.get("data_capabilities") or {}
        if data_capabilities:
            st.subheader("FMP Endpoint Capabilities")
            rows: list[dict[str, Any]] = []
            status_emoji = {
                "available": "🟢",
                "plan_limited": "🟠",
                "not_available": "🟡",
                "error": "🔴",
            }
            for feature, payload in data_capabilities.items():
                status = str(payload.get("status") or "error")
                code = payload.get("http_status")
                detail = str(payload.get("detail") or "")
                rows.append(
                    {
                        "feature": feature,
                        "status": f"{status_emoji.get(status, '⚪')} {status}",
                        "http_status": code,
                        "detail": detail[:180],
                    }
                )
            rows.sort(key=lambda r: str(r.get("feature") or ""))
            st.dataframe(rows, width="stretch", height=220)
            st.caption("🟢 available · 🟠 plan-limited (z. B. 402/403) · 🟡 endpoint missing (404) · 🔴 error")

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
