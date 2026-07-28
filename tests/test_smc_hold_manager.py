"""Behavioral source contracts for the private SMC Hold Manager."""

from __future__ import annotations

import re
from pathlib import Path

from scripts.smc_bus_manifest import ENGINE_BUS_LABELS
from tests.smc_manifest_test_utils import extract_input_bindings

ROOT = Path(__file__).resolve().parents[1]
HOLD_MANAGER = ROOT / "SMC_Hold_Manager.pine"

EXPECTED_BINDINGS = (
    ("BUS SchemaVersion", "gBus"),
    ("BUS ZoneActive", "gBus"),
    ("BUS Armed", "gBus"),
    ("BUS Confirmed", "gBus"),
    ("BUS Ready", "gBus"),
    ("BUS Trigger", "gBus"),
    ("BUS Invalidation", "gBus"),
    ("BUS QualityScore", "gBus"),
    ("BUS SourceKind", "gBus"),
    ("BUS StateCode", "gBus"),
    ("BUS StopLevel", "gBus"),
    ("BUS Target1", "gBus"),
    ("BUS Target2", "gBus"),
)


def _read_source() -> str:
    return HOLD_MANAGER.read_text(encoding="utf-8")


def test_runtime_contains_every_reconstructable_r2_state_field() -> None:
    source = _read_source()
    runtime = re.search(
        r"type HoldRuntime\n(?P<body>(?:    [^\n]+\n)+)",
        source,
    )
    assert runtime is not None

    body = runtime.group("body")
    for field in (
        "phase",
        "entry_price",
        "initial_stop",
        "active_stop",
        "t1_price",
        "t2_price",
        "entry_bar",
        "entry_time_ms",
        "protected_high",
        "t1_hit",
        "terminal_exit_code",
        "terminal_exit_bar",
        "terminal_exit_time_ms",
        "plan_symbol",
        "plan_direction",
        "plan_schema",
        "plan_source_kind",
        "plan_trigger",
        "plan_invalidation",
        "plan_generation",
        "plan_epoch_ms",
    ):
        assert re.search(rf"\b{field}\b", body), field

    assert "var HoldRuntime hold = HoldRuntime.new()" in source
    assert "var int    state" not in source


def test_time_stop_clock_starts_at_confirmed_entry_not_arming() -> None:
    """Waiting in ARMED state must not consume the in-trade time-stop budget."""
    source = _read_source()
    stage_body = re.search(
        r"method stage_plan\(HoldRuntime this,[\s\S]+?\n    this\n",
        source,
    )
    enter_body = re.search(
        r"method enter_trade\(HoldRuntime this,[\s\S]+?\n    this\n",
        source,
    )
    assert stage_body is not None
    assert enter_body is not None

    assert "this.entry_time_ms := na" in stage_body.group(0)
    assert "this.entry_bar := na" in stage_body.group(0)
    assert "this.entry_time_ms := accepted_time" in enter_body.group(0)
    assert "this.entry_bar := accepted_bar" in enter_body.group(0)
    assert "hold.enter_trade(bar_index, bar_epoch_ms, high)" in source


def test_time_stop_requires_initialized_confirmed_entry_epoch() -> None:
    source = _read_source()

    assert "bool can_act = barstate.isconfirmed" in source
    assert "int bar_epoch_ms = na(time_close) ? time : time_close" in source
    assert re.search(
        r"bool time_stop_hit = evaluate_trade .*"
        r"not na\(hold\.entry_time_ms\) and\n"
        r"\s+\(bar_epoch_ms - hold\.entry_time_ms\)",
        source,
        flags=re.DOTALL,
    )


