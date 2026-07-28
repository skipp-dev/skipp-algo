"""Generate the test-only TradingView harness for Hold Manager R2.4.

The canonical indicator intentionally consumes chart OHLC.  A BUS-only fixture
therefore cannot reproduce gap and same-bar cases.  This generator derives a
validation harness from the canonical source and rewires only the external BUS,
OHLC, ATR, recovery, and context inputs to deterministic fixture series.

The generated Pine is not a product surface and must never be published or
added to the managed rollout.  Its embedded canonical source hash and strict
anchor replacements make source drift fail closed.

The one canonical edit that must NOT fail closed is the automated
``smc-library-refresh`` pin bump: it rewrites the canonical's
``smc_micro_profiles_generated/<N>`` import three times per trading day while
the harness itself reads no ``mp.*`` field at all (rewired to fixture series;
pinned by ``test_generated_harness_reads_no_micro_profile_field``).  Hashing and
emitting that import at a frozen version therefore keeps the harness — and the
TradingView compile evidence pinned to it — stable across library republishes
without weakening drift detection for any real source change.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Final

from scripts.smc_atomic_write import atomic_write_text
from scripts.smc_hold_manager_replay import (  # single source of the frozen pin
    build_replay_preflight,
    freeze_library_pin,
)

ROOT: Final = Path(__file__).resolve().parents[1]
SOURCE: Final = ROOT / "SMC_Hold_Manager.pine"
FIXTURE: Final = (
    ROOT / "tests" / "fixtures" / "pine" / "smc_hold_manager_r2_4_fixture.pine"
)
MANIFEST: Final = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_tradingview_fixture_manifest.json"
)

CASE_IDS: Final = tuple(f"R2.4-{number:02d}" for number in range(1, 21))
CASE_OPTIONS: Final = ", ".join(f'"{case_id}"' for case_id in CASE_IDS)

FIXTURE_SECTION: Final = f"""// ── TEST-ONLY R2.4 FIXTURE INPUTS ─────────────────────────────────────────────
// GENERATED FILE. DO NOT PUBLISH. This harness rewires external inputs only;
// the HoldRuntime implementation below is derived from SMC_Hold_Manager.pine.
gFixture = "R2.4 deterministic fixture — TEST ONLY"
string fixture_case = input.string("R2.4-01", "Case", options = [{CASE_OPTIONS}], group = gFixture)
string fixture_reset_variant = input.string("ARMED", "R2.4-11 reset state",
     options = ["NONE", "ARMED", "IN_TRADE", "CLOSED"], group = gFixture)
int fixture_anchor = input.time(timestamp("20 Jul 2026 13:30 +0000"),
     "Fixture anchor (start Bar Replay before this bar)", group = gFixture)

bool fixture_anchor_now = time >= fixture_anchor and nz(time[1], 0) < fixture_anchor
int fixture_anchor_bar = ta.valuewhen(fixture_anchor_now, bar_index, 0)
int fixture_step = na(fixture_anchor_bar) ? -1 : bar_index - fixture_anchor_bar
bool fixture_started = fixture_step >= 0
bool fixture_daily_ok = timeframe.isdaily
bool fixture_five_minute_ok = timeframe.isminutes and timeframe.multiplier == 5
bool fixture_timeframe_ok = fixture_case == "R2.4-20" ? fixture_daily_ok : fixture_five_minute_ok

// Synthetic chart feed. Values after a case's decisive bar remain safe so the
// final diagnostic state is stable while the operator inspects or reloads.
float fixture_open = 98.0
float fixture_high = 99.0
float fixture_low = 97.0
float fixture_close = 98.0
float fixture_atr = 2.0
bool fixture_plan_active = fixture_started and fixture_timeframe_ok
float fixture_schema = 7001.0
float fixture_trigger = 100.0
float fixture_invalidation = 95.0
float fixture_stop = 94.0
float fixture_target1 = 110.0
float fixture_target2 = 120.0
float fixture_quality = 0.8
float fixture_source_kind = 1.0
float fixture_state_code = 1.0

