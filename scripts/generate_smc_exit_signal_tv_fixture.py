"""Generate the private test-only TradingView fixture for R1 Exit Signal.

The fixture is derived from the canonical source and rewires only its external
BUS and OHLC inputs.  Strict anchor replacements fail closed when the canonical
state machine changes, so a stale fixture cannot silently remain green.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final

from scripts.smc_atomic_write import atomic_write_text
from scripts.smc_exit_signal_replay import CASES, ROOT, SOURCE, build_replay_preflight

FIXTURE: Final = ROOT / "tests" / "fixtures" / "pine" / "smc_exit_signal_r1_fixture.pine"
MANIFEST: Final = ROOT / "artifacts" / "governance" / "smc_exit_signal_tradingview_fixture_manifest.json"

TV_CASES: Final = CASES[:11]
CASE_OPTIONS: Final = ", ".join(f'"{case.case_id}"' for case in TV_CASES)

FIXTURE_SECTION: Final = f"""
// ── TEST-ONLY R1 FIXTURE INPUTS ──────────────────────────────────────────────
// GENERATED FILE. DO NOT PUBLISH OR ADD TO A MANAGED PRODUCT LAYOUT.
g_fixture = "R1 deterministic fixture — TEST ONLY"
string fixture_case = input.string("R1-01", "Case", options = [{CASE_OPTIONS}], group = g_fixture)
int fixture_anchor = input.time(timestamp("20 Jul 2026 13:30 +0000"),
     "Fixture anchor (start Bar Replay before this bar)", group = g_fixture)

bool fixture_anchor_now = time >= fixture_anchor and nz(time[1], 0) < fixture_anchor
int fixture_anchor_bar = ta.valuewhen(fixture_anchor_now, bar_index, 0)
int fixture_step = na(fixture_anchor_bar) ? -1 : bar_index - fixture_anchor_bar
bool fixture_started = fixture_step >= 0
bool fixture_timeframe_ok = timeframe.isminutes and timeframe.multiplier == 5

float fixture_high = 99.0
float fixture_close = 98.0
float fixture_schema = 7001.0
float fixture_armed = fixture_started and fixture_timeframe_ok ? 1.0 : 0.0
float fixture_confirmed = 0.0
float fixture_ready = 0.0
float fixture_trigger = 100.0
float fixture_invalidation = 95.0
float fixture_stop = 94.0
float fixture_target1 = 110.0
float fixture_target2 = 120.0

if fixture_case == "R1-02" and fixture_step >= 1
    fixture_high := 106.0
    fixture_close := 104.0
else if fixture_case == "R1-03" and fixture_step == 0
    fixture_high := 101.0
    fixture_close := 93.0
else if fixture_case == "R1-03" and fixture_step > 0
    fixture_armed := 0.0
else if fixture_case == "R1-04"
    fixture_high := fixture_step == 0 ? 112.0 : 105.0
    fixture_close := 105.0
else if fixture_case == "R1-05"
    if fixture_step == 0
        fixture_high := 121.0
        fixture_close := 105.0
    else
        fixture_armed := 0.0
else if fixture_case == "R1-06"
    if fixture_step == 0
        fixture_high := 101.0
        fixture_close := 100.0
    else if fixture_step == 1
        fixture_high := 121.0
        fixture_close := 93.0
    else if fixture_step > 1
        fixture_armed := 0.0
else if fixture_case == "R1-07"
    if fixture_step == 0
        fixture_high := 101.0
        fixture_close := 100.0
    else if fixture_step >= 1
        fixture_high := 111.0
        fixture_close := 105.0
else if fixture_case == "R1-08"
    if fixture_step == 0
        fixture_high := 101.0
        fixture_close := 100.0
    else if fixture_step == 1
        fixture_high := 111.0
        fixture_close := 105.0
    else if fixture_step == 2
        fixture_high := 105.0
        fixture_close := 99.0
    else if fixture_step > 2
        fixture_armed := 0.0
else if fixture_case == "R1-09"
    if fixture_step == 0
        fixture_high := 101.0
        fixture_close := 100.0
    else if fixture_step >= 1
        fixture_high := 105.0
        fixture_close := 102.0
        fixture_armed := 0.0
else if fixture_case == "R1-10"
    fixture_schema := 7000.0
    fixture_high := 121.0
    fixture_close := 105.0
else if fixture_case == "R1-11"
    fixture_stop := 101.0
    fixture_high := 121.0
    fixture_close := 105.0
"""

DIAGNOSTICS_SECTION: Final = """

