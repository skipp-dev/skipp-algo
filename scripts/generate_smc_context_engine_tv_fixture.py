"""Generate the private test-only TradingView fixture for R3 Context Engine.

The generated Pine source is the complete canonical private library converted
to an indicator.  Only the library/export declarations are rewritten; the
detectors, scorers, state, and aggregate implementation remain the canonical
source.  Test-only code then drives the private injected-input seams with the
same vectors used by the repository replay.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from scripts.smc_atomic_write import atomic_write_text

ROOT: Final = Path(__file__).resolve().parents[1]
SOURCE: Final = ROOT / "SMC++" / "smc_context_engine_private.pine"
FIXTURE: Final = ROOT / "tests" / "fixtures" / "pine" / "smc_context_engine_r3_fixture.pine"
MANIFEST: Final = ROOT / "artifacts" / "governance" / "smc_context_engine_tradingview_fixture_manifest.json"


@dataclass(frozen=True)
class RuntimeCase:
    case_id: str
    name: str
    domain: str
    checkpoint_step: int
    diagnostics: tuple[str, ...]


CASES: Final = (
    RuntimeCase(
        "R3-SWEEP-01",
        "immediate stop-hunt reclaim",
        "sweep",
        1,
        ("direction=1", "type=1", "reclaimed=1", "age=0", "quality=5"),
    ),
    RuntimeCase(
        "R3-SWEEP-02",
        "no duplicate while the level remains pierced",
        "sweep",
        2,
        ("direction=1", "type=1", "reclaimed=1", "age=1", "quality=5"),
    ),
    RuntimeCase(
        "R3-SWEEP-03",
        "delayed reclaim",
        "sweep",
        2,
        ("direction=1", "type=3", "reclaimed=1", "age=1", "quality=3"),
    ),
    RuntimeCase(
        "R3-SWEEP-04",
        "event expires after the freshness window",
        "sweep",
        22,
        ("direction=0", "type=0", "fresh=0", "age=21", "quality=0"),
    ),
    RuntimeCase(
        "R3-SWEEP-05",
        "two-sided sweep remains directionally ambiguous",
        "sweep",
        1,
        ("direction=0", "type=1", "bull=1", "bear=1", "quality=5"),
    ),
    RuntimeCase(
        "R3-POOL-01",
        "equal-high cluster becomes a strong buy-side magnet",
        "pool",
        3,
        ("buyStrength=3", "density=3", "magnet=1", "quality=5"),
    ),
    RuntimeCase(
        "R3-POOL-02",
        "taken buy-side pool is removed",
        "pool",
        4,
        ("buyStrength=0", "untestedBuy=0", "magnet=-1", "quality=2"),
    ),
    RuntimeCase(
        "R3-SESSION-01",
        "Asia killzone classification",
        "session",
        0,
        ("sessionCode=1", "killzone=1", "direction=0", "score=2"),
    ),
    RuntimeCase(
        "R3-SESSION-02",
        "London killzone classification",
        "session",
        0,
        ("sessionCode=2", "killzone=1", "direction=0", "score=2"),
    ),
    RuntimeCase(
        "R3-SESSION-03",
        "New York AM bullish session context",
        "session",
        0,
        ("sessionCode=3", "mssBull=1", "direction=1", "score=6"),
    ),
    RuntimeCase(
        "R3-SESSION-04",
        "New York PM bearish session context",
        "session",
        0,
        ("sessionCode=4", "mssBear=1", "direction=-1", "score=6"),
    ),
    RuntimeCase(
        "R3-SESSION-05",
        "out-of-session state resets",
        "session",
        0,
        ("sessionCode=0", "killzone=0", "direction=0", "score=0"),
    ),
    RuntimeCase(
        "R3-CONTEXT-01",
        "bullish three-domain agreement",
        "context",
        0,
        ("bias=1", "directionalScore=3", "availableDomains=3", "quality=93"),
    ),
    RuntimeCase(
        "R3-CONTEXT-02",
        "conflicted context remains neutral",
        "context",
        0,
        ("bias=0", "directionalScore=0", "availableDomains=2", "quality=75"),
    ),
    RuntimeCase(
        "R3-CONTEXT-03",
        "bearish three-domain agreement",
        "context",
        0,
        ("bias=-1", "directionalScore=-3", "availableDomains=3", "quality=100"),
    ),
)

CASE_OPTIONS: Final = ", ".join(f'"{case.case_id}"' for case in CASES)

FIXTURE_SECTION: Final = f"""

