"""Regression pins for the Pine decision-logic deep-review fixes."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_aggregate_symbol_event_flags_are_scoped_to_exact_csv_tokens() -> None:
    suite = _read("SMC_Long_Dip_Suite.pine")
    alerts = _read("SMC_Long_Dip_Alerts.pine")
    event_overlay = _read("SMC_Event_Overlay.pine")
    hold_manager = _read("SMC_Hold_Manager.pine")

    assert (
        "u.csv_has_symbol_token(mp.HIGH_RISK_EVENT_TICKERS, "
        "current_symbol_key, current_symbol_key_qualified)"
    ) in suite
    assert (
        "u.csv_has_symbol_token(mp.EARNINGS_SOON_TICKERS, "
        "current_symbol_key, current_symbol_key_qualified)"
    ) in suite
    assert (
        "u.csv_has_symbol_token(mp.HIGH_RISK_EVENT_TICKERS, "
        "syminfo.ticker, syminfo.tickerid)"
    ) in alerts
    assert (
        "u.csv_has_symbol_token(mp.EARNINGS_SOON_TICKERS, "
        "syminfo.ticker, syminfo.tickerid)"
    ) in alerts
    assert "ev_sym_block and is_symbol_event" in event_overlay
    assert "ev_earnings_tickers = mp.EARNINGS_SOON_TICKERS" in event_overlay
    assert (
        "u.csv_has_symbol_token(ev_earnings_tickers, "
        "syminfo.ticker, syminfo.tickerid)"
    ) in event_overlay
    assert (
        "u.csv_has_symbol_token(mp.HIGH_RISK_EVENT_TICKERS, "
        "syminfo.ticker, syminfo.tickerid)"
    ) in hold_manager
    assert (
        "u.csv_has_symbol_token(mp.EARNINGS_SOON_TICKERS, "
        "syminfo.ticker, syminfo.tickerid)"
    ) in hold_manager


def test_earnings_membership_never_uses_substring_matching() -> None:
    paths = (
        "SMC_Long_Dip_Suite.pine",
        "SMC_Long_Dip_Strategy.pine",
        "SMC_Long_Dip_Alerts.pine",
        "SMC_Hold_Manager.pine",
    )
    for path in paths:
        source = _read(path)
        assert "str.contains(mp.EARNINGS_TODAY_TICKERS" not in source
        assert "str.contains(mp.EARNINGS_TOMORROW_TICKERS" not in source

    suite = _read("SMC_Long_Dip_Suite.pine")
    strategy = _read("SMC_Long_Dip_Strategy.pine")
    assert (
        "u.csv_has_symbol_token(mp.EARNINGS_TODAY_TICKERS, "
        "current_symbol_key, current_symbol_key_qualified)"
    ) in suite
    assert (
        "u.csv_has_symbol_token(mp.EARNINGS_TOMORROW_TICKERS, "
        "current_symbol_key, current_symbol_key_qualified)"
    ) in suite
    assert (
        "u.csv_has_symbol_token(mp.EARNINGS_TODAY_TICKERS, "
        "syminfo.ticker, syminfo.tickerid)"
    ) in strategy


def test_sd_gate_uses_change_in_regression_slope() -> None:
    utils = _read("SMC++/smc_utils.pine")
    suite = _read("SMC_Long_Dip_Suite.pine")

    assert "float lr_slope = lr0 - lr1" in utils
    assert "lr_slope - lr_slope[1]" in utils
    assert "lr0 - 2.0 * lr1 + lr2" not in utils
    assert "float sd_lr_slope = sd_lr_now - sd_lr_offset" in suite
    assert "sd_lr_slope - sd_lr_slope[1]" in suite
    assert "u.sd_lr2_pct(" not in suite


def test_strict_ltf_sampling_is_not_limited_to_one_calculation_bar() -> None:
    suite = _read("SMC_Long_Dip_Suite.pine")

    assert "request.security_lower_tf(" in suite
    assert "calc_bars_count = 1" not in suite


def test_confluence_quality_bonus_is_normalized_to_five_points() -> None:
    hub = _read("SMC_Confluence_Hub.pine")

    assert (
        "math.min(5.0, math.max(0.0, smc_quality) * 0.05)"
    ) in hub
    assert "math.min(5.0, math.max(0.0, smc_quality) * 2.0)" not in hub


def test_blocked_regime_cannot_render_or_alert_as_trade_zone() -> None:
    hub = _read("SMC_Confluence_Hub.pine")

    assert (
        'bool regime_blocks_trade = smc_connected and '
        'mp.TRADE_STATE == "BLOCKED"'
    ) in hub
    assert "bool trade_zone = confluence >= 70 and not regime_blocks_trade" in hub
    assert 'regime_blocks_trade ? "🔴  BLOCKED"' in hub
    assert "alertcondition(trade_zone and not trade_zone[1] and _alertGate" in hub
    assert "alertcondition(confluence >= 70" not in hub


def test_event_risk_alerts_fire_only_on_live_boundary_or_new_day() -> None:
    suite = _read("SMC_Long_Dip_Suite.pine")
    alerts = _read("SMC_Long_Dip_Alerts.pine")

    assert (
        "not event_risk_gate_ok and barstate.isrealtime and "
        "barstate.isconfirmed and "
        "(barstate.islastconfirmedhistory[1] or _alert_new_day)"
    ) in suite
    assert (
        "barstate.isrealtime and event_risk_active and "
        "(barstate.islastconfirmedhistory[1] or _new_day)"
    ) in alerts
    assert "_alertGate and event_risk_alert_now" in alerts


def test_freshness_v2_labels_have_explicit_trust_semantics() -> None:
    suite = _read("SMC_Long_Dip_Suite.pine")
    alerts = _read("SMC_Long_Dip_Alerts.pine")
    resolvers = _read("SMC++/smc_context_resolvers.pine")
    engine = _read("SMC++/smc_engine_private.pine")

    for consumer in (suite, alerts):
        assert '== "very_fresh" ? "fresh"' in consumer or (
            "== 'very_fresh' ? 'fresh'" in consumer
        )
        assert '== "expired" ? "stale"' in consumer or (
            "== 'expired' ? 'stale'" in consumer
        )
    assert 'sq_freshness == "very_fresh" or sq_freshness == "fresh"' in resolvers
    assert 'sq_freshness == "expired" ? -1' in resolvers
    assert "signal_freshness == 'stale' or signal_freshness == 'expired'" in engine
    assert "signal_freshness == 'fresh' or signal_freshness == 'very_fresh'" in engine


def test_vwap_filter_stays_quality_only_not_an_entry_gate() -> None:
    """Owner decision #4194 (2026-07-29): the VWAP filter feeds the
    context-quality score and the long clean tier (BUS Quality/Vwap rows) and
    is deliberately NOT wired into the ready/entry projections. Wiring it in
    is a measured product change: it needs a shadow/replay result and a NEW
    operator input — `use_vwap_filter` must never be silently repurposed into
    a hard gate. (The VWAP itself is the Pine-default daily-anchored session
    VWAP: `ta.vwap`'s default anchor is `timeframe.change("1D")` — see the
    refuted chart-anchor finding, PR #4192.)"""
    suite = _read("SMC_Long_Dip_Suite.pine")

    ready_call = re.search(
        r"ll\.resolve_long_ready_projection_state\(([^\n]*)\)", suite
    )
    entry_call = re.search(
        r"ll\.resolve_long_entry_projection_state\(([^\n]*)\)", suite
    )
    assert ready_call is not None and entry_call is not None
    assert "vwap" not in ready_call.group(1).lower()
    assert "vwap" not in entry_call.group(1).lower()

    # The context-quality gate (which carries the VWAP weight) feeds exactly
    # two sites: its computation and the BUS ContextQualityRow plot.
    assert suite.count("context_quality_gate_ok") == 2

    doc = _read("docs/PINE_INPUT_SURFACE.md")
    assert "quality-context control, not an entry gate" in doc
