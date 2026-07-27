"""Behavioral source contracts for the BUS-driven SMC Exit Signal."""

from __future__ import annotations

import re
from pathlib import Path

from scripts.smc_bus_manifest import ENGINE_BUS_LABELS
from tests.smc_manifest_test_utils import extract_input_bindings

ROOT = Path(__file__).resolve().parents[1]
EXIT_SIGNAL = ROOT / "SMC_Exit_Signal.pine"

EXPECTED_BINDINGS = (
    ("BUS SchemaVersion", "g_bus_state"),
    ("BUS Armed", "g_bus_state"),
    ("BUS Confirmed", "g_bus_state"),
    ("BUS Ready", "g_bus_state"),
    ("BUS Trigger", "g_bus_plan"),
    ("BUS Invalidation", "g_bus_plan"),
    ("BUS StopLevel", "g_bus_plan"),
    ("BUS Target1", "g_bus_plan"),
    ("BUS Target2", "g_bus_plan"),
)


def _source() -> str:
    return EXIT_SIGNAL.read_text(encoding="utf-8")


def test_exit_signal_uses_the_complete_critical_bus_plan() -> None:
    source = _source()
    labels = tuple(label for label, _group in EXPECTED_BINDINGS)

    assert extract_input_bindings(source) == EXPECTED_BINDINGS
    assert set(labels) <= set(ENGINE_BUS_LABELS)
    assert tuple(sorted(labels, key=ENGINE_BUS_LABELS.index)) == labels
    assert "EXPECTED_SCHEMA = 7001" in source
    assert "math.round(src_schema) == EXPECTED_SCHEMA" in source


def test_invalid_or_incomplete_bus_plan_fails_closed_before_fill() -> None:
    source = _source()

    for invariant in (
        "src_stop <= src_invalidation",
        "src_invalidation < src_trigger",
        "src_target1 > src_trigger",
        "src_target2 > src_target1",
    ):
        assert invariant in source
    assert (
        "if eval_now and pos_state == 1 and (not any_state or not risk_ok)"
        in source
    )
    assert (
        "if eval_now and pos_state == 1 and any_state and risk_ok and "
        "not na(entry_price) and high >= entry_price"
    ) in source


def test_exit_levels_are_latched_from_bus_without_local_r_multiple_drift() -> None:
    source = _source()

    assert "entry_stop := src_stop" in source
    assert "tp1_price := src_target1" in source
    assert "tp2_price := src_target2" in source
    assert "R-multiple" not in source
    assert re.search(r"src_trigger\s*\+\s*\(src_trigger", source) is None


def test_exit_precedence_and_full_exit_reset_stay_explicit() -> None:
    source = _source()
    stop_pos = source.index("if not na(entry_stop) and close < entry_stop")
    tp1_pos = source.index("if not exit_stop_hit and not tp1_hit_already")
    tp2_pos = source.index("if not exit_stop_hit and not na(tp2_price)")
    reset_pos = source.index("if full_exit")

    assert stop_pos < tp1_pos < tp2_pos < reset_pos
    assert "bool full_exit = exit_stop_hit or exit_tp2_hit or exit_defensive" in source