// ── TEST-ONLY R3 RUNTIME FIXTURE ────────────────────────────────────────────
// GENERATED FILE. DO NOT PUBLISH OR ADD TO A MANAGED PRODUCT LAYOUT.
g_fixture = "R3 deterministic fixture — TEST ONLY"
string fixture_case = input.string("R3-SWEEP-01", "Case", options = [{CASE_OPTIONS}], group = g_fixture)
int fixture_anchor = input.time(timestamp("20 Jul 2026 13:30 +0000"),
     "Fixture anchor (start Bar Replay before this bar)", group = g_fixture)

_fixture_empty_structure() =>
    StructureFrame.new(0, false, false, 0, na, na, na, na, na, false)

_fixture_structure(int direction, bool fresh) =>
    StructureFrame.new(direction, true, false, direction, na, na, na, na, 0, fresh)

_fixture_empty_imbalance() =>
    ImbalanceFrame.new(false, false, na, na, na, na, na, na, false, false,
         0, 0, false, 0, na, na, false, na, na, 0, 0)

_fixture_imbalance(int direction, bool bpr) =>
    ImbalanceFrame.new(direction == 1, direction == -1,
         direction == 1 ? 101.0 : na, direction == 1 ? 100.0 : na,
         direction == -1 ? 100.0 : na, direction == -1 ? 99.0 : na,
         0.0, 0.0, false, false, direction == 1 ? 2 : 0,
         direction == -1 ? 2 : 0, bpr, direction, na, na, false, na, na,
         direction, bpr ? 3 : direction == 1 ? 1 : 2)

_fixture_empty_zone() =>
    ZoneFrame.new(false, false, na, na, na, na, na, na, 0, 0,
         false, false, false, false, 0, 0)

_fixture_zone(int direction) =>
    ZoneFrame.new(direction == 1, direction == -1, na, na, na, na, na, na,
         direction == 1 ? 2 : 0, direction == -1 ? 2 : 0,
         false, false, false, false, direction, direction == 1 ? 1 : 2)

_fixture_empty_sweep() =>
    SweepFrame.new(false, false, 0, 0, na, na, false, 0, 0.0, 0.0, 0, na, false)

_fixture_sweep(int direction, int quality) =>
    SweepFrame.new(direction == 1, direction == -1, 1, direction, na, na,
         true, -direction, 0.4, 1.3, quality, 0, true)

_fixture_empty_pool() =>
    PoolFrame.new(na, na, 0, 0, 0.0, 0, 0, 0, 0.0, 0, 0)

_fixture_empty_session() =>
    SessionFrame.new(0, false, false, false, 0, false, false, false,
         na, na, na, na, na, na, false, na, na, 0, 0)

_fixture_checkpoint(simple string selected_case) =>
    selected_case == "R3-SWEEP-02" or selected_case == "R3-SWEEP-03" ? 2 :
     selected_case == "R3-SWEEP-04" ? 22 :
     selected_case == "R3-POOL-01" ? 3 :
     selected_case == "R3-POOL-02" ? 4 :
     str.startswith(selected_case, "R3-SWEEP-") ? 1 : 0