bool fixture_trade_case = fixture_case == "R2.4-02" or fixture_case == "R2.4-04" or
     fixture_case == "R2.4-06" or fixture_case == "R2.4-08" or fixture_case == "R2.4-09" or
     fixture_case == "R2.4-13" or fixture_case == "R2.4-14" or fixture_case == "R2.4-17" or
     fixture_case == "R2.4-18"
if fixture_trade_case and fixture_step > 0
    fixture_open := 104.0
    fixture_high := 106.0
    fixture_low := 101.0
    fixture_close := 104.0

if fixture_case == "R2.4-02" or fixture_case == "R2.4-03"
    if fixture_step >= 205
        fixture_open := 102.0
        fixture_high := 105.0
        fixture_low := 99.0
        fixture_close := 103.0
    if fixture_step > 205
        fixture_open := 104.0
        fixture_high := 106.0
        fixture_low := 101.0
        fixture_close := 104.0
else if fixture_case == "R2.4-04" and fixture_step == 0
    fixture_open := 102.0
    fixture_high := 115.0
    fixture_low := 99.0
    fixture_close := 112.0
else if fixture_case == "R2.4-05" and fixture_step == 0
    fixture_open := 99.0
    fixture_high := 105.0
    fixture_low := 93.0
    fixture_close := 96.0
else if fixture_case == "R2.4-06" and fixture_step == 1
    fixture_open := 104.0
    fixture_high := 106.0
    fixture_low := 103.0
    fixture_close := 105.0
else if fixture_case == "R2.4-07"
    if fixture_step == 0
        fixture_open := 99.0
        fixture_high := 105.0
        fixture_low := 99.0
        fixture_close := 103.0
    else if fixture_step >= 1
        fixture_open := 90.0
        fixture_high := 92.0
        fixture_low := 88.0
        fixture_close := 89.0
else if fixture_case == "R2.4-08"
    if fixture_step == 0
        fixture_open := 99.0
        fixture_high := 105.0
        fixture_low := 99.0
        fixture_close := 103.0
    else if fixture_step >= 1
        fixture_open := 104.0
        fixture_high := 112.0
        fixture_low := 101.0
        fixture_close := 111.0
else if fixture_case == "R2.4-09"
    if fixture_step == 0
        fixture_open := 99.0
        fixture_high := 105.0
        fixture_low := 99.0
        fixture_close := 103.0
    else if fixture_step == 1
        fixture_open := 104.0
        fixture_high := 112.0
        fixture_low := 101.0
        fixture_close := 110.0
    else if fixture_step >= 2
        fixture_open := 109.0
        fixture_high := 111.0
        fixture_low := 108.0
        fixture_close := 109.0
        fixture_atr := 4.0
else if fixture_case == "R2.4-10"
    if fixture_step == 0
        fixture_open := 99.0
        fixture_high := 105.0
        fixture_low := 99.0
        fixture_close := 103.0
    else if fixture_step >= 1
        fixture_open := 104.0
        fixture_high := 121.0
        fixture_low := 101.0
        fixture_close := 120.0
else if fixture_case == "R2.4-11"
    fixture_plan_active := fixture_started and fixture_timeframe_ok and fixture_reset_variant != "NONE"
    if fixture_reset_variant == "IN_TRADE" and fixture_step == 0
        fixture_open := 99.0
        fixture_high := 105.0
        fixture_low := 99.0
        fixture_close := 103.0
    if fixture_reset_variant == "IN_TRADE" and fixture_step > 0
        fixture_open := 104.0
        fixture_high := 106.0
        fixture_low := 101.0
        fixture_close := 104.0
    if fixture_reset_variant == "CLOSED" and fixture_step == 0
        fixture_open := 99.0
        fixture_high := 105.0
        fixture_low := 93.0
        fixture_close := 96.0