def test_engine_bus_v2_is_the_default_and_complete_plan_source() -> None:
    source = _read_source()
    labels = tuple(label for label, _group in EXPECTED_BINDINGS)

    assert (
        'input.string("Engine BUS v2", "Plan-Quelle",\n'
        '     options = ["Engine BUS v2", "Manual fallback"]'
    ) in source
    assert extract_input_bindings(source) == EXPECTED_BINDINGS
    assert set(labels) <= set(ENGINE_BUS_LABELS)
    assert tuple(sorted(labels, key=ENGINE_BUS_LABELS.index)) == labels
    assert "EXPECTED_SCHEMA = 7001" in source


def test_bus_plan_levels_and_metadata_fail_closed() -> None:
    source = _read_source()

    assert "bus_schema_ok and bus_lifecycle_active and bus_metadata_ok and bus_levels_ok" in source
    for invariant in (
        "src_stop <= src_invalidation",
        "src_invalidation < src_trigger",
        "src_target1 > src_trigger",
        "src_target2 > src_target1",
    ):
        assert invariant in source
    assert (
        "if can_act and hold.phase == PHASE_ARMED and use_bus_plan and "
        "not bus_plan_valid"
    ) in source
    assert "hold.clear_trade()" in source
    assert "FAIL-CLOSED / WAITING" in source


def test_bus_plan_is_primary_and_manual_values_are_explicit_fallback_only() -> None:
    source = _read_source()

    assert "effective_entry = use_bus_plan ? src_trigger : i_entry" in source
    assert "effective_stop = use_bus_plan ? src_stop : i_stop" in source
    assert "effective_t1 = use_bus_plan ? src_target1" in source
    assert "effective_t2 = use_bus_plan ? src_target2" in source
    assert "manual_arm_edge = not use_bus_plan and manual_plan_valid" in source
    assert "bool arm_now = use_bus_plan ? bus_plan_event : manual_arm_edge" in source
    assert "BUS Target1/2/StopLevel sind aktuell NICHT published" not in source


def test_default_bus_install_does_not_enter_manual_price_selection() -> None:
    source = _read_source()

    assert "confirm = true" not in source
    assert 'input.price(0.0 , "Entry / Trigger"' in source
    assert 'input.price(0.0 , "Initial Invalidation"' in source


def test_bus_plan_generation_is_historical_and_identity_complete() -> None:
    source = _read_source()

    assert "bool bus_identity_changed = bus_plan_valid and bus_plan_valid[1]" in source
    assert "bool bus_plan_event = bus_plan_valid and" in source
    assert "hold.bus_generation += 1" in source
    assert "hold.bus_generation_epoch_ms := bar_epoch_ms" in source
    assert "barstate.islast and bus_plan_valid" not in source

    for identity_term in (
        "hold.plan_symbol == ticker.standard(syminfo.tickerid)",
        "hold.plan_direction == 1",
        "hold.plan_schema",
        "hold.plan_source_kind",
        "hold.plan_trigger",
        "hold.plan_invalidation",
        "hold.plan_generation",
    ):
        assert identity_term in source


def test_tradingview_builtin_atr_and_standard_symbol_identity_are_used() -> None:
    source = _read_source()

    assert "import TradingView/ta/" not in source
    assert "float atr = ta.atr(i_atr_len)" in source
    assert "this.plan_symbol := ticker.standard(syminfo.tickerid)" in source
    assert "hold.plan_symbol == ticker.standard(syminfo.tickerid)" in source


def test_new_plan_is_rejected_while_assumed_trade_is_open() -> None:
    source = _read_source()

    assert re.search(
        r"bool new_plan_blocked = can_act and use_bus_plan and\n"
        r"\s+hold\.phase == PHASE_IN_TRADE and bus_plan_event and\n"
        r"\s+not active_plan_matches_bus",
        source,
    )
    assert "hold.last_blocked_generation := hold.bus_generation" in source
    assert "hold.last_blocked_time_ms := bar_epoch_ms" in source
    assert "rejected while in trade" in source