_run_fixture(simple string selected_case, int fixture_step, bool fixture_started) =>
    int fixture_kind = 0
    float value_1 = na
    float value_2 = na
    float value_3 = na
    float value_4 = na
    float value_5 = na
    bool passed = false

    bool sweep_case = str.startswith(selected_case, "R3-SWEEP-")
    bool pool_case = str.startswith(selected_case, "R3-POOL-")
    bool session_case = str.startswith(selected_case, "R3-SESSION-")
    bool context_case = str.startswith(selected_case, "R3-CONTEXT-")

    if sweep_case
        fixture_kind := 1
        bool delayed = selected_case == "R3-SWEEP-03" or selected_case == "R3-SWEEP-04"
        bool ambiguous = selected_case == "R3-SWEEP-05"
        float bar_high = fixture_step == 0 ? 95.0 : ambiguous ? 100.4 : 96.0
        float bar_low = fixture_step == 0 ? 92.0 :
             ambiguous ? 89.6 :
             delayed and fixture_step == 1 ? 89.8 :
             delayed ? fixture_step == 2 ? 90.0 : 91.0 :
             fixture_step == 1 ? 89.5 : 89.6
        float bar_close = fixture_step == 0 ? 94.0 :
             ambiguous ? 95.0 :
             delayed and fixture_step == 1 ? 89.9 :
             delayed and fixture_step == 2 ? 90.1 :
             delayed ? 92.0 :
             fixture_step == 1 ? 90.5 : 91.0
        float bar_volume = ambiguous ? 130.0 : delayed ? 100.0 : 150.0
        float pivot_high = fixture_step == 0 ? 100.0 : na
        float pivot_low = fixture_step == 0 ? 90.0 : na
        bool confirmed = fixture_started and fixture_step <= _fixture_checkpoint(selected_case)
        SweepFrame result = _build_sweep_from_inputs(
             bar_high, bar_low, bar_close, bar_volume, 100.0,
             pivot_high, pivot_low, confirmed, 20)
        value_1 := result.direction
        value_2 := result.sweep_type
        value_3 := result.reclaim_active ? 1 : 0
        value_4 := result.bars_since_event
        value_5 := result.quality_score
        passed := selected_case == "R3-SWEEP-01" ?
             result.direction == 1 and result.sweep_type == 1 and result.reclaim_active and result.bars_since_event == 0 and result.quality_score == 5 :
             selected_case == "R3-SWEEP-02" ?
             result.direction == 1 and result.sweep_type == 1 and result.reclaim_active and result.bars_since_event == 1 and result.quality_score == 5 :
             selected_case == "R3-SWEEP-03" ?
             result.direction == 1 and result.sweep_type == 3 and result.reclaim_active and result.bars_since_event == 1 and result.quality_score == 3 :
             selected_case == "R3-SWEEP-04" ?
             result.direction == 0 and result.sweep_type == 0 and not result.fresh and result.bars_since_event == 21 and result.quality_score == 0 :
             result.direction == 0 and result.sweep_type == 1 and result.recent_bull_sweep and result.recent_bear_sweep and result.quality_score == 5
    else if pool_case
        fixture_kind := 2
        float bar_high = fixture_step <= 2 ? 99.0 : fixture_step == 3 ? 99.8 : 100.1
        float bar_low = fixture_step <= 2 ? 94.0 : 99.0
        float bar_close = fixture_step <= 2 ? 95.0 : 99.5
        float pivot_high = fixture_step == 0 ? 100.0 :
             fixture_step == 1 ? 100.05 :
             fixture_step == 2 ? 99.98 : na
        float pivot_low = fixture_step == 0 ? 90.0 : na
        bool confirmed = fixture_started and fixture_step <= _fixture_checkpoint(selected_case)
        PoolFrame result = _build_pool_from_inputs(
             bar_high, bar_low, bar_close, pivot_high, pivot_low,
             confirmed, 0.1, 20)
        value_1 := result.buy_side_strength
        value_2 := result.cluster_density
        value_3 := result.untested_buy_pools
        value_4 := result.magnet_direction
        value_5 := result.quality_score
        passed := selected_case == "R3-POOL-01" ?
             result.buy_side_strength == 3 and result.cluster_density == 3 and
             result.untested_buy_pools == 1 and result.magnet_direction == 1 and
             result.quality_score == 5 :
             na(result.buy_side_level) and result.buy_side_strength == 0 and
             result.untested_buy_pools == 0 and result.magnet_direction == -1 and
             result.quality_score == 2
    else if session_case
        fixture_kind := 3
        int session_code = selected_case == "R3-SESSION-01" ? SESSION_ASIA :
             selected_case == "R3-SESSION-02" ? SESSION_LONDON :
             selected_case == "R3-SESSION-03" ? SESSION_NY_AM :
             selected_case == "R3-SESSION-04" ? SESSION_NY_PM : 0
        bool killzone = session_code == SESSION_ASIA or session_code == SESSION_LONDON or session_code == SESSION_NY_AM
        int direction = selected_case == "R3-SESSION-03" ? 1 :
             selected_case == "R3-SESSION-04" ? -1 : 0
        StructureFrame structure = direction == 0 ? _fixture_empty_structure() : _fixture_structure(direction, true)
        ImbalanceFrame imbalance = direction == 0 ? _fixture_empty_imbalance() :
             _fixture_imbalance(direction, selected_case == "R3-SESSION-04")
        float fixture_vwap = direction == 1 ? 101.0 : direction == -1 ? 99.0 : 100.0
        SessionFrame result = _build_session_from_inputs(
             structure, imbalance, fixture_anchor + fixture_step * 300000,
             105.0, 95.0, fixture_vwap, 100.0, session_code, killzone,
             fixture_started and fixture_step == 0)
        value_1 := result.session_code
        value_2 := result.in_killzone ? 1 : 0
        value_3 := result.direction_bias
        value_4 := result.context_score
        value_5 := result.mss_bull ? 1 : result.mss_bear ? -1 : 0
        passed := selected_case == "R3-SESSION-01" or selected_case == "R3-SESSION-02" ?
             result.session_code == session_code and result.in_killzone and
             result.direction_bias == 0 and result.context_score == 2 :
             selected_case == "R3-SESSION-03" ?
             result.session_code == SESSION_NY_AM and result.in_killzone and
             result.mss_bull and result.direction_bias == 1 and
             result.context_score == 6 and result.range_top == 105.0 and
             result.range_bottom == 95.0 and result.vwap == 101.0 :
             selected_case == "R3-SESSION-04" ?
             result.session_code == SESSION_NY_PM and not result.in_killzone and
             result.mss_bear and result.direction_bias == -1 and
             result.context_score == 6 and result.range_top == 105.0 and
             result.range_bottom == 95.0 and result.vwap == 99.0 :
             result.session_code == 0 and not result.in_killzone and
             result.direction_bias == 0 and result.context_score == 0
    else if context_case
        fixture_kind := 4
        StructureFrame structure = selected_case == "R3-CONTEXT-01" ?
             _fixture_structure(1, true) :
             selected_case == "R3-CONTEXT-02" ?
             _fixture_structure(1, false) : _fixture_structure(-1, true)
        ImbalanceFrame imbalance = selected_case == "R3-CONTEXT-01" ?
             _fixture_imbalance(1, false) : _fixture_imbalance(-1, false)
        ZoneFrame zone = selected_case == "R3-CONTEXT-03" ?
             _fixture_zone(-1) : _fixture_empty_zone()
        SweepFrame sweep = selected_case == "R3-CONTEXT-01" ?
             _fixture_sweep(1, 4) : _fixture_empty_sweep()
        ContextFrame result = _aggregate_context(
             structure, imbalance, zone, sweep, _fixture_empty_pool(),
             _fixture_empty_session())
        value_1 := result.bias
        value_2 := result.directional_score
        value_3 := result.available_domains
        value_4 := result.quality_score
        passed := selected_case == "R3-CONTEXT-01" ?
             result.bias == 1 and result.directional_score == 3 and
             result.available_domains == 3 and result.quality_score == 93 :
             selected_case == "R3-CONTEXT-02" ?
             result.bias == 0 and result.directional_score == 0 and
             result.available_domains == 2 and result.quality_score == 75 :
             result.bias == -1 and result.directional_score == -3 and
             result.available_domains == 3 and result.quality_score == 100

    [fixture_kind, value_1, value_2, value_3, value_4, value_5, passed]