else if fixture_case == "R2.4-13"
    if fixture_step == 1
        fixture_open := 99.0
        fixture_high := 105.0
        fixture_low := 99.0
        fixture_close := 103.0
    else if fixture_step >= 2
        fixture_open := 104.0
        fixture_high := 112.0
        fixture_low := 101.0
        fixture_close := 111.0
else if fixture_case == "R2.4-14"
    if fixture_step == 0
        fixture_open := 99.0
        fixture_high := 105.0
        fixture_low := 99.0
        fixture_close := 103.0
    else if fixture_step >= 1
        fixture_open := 104.0
        fixture_high := 106.0
        fixture_low := 101.0
        fixture_close := 104.0
        fixture_trigger := 102.0
        fixture_invalidation := 97.0
        fixture_stop := 96.0
        fixture_target1 := 112.0
        fixture_target2 := 122.0
else if fixture_case == "R2.4-15"
    fixture_schema := 7002.0
else if fixture_case == "R2.4-16"
    fixture_target2 := na
else if fixture_case == "R2.4-17" or fixture_case == "R2.4-18"
    if fixture_step == 0
        fixture_open := 99.0
        fixture_high := 105.0
        fixture_low := 99.0
        fixture_close := 103.0
else if fixture_case == "R2.4-19"
    if fixture_step == 0
        fixture_open := 99.0
        fixture_high := 105.0
        fixture_low := 99.0
        fixture_close := 103.0
    else if fixture_step == 1
        fixture_open := 104.0
        fixture_high := 112.0
        fixture_low := 101.0
        fixture_close := 111.0
    else if fixture_step == 2
        fixture_open := 110.0
        fixture_high := 113.0
        fixture_low := 101.0
        fixture_close := 112.0
    else if fixture_step >= 3
        fixture_open := 101.0
        fixture_high := 106.0
        fixture_low := 99.0
        fixture_close := 100.0
else if fixture_case == "R2.4-20"
    if fixture_step == 0
        fixture_open := 99.0
        fixture_high := 105.0
        fixture_low := 99.0
        fixture_close := 103.0
    else if fixture_step >= 1
        fixture_open := 104.0
        fixture_high := 106.0
        fixture_low := 101.0
        fixture_close := 104.0

string i_plan_source = "Engine BUS v2"
float src_schema = fixture_schema
float src_zone_active = fixture_plan_active ? 1.0 : 0.0
float src_armed = fixture_plan_active ? 1.0 : 0.0
float src_confirmed = 0.0
float src_ready = 0.0
float src_trigger = fixture_trigger
float src_invalidation = fixture_invalidation
float src_quality = fixture_quality
float src_source_kind = fixture_source_kind
float src_state_code = fixture_state_code
float src_stop = fixture_stop
float src_target1 = fixture_target1
float src_target2 = fixture_target2

bool i_arm_long = false
float i_entry = 0.0
float i_stop = 0.0
float i_t1_R = 1.0
float i_t2_R = 2.0
bool i_simple_mode = false
bool i_use_chand = fixture_case == "R2.4-02" or fixture_case == "R2.4-09"
float i_atr_mult = 2.5
bool i_breakeven = true
float i_t1_partial = 50.0
bool i_use_tstop = fixture_case == "R2.4-03" or fixture_case == "R2.4-20"
int i_tstop_min = 90
int i_recovery_at = fixture_case == "R2.4-11" and fixture_step == 1 ? time_close : 0

bool ctx_profile_stale = fixture_case == "R2.4-17" and fixture_started
bool ctx_event_block = fixture_case == "R2.4-18" and fixture_started
bool ctx_earnings = false
string ctx_action_tier = ctx_profile_stale ? "avoid" : "none"