def test_recovery_is_a_replayable_timestamp_event_not_last_bar_toggle() -> None:
    source = _read_source()

    assert 'input.time(0, "Recovery-Zeitpunkt (UTC; 0 = aus)"' in source
    assert "bar_epoch_ms >= i_recovery_at" in source
    assert "nz(bar_epoch_ms[1], 0) < i_recovery_at" in source
    assert "if recovery_now\n    hold.clear_trade()" in source
    assert "i_reset_now" not in source


def test_current_bar_exits_use_previous_protection_before_stop_moves() -> None:
    source = _read_source()

    stop_snapshot = source.index("float stop_before_management = hold.active_stop")
    stop_evaluation = source.index("bool stop_hit = evaluate_trade")
    exit_transition = source.index("if exit_edge")
    breakeven_update = source.index("hold.active_stop := math.max(")
    protected_high_update = source.index(
        "hold.protected_high := na(hold.protected_high)"
    )

    assert (
        stop_snapshot
        < stop_evaluation
        < exit_transition
        < breakeven_update
        < protected_high_update
    )
    assert "STOP > TARGET_2 > TIME_STOP" in source
    assert "bool t2_hit = evaluate_trade and not stop_hit" in source
    assert (
        "bool time_stop_hit = evaluate_trade and not stop_hit and not t2_hit"
        in source
    )
    assert "bool exit_edge = exit_now" in source
    assert "exit_now and not exit_now[1]" not in source


def test_protected_high_and_active_stop_are_monotonic() -> None:
    source = _read_source()

    assert "math.max(hold.protected_high, high)" in source
    assert "hold.protected_high - atr * i_atr_mult" in source
    assert "hold.active_stop := math.max(hold.active_stop, chandelier_next)" in source
    assert "hold.active_stop := math.max(hold.active_stop, hold.entry_price)" in source
    assert "hold.active_stop := math.min" not in source


def test_reconstruction_diagnostics_cover_reload_evidence_fields() -> None:
    source = _read_source()

    expected_hidden_plots = {
        "HM StateCode": "hold.phase",
        "HM PlanGeneration": "hold.plan_generation",
        "HM PlanEpochMs": "hold.plan_epoch_ms",
        "HM EntryEpochMs": "hold.entry_time_ms",
        "HM ProtectedHigh": "hold.protected_high",
        "HM Target1State": "hold.t1_hit ? 1 : 0",
        "HM TerminalExitCode": "hold.terminal_exit_code",
        "HM TerminalExitEpochMs": "hold.terminal_exit_time_ms",
        "HM NewPlanBlocked": "new_plan_blocked ? 1 : 0",
        "HM ContextStale": "ctx_profile_stale ? 1 : 0",
    }
    for title, expression in expected_hidden_plots.items():
        assert re.search(
            rf"plot\({re.escape(expression)}, \"{re.escape(title)}\", "
            r"display = display\.none\)",
            source,
        )


def test_micro_profile_staleness_is_observable_but_not_trade_gating() -> None:
    source = _read_source()

    assert "str.substring(mp.ASOF_DATE, 0, 4)" in source
    assert "str.substring(mp.ASOF_DATE, 5, 7)" in source
    assert "str.substring(mp.ASOF_DATE, 8, 10)" in source
    assert (
        "math.floor((timenow - ctx_asof_ts) / 86400000)"
        in source
    )
    assert "ctx_profile_days_old > 5" in source
    assert "ctx_profile_days_old > 2" not in source
    assert "⚠ STALE_CONTEXT — Indikator neu hinzufügen" in source

    plan_section = source.index("// ── 3.  PLAN SOURCE")
    diagnostic_section = source.index(
        "// Hidden reconstruction diagnostics for replay/source evidence."
    )
    alert_section = source.index("// ── 8.  ALERTS")
    assert "ctx_profile_stale" not in source[plan_section:diagnostic_section]
    assert "ctx_profile_stale" not in source[alert_section:]
    assert source.count("ctx_profile_stale") == 3