bool fixture_anchor_now = time >= fixture_anchor and nz(time[1], 0) < fixture_anchor
int fixture_anchor_bar = ta.valuewhen(fixture_anchor_now, bar_index, 0)
int fixture_step = na(fixture_anchor_bar) ? -1 : bar_index - fixture_anchor_bar
bool fixture_started = fixture_step >= 0
bool fixture_timeframe_ok = timeframe.isminutes and timeframe.multiplier == 5
int fixture_checkpoint = _fixture_checkpoint(fixture_case)

[fixture_kind, fixture_value_1, fixture_value_2, fixture_value_3,
 fixture_value_4, fixture_value_5, fixture_result] =
     _run_fixture(fixture_case, fixture_step, fixture_started)

bool fixture_done = fixture_started and fixture_step == fixture_checkpoint
bool fixture_pass = fixture_done and fixture_timeframe_ok and fixture_result

plot(fixture_kind, "FIXTURE KIND", display = display.data_window)
plot(fixture_value_1, "FIXTURE VALUE 1", display = display.data_window)
plot(fixture_value_2, "FIXTURE VALUE 2", display = display.data_window)
plot(fixture_value_3, "FIXTURE VALUE 3", display = display.data_window)
plot(fixture_value_4, "FIXTURE VALUE 4", display = display.data_window)
plot(fixture_value_5, "FIXTURE VALUE 5", display = display.data_window)
plot(fixture_checkpoint, "FIXTURE CHECKPOINT STEP", display = display.data_window)
plot(fixture_pass ? 1 : 0, "FIXTURE PASS", display = display.data_window)