plot(src_schema, "BUS SchemaVersion", display = display.none)
plot(src_zone_active, "BUS ZoneActive", display = display.none)
plot(src_armed, "BUS Armed", display = display.none)
plot(src_confirmed, "BUS Confirmed", display = display.none)
plot(src_ready, "BUS Ready", display = display.none)
plot(src_trigger, "BUS Trigger", display = display.none)
plot(src_invalidation, "BUS Invalidation", display = display.none)
plot(src_quality, "BUS QualityScore", display = display.none)
plot(src_source_kind, "BUS SourceKind", display = display.none)
plot(src_state_code, "BUS StateCode", display = display.none)
plot(src_stop, "BUS StopLevel", display = display.none)
plot(src_target1, "BUS Target1", display = display.none)
plot(src_target2, "BUS Target2", display = display.none)
plot(fixture_open, "Fixture Open", display = display.none)
plot(fixture_high, "Fixture High", display = display.none)
plot(fixture_low, "Fixture Low", display = display.none)
plot(fixture_close, "Fixture Close", display = display.none)
plot(fixture_step, "Fixture Step", display = display.none)
plot(ctx_profile_stale ? 1 : 0, "Fixture ContextStale", display = display.none)
plot(ctx_event_block ? 1 : 0, "Fixture EventWarning", display = display.none)
bgcolor(fixture_started ? color.new(color.orange, 88) : na,
     title = "TEST FIXTURE — NOT FOR TRADING")

"""


def _replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise RuntimeError(
            f"fixture generation anchor must occur exactly once: {old!r}"
        )
    return source.replace(old, new, 1)


#: Diagnostics the R2.4 protocol asks the operator to read. The canonical
#: indicator hides them (``display.none``) because they are not a product
#: surface — but TradingView renders a ``display.none`` plot NOWHERE: "the
#: script calculates the plot values, but does not display them in the script
#: pane, status line, or Data Window" (Pine v6 reference). Inherited verbatim,
#: that made the twenty-case gate unexecutable: neither an operator nor an
#: automated driver can read a value TradingView never shows. The harness is
#: test-only and never published, so it exposes them in the Data Window; the
#: canonical is untouched and stays hidden.
_HIDDEN_DISPLAY: Final = "display = display.none"
_OBSERVABLE_DISPLAY: Final = "display = display.data_window"
#: Guard against a silent partial rewrite: the harness carries the canonical's
#: BUS/HM diagnostics plus the fixture's own feed and pulse counters.
_MIN_OBSERVABLE_DIAGNOSTICS: Final = 30


def expose_diagnostics_in_data_window(fixture: str) -> str:
    """Make every hidden diagnostic readable in TradingView's Data Window."""

    exposed = fixture.count(_HIDDEN_DISPLAY)
    if exposed < _MIN_OBSERVABLE_DIAGNOSTICS:
        raise RuntimeError(
            f"expected at least {_MIN_OBSERVABLE_DIAGNOSTICS} hidden diagnostics "
            f"to expose, found {exposed} — the harness lost its instrumentation "
            "or the canonical changed how it hides plots"
        )
    return fixture.replace(_HIDDEN_DISPLAY, _OBSERVABLE_DISPLAY)


