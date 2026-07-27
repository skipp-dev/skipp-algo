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


def _indented_body_after(source: str, condition: str) -> str:
    match = re.search(
        rf"^{re.escape(condition)}\n(?P<body>(?:    [^\n]*\n)+)",
        source,
        flags=re.MULTILINE,
    )
    assert match is not None, f"Missing Pine block: {condition}"
    return match.group("body")


def test_time_stop_clock_starts_at_entry_touch_not_arming() -> None:
    """Waiting in ARMED state must not consume the in-trade time-stop budget."""
    source = _read_source()
    arming_body = _indented_body_after(
        source,
        "if can_act and state == 0 and arm_now",
    )
    entry_body = _indented_body_after(source, "if can_act and entry_touch")

    assert "entry_time_ms := time" not in arming_body
    assert "entry_bar     := bar_index" not in arming_body
    assert "state         := 2" in entry_body
    assert "entry_bar     := bar_index" in entry_body
    assert "entry_time_ms := time" in entry_body


def test_time_stop_requires_an_initialized_entry_clock() -> None:
    source = _read_source()

    assert re.search(
        r"bool time_stop_hit = state == 2 .* not na\(entry_time_ms\) and\n"
        r"\s+\(time - entry_time_ms\)",
        source,
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
    assert "if can_act and state == 1 and use_bus_plan and not bus_plan_valid" in source
    assert "FAIL-CLOSED / WAITING" in source


def test_bus_plan_is_primary_and_manual_values_are_explicit_fallback_only() -> None:
    source = _read_source()

    assert "effective_entry = use_bus_plan ? src_trigger : i_entry" in source
    assert "effective_stop = use_bus_plan ? src_stop : i_stop" in source
    assert "effective_t1 = use_bus_plan ? src_target1" in source
    assert "effective_t2 = use_bus_plan ? src_target2" in source
    assert "manual_arm_edge = not use_bus_plan and manual_plan_valid" in source
    assert "bus_arm_edge = use_bus_plan and bus_plan_valid" in source
    assert "BUS Target1/2/StopLevel sind aktuell NICHT published" not in source