// ── TEST-ONLY R1 DIAGNOSTICS ────────────────────────────────────────────────
var int fixture_enter_count = 0
var int fixture_stop_count = 0
var int fixture_tp1_count = 0
var int fixture_tp2_count = 0
var int fixture_defensive_count = 0
var int fixture_exit_any_count = 0

if just_entered
    fixture_enter_count += 1
if exit_stop_hit
    fixture_stop_count += 1
if exit_tp1_hit
    fixture_tp1_count += 1
if exit_tp2_hit
    fixture_tp2_count += 1
if exit_defensive
    fixture_defensive_count += 1
if full_exit
    fixture_exit_any_count += 1

int expected_enter = fixture_case == "R1-01" or fixture_case == "R1-10" or fixture_case == "R1-11" ? 0 : 1
int expected_stop = fixture_case == "R1-03" or fixture_case == "R1-06" or fixture_case == "R1-08" ? 1 : 0
int expected_tp1 = fixture_case == "R1-04" or fixture_case == "R1-05" or fixture_case == "R1-07" or fixture_case == "R1-08" ? 1 : 0
int expected_tp2 = fixture_case == "R1-05" ? 1 : 0
int expected_defensive = fixture_case == "R1-09" ? 1 : 0
int expected_exit_any = expected_stop + expected_tp2 + expected_defensive
int expected_state = fixture_case == "R1-01" ? 1 :
     fixture_case == "R1-02" or fixture_case == "R1-04" or fixture_case == "R1-07" ? 2 : 0

bool fixture_done = fixture_step >= 4
bool fixture_pass = fixture_done and fixture_timeframe_ok and
     fixture_enter_count == expected_enter and fixture_stop_count == expected_stop and
     fixture_tp1_count == expected_tp1 and fixture_tp2_count == expected_tp2 and
     fixture_defensive_count == expected_defensive and
     fixture_exit_any_count == expected_exit_any and pos_state == expected_state

plot(fixture_enter_count, "FIXTURE ENTER COUNT", display = display.data_window)
plot(fixture_stop_count, "FIXTURE STOP COUNT", display = display.data_window)
plot(fixture_tp1_count, "FIXTURE TP1 COUNT", display = display.data_window)
plot(fixture_tp2_count, "FIXTURE TP2 COUNT", display = display.data_window)
plot(fixture_defensive_count, "FIXTURE DEFENSIVE COUNT", display = display.data_window)
plot(fixture_exit_any_count, "FIXTURE EXIT ANY COUNT", display = display.data_window)
plot(pos_state, "FIXTURE FINAL STATE", display = display.data_window)
plot(fixture_pass ? 1 : 0, "FIXTURE PASS", display = display.data_window)

if barstate.islast and fixture_done and not fixture_pass
    runtime.error("R1 fixture mismatch: " + fixture_case)