def build_fixture(source: str) -> str:
    """Return a deterministic test harness derived from canonical Pine."""

    source = freeze_library_pin(source)
    source_hash = hashlib.sha256(source.encode()).hexdigest()
    source = _replace_once(
        source,
        "//@version=6\n",
        (
            "//@version=6\n"
            f"// GENERATED FROM SMC_Hold_Manager.pine SHA256 {source_hash}\n"
            "// TEST ONLY — DO NOT PUBLISH OR USE FOR TRADING\n"
        ),
    )
    source = _replace_once(
        source,
        'indicator("SMC Hold Manager",',
        'indicator("SMC Hold Manager R2.4 Fixture",',
    )
    section_one = source.index("// ── 1.  INPUTS")
    section_three = source.index("// ── 3.  PLAN SOURCE")
    source = source[:section_one] + FIXTURE_SECTION + source[section_three:]
    source = _replace_once(
        source,
        "high >= hold.entry_price and\n"
        "     (low <= hold.entry_price or open > hold.entry_price)",
        "fixture_high >= hold.entry_price and\n"
        "     (fixture_low <= hold.entry_price or "
        "fixture_open > hold.entry_price)",
    )
    source = _replace_once(
        source,
        "hold.enter_trade(bar_index, bar_epoch_ms, high)",
        "hold.enter_trade(bar_index, bar_epoch_ms, fixture_high)",
    )
    source = _replace_once(
        source, "float atr = ta.atr(i_atr_len)", "float atr = fixture_atr"
    )
    source = _replace_once(
        source,
        "low <= stop_before_management",
        "fixture_low <= stop_before_management",
    )
    source = _replace_once(
        source, "high >= hold.t2_price", "fixture_high >= hold.t2_price"
    )
    source = _replace_once(
        source, "high >= hold.t1_price", "fixture_high >= hold.t1_price"
    )
    source = _replace_once(
        source,
        "hold.protected_high := na(hold.protected_high) ?\n"
        "         high : math.max(hold.protected_high, high)",
        "hold.protected_high := na(hold.protected_high) ?\n"
        "         fixture_high : math.max(hold.protected_high, fixture_high)",
    )
    source = _replace_once(
        source,
        "// Hidden reconstruction diagnostics for replay/source evidence.\n",
        (
            "// Hidden reconstruction diagnostics for replay/source evidence.\n"
            'plot(ctx_profile_stale ? 1 : 0, "HM ContextStale", '
            "display = display.none)\n"
            'plot(ctx_event_block ? 1 : 0, "HM EventWarning", '
            "display = display.none)\n"
        ),
    )
    source = _replace_once(
        source,
        "statusLbl := label.new(bar_index, high, txt,",
        "statusLbl := label.new(bar_index, fixture_high, txt,",
    )
    source = _replace_once(
        source,
        '         (ctx_event_block ? "\\n⚠ EVENT_BLOCK" : "") +',
        (
            '         (ctx_profile_stale ? "\\n⚠ STALE_CONTEXT" : "") +\n'
            '         (ctx_event_block ? "\\n⚠ EVENT_BLOCK" : "") +'
        ),
    )
    source += """

// Fixture-only cumulative pulse diagnostics. They expose confirmed historical
// counts after reload; they do not claim TradingView server alert delivery.
var int fixture_entry_count = 0
var int fixture_t1_count = 0
var int fixture_t2_count = 0
var int fixture_stop_count = 0
var int fixture_timestop_count = 0
var int fixture_exit_count = 0
if _alertGate and entry_event
    fixture_entry_count += 1
if _alertGate and t1_event
    fixture_t1_count += 1
if _alertGate and t2_hit
    fixture_t2_count += 1
if _alertGate and stop_hit
    fixture_stop_count += 1
if _alertGate and time_stop_hit
    fixture_timestop_count += 1
if _alertGate and exit_edge
    fixture_exit_count += 1
plot(fixture_entry_count, "Fixture HM_ENTRY Count", display = display.none)
plot(fixture_t1_count, "Fixture HM_T1 Count", display = display.none)
plot(fixture_t2_count, "Fixture HM_T2 Count", display = display.none)
plot(fixture_stop_count, "Fixture HM_STOP Count", display = display.none)
plot(fixture_timestop_count, "Fixture HM_TIMESTOP Count", display = display.none)
plot(fixture_exit_count, "Fixture HM_EXIT_ANY Count", display = display.none)
"""
    return expose_diagnostics_in_data_window(source)