if barstate.islast and fixture_started and fixture_step >= fixture_checkpoint and not fixture_pass
    runtime.error("R3 fixture mismatch or replay cursor passed checkpoint: " + fixture_case)
"""


def _replace_once(source: str, old: str, new: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"canonical anchor must occur exactly once, got {count}: {old!r}")
    return source.replace(old, new, 1)


def build_fixture() -> str:
    source = SOURCE.read_text(encoding="utf-8")
    source_sha = hashlib.sha256(source.encode()).hexdigest()
    source = _replace_once(
        source,
        'library("smc_context_engine_private", overlay = true)',
        'indicator("SMC Context Engine R3 Fixture TEST ONLY", overlay = false)\n'
        f"// Canonical source SHA-256: {source_sha}",
    )
    source = re.sub(r"^export ", "", source, flags=re.MULTILINE)
    if re.search(r"^export ", source, flags=re.MULTILINE):
        raise RuntimeError("fixture conversion left an exported declaration")
    return source.rstrip() + FIXTURE_SECTION


def build_manifest(fixture: str) -> dict:
    source = SOURCE.read_text(encoding="utf-8")
    return {
        "schemaVersion": 1,
        "gate": "R3-REMAINING-FRAMES",
        "surfaceClass": "test_only_not_managed_not_publishable",
        "canonicalSource": {
            "path": SOURCE.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(source.encode()).hexdigest(),
        },
        "fixture": {
            "path": FIXTURE.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(fixture.encode()).hexdigest(),
            "scriptName": "SMC Context Engine R3 Fixture TEST ONLY",
            "derivation": "canonical_source_with_library_exports_removed",
        },
        "requiredChart": {
            "symbol": "NASDAQ:AAPL",
            "timeframe": "5",
            "layoutName": "SMC Context Engine R3 Validation",
        },
        "caseCount": len(CASES),
        "cases": [
            {
                "caseId": case.case_id,
                "name": case.name,
                "domain": case.domain,
                "checkpointStep": case.checkpoint_step,
                "expectedDiagnostics": list(case.diagnostics),
                "tradingViewStatus": "pending",
            }
            for case in CASES
        ],
        "operatorRules": [
            "Compile the canonical private library before executing this fixture.",
            "Load this generated fixture only in the isolated validation layout.",
            "Do not publish the fixture or add it to a managed product layout.",
            "Run each case from before the anchor and stop on its exact checkpoint step.",
            "Record only redacted data-window diagnostics and source hashes.",
            "Restore the canonical chart state after the private replay.",
        ],
        "limitations": [
            "The source-derived fixture executes the canonical detector/scorer seams but is not a published library consumer.",
            "IANA timezone calls remain source- and compile-gated here; the separate R5 HTF/session gate owns cross-DST runtime replay.",
        ],
        "gateStatus": "partial",
        "openGates": [
            "Private TradingView compile, private library publication evidence, and fifteen-case runtime replay remain pending."
        ],
    }


def main() -> int:
    fixture = build_fixture()
    atomic_write_text(fixture, FIXTURE)
    atomic_write_text(
        json.dumps(build_manifest(fixture), indent=2, sort_keys=True) + "\n",
        MANIFEST,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