"""


def _replace_once(source: str, old: str, new: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"canonical anchor must occur exactly once, got {count}: {old[:80]!r}")
    return source.replace(old, new, 1)


def build_fixture() -> str:
    source = SOURCE.read_text(encoding="utf-8")
    source_sha = hashlib.sha256(source.encode()).hexdigest()

    source = _replace_once(
        source,
        'indicator("SMC Exit Signal", overlay = true)',
        'indicator("SMC Exit Signal R1 Fixture TEST ONLY", overlay = true)',
    )
    source = _replace_once(
        source,
        'var string g_bus_plan = "4. Expert Mapping - Trade Plan"',
        'var string g_bus_plan = "4. Expert Mapping - Trade Plan"\n'
        f"// Canonical source SHA-256: {source_sha}\n"
        f"{FIXTURE_SECTION.rstrip()}",
    )

    replacements = {
        'move_be_after_tp1 = input.bool(true, "Move stop to break-even after TP1", group = g_plan, tooltip = "After TP1 hits, the displayed Stop bumps up to entry price. The hard-stop alert then fires at break-even instead of the original invalidation. Most-asked-for safety feature.")': "move_be_after_tp1 = true",
        'use_defensive_exit = input.bool(true, "Defensive exit on setup invalidation", group = g_plan, tooltip = "Fire EXIT if the entry-stack collapses (Armed/Confirmed/Ready all drop to false) while still in trade — before stop is hit.")': "use_defensive_exit = true",
        'defensive_grace_bars = input.int(2, "Defensive grace bars", minval = 0, maxval = 20, group = g_plan, tooltip = "Tolerate this many bars of state collapse before firing the defensive exit. Avoids one-bar flickers.")': "defensive_grace_bars = 2",
        'confirm_bars_only = input.bool(true, "Evaluate on confirmed bars only", group = g_plan, tooltip = "Gate state-machine transitions and exit detection to barstate.isconfirmed. Recommended ON to avoid intrabar flicker (re-arm / multi-trigger alerts on the same bar). Turn OFF only if you explicitly want intrabar reactions.")': "confirm_bars_only = true",
        'show_levels = input.bool(true, "Show Stop/TP1/TP2 lines while in trade", group = g_visual)': "show_levels = false",
        'show_labels = input.bool(true, "Show ENTER / EXIT labels", group = g_visual)': "show_labels = false",
        'show_table = input.bool(true, "Show status table", group = g_visual)': "show_table = false",
        'src_schema = input.source(close, "BUS SchemaVersion", group = g_bus_state, display = display.none, tooltip = "Bind all rows to the matching SMC Long-Dip Suite BUS outputs. SchemaVersion must read 7001; otherwise the companion fails closed.")': "src_schema = fixture_schema",
        'src_armed = input.source(close, "BUS Armed", group = g_bus_state, display = display.none)': "src_armed = fixture_armed",
        'src_confirmed = input.source(close, "BUS Confirmed", group = g_bus_state, display = display.none)': "src_confirmed = fixture_confirmed",
        'src_ready = input.source(close, "BUS Ready", group = g_bus_state, display = display.none)': "src_ready = fixture_ready",
        'src_trigger = input.source(close, "BUS Trigger", group = g_bus_plan, display = display.none)': "src_trigger = fixture_trigger",
        'src_invalidation = input.source(close, "BUS Invalidation", group = g_bus_plan, display = display.none)': "src_invalidation = fixture_invalidation",
        'src_stop = input.source(close, "BUS StopLevel", group = g_bus_plan, display = display.none)': "src_stop = fixture_stop",
        'src_target1 = input.source(close, "BUS Target1", group = g_bus_plan, display = display.none)': "src_target1 = fixture_target1",
        'src_target2 = input.source(close, "BUS Target2", group = g_bus_plan, display = display.none)': "src_target2 = fixture_target2",
        "high >= entry_price": "fixture_high >= entry_price",
        "close < entry_stop": "fixture_close < entry_stop",
        "high >= tp1_price": "fixture_high >= tp1_price",
        "high >= tp2_price": "fixture_high >= tp2_price",
    }
    for old, new in replacements.items():
        source = _replace_once(source, old, new)

    return source.rstrip() + DIAGNOSTICS_SECTION


def build_manifest(fixture: str) -> dict:
    source = SOURCE.read_text(encoding="utf-8")
    preflight = build_replay_preflight()
    return {
        "schemaVersion": 1,
        "gate": "R1-REPLAY",
        "surfaceClass": "test_only_not_managed_not_publishable",
        "canonicalSource": {
            "path": SOURCE.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(source.encode()).hexdigest(),
        },
        "fixture": {
            "path": FIXTURE.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(fixture.encode()).hexdigest(),
            "scriptName": "SMC Exit Signal R1 Fixture TEST ONLY",
        },
        "requiredChart": {
            "symbol": "NASDAQ:AAPL",
            "timeframe": "5",
            "layoutName": "SMC Exit Signal R1 Validation",
        },
        "caseCount": len(TV_CASES),
        "cases": [
            {
                "caseId": case["caseId"],
                "name": case["name"],
                "expectedAlertCounts": case["alertCounts"],
                "expectedFinalState": case["finalState"],
                "tradingViewStatus": "pending",
            }
            for case in preflight["cases"][: len(TV_CASES)]
        ],
        "sourceOnlyCase": {
            "caseId": preflight["cases"][11]["caseId"],
            "name": preflight["cases"][11]["name"],
            "reason": "Historical TradingView replay bars are confirmed; intrabar gating remains a canonical source contract.",
        },
        "operatorRules": [
            "Load this generated fixture, never a managed product script or product layout.",
            "Do not publish the fixture.",
            "Run each case from before the fixture anchor and record only redacted pulse counts.",
            "Restore the canonical chart state after the private replay.",
        ],
        "gateStatus": "partial",
        "openGates": ["Private TradingView compile and eleven-case replay evidence is pending."],
    }


def main() -> int:
    fixture = build_fixture()
    manifest = build_manifest(fixture)
    atomic_write_text(fixture, FIXTURE)
    atomic_write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        MANIFEST,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