def build_manifest(source: str, fixture: str) -> dict[str, object]:
    """Build the operator contract without claiming runtime execution."""

    source = freeze_library_pin(source)
    preflight = build_replay_preflight()
    cases = []
    for case in preflight["cases"]:
        case_id = case["caseId"]
        diagnostics = dict(case["finalDiagnostics"])
        diagnostics["entryEpoch"] = (
            "present" if diagnostics.pop("entryEpochMs") is not None else "absent"
        )
        diagnostics["terminalExitEpoch"] = (
            "present"
            if diagnostics.pop("terminalExitEpochMs") is not None
            else "absent"
        )
        cases.append(
            {
                "caseId": case_id,
                "name": case["name"],
                "requiredTimeframe": "1D" if case_id == "R2.4-20" else "5m",
                "variants": (
                    ["NONE", "ARMED", "IN_TRADE", "CLOSED"]
                    if case_id == "R2.4-11"
                    else []
                ),
                "operatorActions": [
                    *(
                        ["reload while the hidden state is ARMED"]
                        if case_id == "R2.4-12"
                        else []
                    ),
                    *(
                        ["reload after entry and Target 1"]
                        if case_id == "R2.4-13"
                        else []
                    ),
                    "inspect hidden diagnostics and cumulative pulse counts",
                ],
                "expectedAlertCounts": case["alertCounts"],
                "expectedCheckpointDiagnostics": diagnostics,
                "canonicalCoverage": (
                    "blocked_missing_canonical_stale_context_diagnostic"
                    if case_id == "R2.4-17"
                    else "canonical_preconditions_plus_source_derived_harness"
                ),
                "tradingViewStatus": "pending",
            }
        )
    return {
        "schemaVersion": 1,
        "requirementId": "R2-REPLAY",
        "status": "fixture_ready_execution_pending",
        "canonicalSource": {
            "path": SOURCE.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(source.encode()).hexdigest(),
        },
        "fixture": {
            "path": FIXTURE.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(fixture.encode()).hexdigest(),
            "surfaceClass": "test_only_not_managed_not_publishable",
            "defaultAnchor": "2026-07-20T13:30:00Z",
        },
        "caseCount": len(cases),
        "cases": cases,
        "executionProtocol": [
            "Use an isolated TradingView validation layout.",
            "Load this generated fixture, never the managed product layout.",
            "Use 5m for R2.4-01 through R2.4-19 and 1D for R2.4-20.",
            "Start Bar Replay before the configured fixture anchor.",
            "Use regular trading hours so the pinned 5m step schedule is stable.",
            "Select one case, replay past its decisive bars, and inspect hidden diagnostics.",
            "For R2.4-11 execute all four reset variants.",
            "For R2.4-12 and R2.4-13 reload at the stated intermediate state.",
            "Record compile diagnostics, diagnostic values, and pulse counts.",
        ],
        "limitations": [
            "The fixture rewires external BUS, OHLC, ATR, recovery, and context inputs in a generated test harness; it is not the canonical saved script.",
            "The canonical compile and thirteen input.source bindings remain separate precondition evidence.",
            "Cumulative Pine pulse counts prove runtime predicates, not TradingView server alert delivery.",
            "R2.4-17 cannot pass until the canonical Hold Manager exposes Micro-Profile staleness; the current stale flag exists only in this harness.",
            "No case becomes passed until immutable TradingView evidence is reviewed and retained.",
        ],
        "openGates": [
            "Compile and execute all fixture cases in an isolated TradingView layout.",
            "Add and live-verify canonical stale Micro-Profile observability for R2.4-17.",
            "Validate TradingView server alert delivery separately before shadow cutover.",
        ],
    }


def main() -> None:
    """Write both deterministic fixture artifacts."""

    source = SOURCE.read_text(encoding="utf-8")
    fixture = build_fixture(source)
    manifest = build_manifest(source, fixture)
    atomic_write_text(fixture, FIXTURE)  # tempfile+os.replace; mkdirs parent
    atomic_write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        MANIFEST,
    )


if __name__ == "__main__":
    main()
