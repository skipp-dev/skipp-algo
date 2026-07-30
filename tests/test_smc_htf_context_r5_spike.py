"""Truthfulness and freeze gates for the R5 HTF Context technical spike."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.smc_htf_context_r5_spike_manifest import (
    CASES,
    DEFAULT_OUTPUT,
    FIXTURE,
    build_manifest,
)
from scripts.smc_htf_context_r5_temporal_closeout_manifest import (
    DEFAULT_OUTPUT as TEMPORAL_CLOSEOUT,
)
from scripts.smc_htf_context_r5_temporal_closeout_manifest import (
    build_manifest as build_temporal_closeout_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
TRACE = ROOT / "artifacts/governance/pine_extended_migration_traceability.json"
PLAN = ROOT / "docs/SMC_EXTENDED_PINE_ARCHITECTURE_AND_ROLLOUT_2026-07-26.md"
RUNBOOK = ROOT / "docs/SMC_HTF_CONTEXT_R5_SPIKE_RUNBOOK.md"
EVIDENCE = (
    ROOT
    / "artifacts/governance/smc_htf_context_r5_spike_tradingview_2026-07-30.json"
)
TEMPORAL_EVIDENCE = (
    ROOT
    / "artifacts/governance/"
    "smc_htf_context_r5_temporal_closeout_tradingview_2026-07-30.json"
)


def _source() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def _code(source: str) -> str:
    return "\n".join(
        line.split("//", 1)[0]
        for line in source.splitlines()
        if not line.lstrip().startswith("//")
    )


def _requirement(requirement_id: str) -> dict:
    trace = json.loads(TRACE.read_text(encoding="utf-8"))
    return next(
        requirement
        for phase in trace["phases"]
        for requirement in phase["requirements"]
        if requirement["id"] == requirement_id
    )


def test_generated_manifest_is_current() -> None:
    assert json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8")) == build_manifest()


def test_temporal_closeout_manifest_is_current_and_closes_only_open_cases() -> None:
    manifest = build_temporal_closeout_manifest()
    cases = manifest["cases"]

    assert json.loads(TEMPORAL_CLOSEOUT.read_text(encoding="utf-8")) == manifest
    assert manifest["caseCount"] == len(cases) == 3
    assert {case["closesCaseId"] for case in cases} == {
        "R5-HTF-08",
        "R5-DST-04",
        "R5-DST-05",
    }
    assert all(case["tradingViewStatus"] == "pending" for case in cases)
    assert all(
        checkpoint["gateBlocking"] is False
        for checkpoint in manifest["futureRevalidation"]
    )


def test_historical_autumn_checkpoints_match_the_registered_zone_offsets() -> None:
    manifest = build_temporal_closeout_manifest()
    cases = {case["closesCaseId"]: case for case in manifest["cases"]}
    new_york = ZoneInfo("America/New_York")
    berlin = ZoneInfo("Europe/Berlin")

    europe_only_gap = datetime.fromisoformat(
        cases["R5-DST-04"]["checkpointUtc"].replace("Z", "+00:00")
    )
    after_us_fall = datetime.fromisoformat(
        cases["R5-DST-05"]["checkpointUtc"].replace("Z", "+00:00")
    )

    assert europe_only_gap.astimezone(new_york).isoformat() == (
        "2025-10-27T09:45:00-04:00"
    )
    assert europe_only_gap.astimezone(berlin).isoformat() == (
        "2025-10-27T14:45:00+01:00"
    )
    assert after_us_fall.astimezone(new_york).isoformat() == (
        "2025-11-03T09:45:00-05:00"
    )
    assert after_us_fall.astimezone(berlin).isoformat() == (
        "2025-11-03T15:45:00+01:00"
    )


def test_temporal_closeout_evidence_closes_all_three_cases_and_restores_chart() -> None:
    evidence = json.loads(TEMPORAL_EVIDENCE.read_text(encoding="utf-8"))
    expected_manifest_sha = hashlib.sha256(TEMPORAL_CLOSEOUT.read_bytes()).hexdigest()

    assert evidence["manifest"]["sha256"] == expected_manifest_sha
    assert evidence["results"]["status"] == "passed"
    assert evidence["results"]["passedLogicalCases"] == 3
    assert evidence["results"]["failedLogicalCases"] == 0
    assert evidence["results"]["pendingLogicalCases"] == 0
    by_id = {case["caseId"]: case for case in evidence["results"]["cases"]}
    assert set(by_id) == {
        "R5-HTF-08",
        "R5-DST-04-HISTORICAL-EQUIVALENT",
        "R5-DST-05-HISTORICAL-EQUIVALENT",
    }
    assert by_id["R5-HTF-08"]["observed"][
        "confirmedSourceCloseStableUntilBoundary"
    ] == 1
    assert by_id["R5-HTF-08"]["observed"]["rawDiffersFromConfirmed"] == 1
    assert by_id["R5-DST-04-HISTORICAL-EQUIVALENT"]["observed"] == {
        "sourceOpenUtc": "2025-10-27T13:30:00Z",
        "sourceCloseUtc": "2025-10-27T13:45:00Z",
        "sessionCode": 3,
        "sourceConfirmed": 1,
        "publishEdge": 1,
        "rawProbeEnabled": 0,
    }
    assert by_id["R5-DST-05-HISTORICAL-EQUIVALENT"]["observed"] == {
        "sourceOpenUtc": "2025-11-03T14:30:00Z",
        "sourceCloseUtc": "2025-11-03T14:45:00Z",
        "sessionCode": 3,
        "sourceConfirmed": 1,
        "publishEdge": 1,
        "rawProbeEnabled": 0,
    }
    assert evidence["gate"]["status"] == "complete"
    restored = evidence["tradingView"]["canonicalStateAfterRestore"]
    assert evidence["tradingView"]["canonicalChartStateRestored"] is True
    assert restored["replayActive"] is False
    assert restored["fixtureOnChart"] is False
    assert restored["objectTreeAndDataWindowOpen"] is False
    assert restored["layoutSaved"] is True
    assert restored["reloadVerified"] is True


def test_fixture_runs_the_stateless_fallback_inside_requests() -> None:
    source = _source()
    code = _code(source)

    assert "smc_context_engine_private" not in code
    assert "ctx.build_context_frame()" not in code
    assert "_stateless_metrics()" in source
    assert "ta.ema(close, FAST_LEN)" in source
    assert "ta.rsi(close, RSI_LEN)" in source
    assert "ta.atr(ATR_LEN)" in source
    assert "_confirmed_tuple()" in source
    assert "_current_tuple()" in source
    assert "type HtfSnapshot" not in code
    assert code.count("request.security(") == 4
    assert "calc_bars_count = CALC_BARS" in source
    assert "const int CALC_BARS = 1000" in source


def test_confirmed_arm_uses_the_documented_non_repainting_pair() -> None:
    source = _code(_source())
    confirmed = source[source.index("_confirmed_tuple() =>") :]
    confirmed = confirmed[: confirmed.index("_strictly_higher(")]
    request = source[source.index("[c15_available_raw") :]
    request = request[: request.index("[r15_available_raw")]

    for primitive in (
        "time[1]",
        "time_close[1]",
        "structure_trend[1]",
        "context_bias[1]",
        "available_domains[1]",
        "quality_score[1]",
        "session_code[1]",
        "barstate.isconfirmed[1]",
    ):
        assert primitive in confirmed
    assert "lookahead = barmerge.lookahead_on" in request
    assert "lookahead_off" not in request


def test_unoffset_lookahead_off_arm_is_diagnostic_only_and_default_off() -> None:
    source = _source()

    assert 'bool show_raw_probe = input.bool(\n     false,' in source
    assert "Diagnostic only" in source
    raw = source[source.index("[r15_available_raw") :]
    raw = raw[: raw.index("bool relation_15m")]
    assert "_current_tuple()" in raw
    assert "lookahead = barmerge.lookahead_off" in raw
    assert "lookahead_on" not in raw
    assert "bool raw_available = show_raw_probe and relation_15m" in source


def test_lower_and_equal_timeframes_fail_closed_after_fixed_requests() -> None:
    source = _source()

    assert (
        "timeframe.in_seconds(requested_tf) > timeframe.in_seconds()" in source
    )
    assert "bool inspected_available = inspected_relation and selected_available_raw" in source
    assert "int inspected_open_ms = inspected_available ? selected_open_ms_raw : na" in source
    assert "bool raw_available = show_raw_probe and relation_15m" in source
    assert source.count("bool relation_15m = _strictly_higher(TF_15M)") == 1
    assert source.count("bool relation_1h = _strictly_higher(TF_1H)") == 1
    assert source.count("bool relation_4h = _strictly_higher(TF_4H)") == 1


def test_request_expressions_are_fixed_primitive_tuples() -> None:
    source = _source()

    assert "if _strictly_higher" not in source
    assert "if enabled and _strictly_higher" not in source
    assert source.count("_confirmed_tuple(),") == 3
    assert source.count("_current_tuple(),") == 1
    assert "Primitive tuples avoid the object-memory failure mode" in source


def test_tuple_helpers_close_with_square_brackets() -> None:
    source = _code(_source())
    current = source[source.index("_current_tuple() =>") :]
    current = current[: current.index("_confirmed_tuple() =>")]
    confirmed = source[source.index("_confirmed_tuple() =>") :]
    confirmed = confirmed[: confirmed.index("_strictly_higher(")]

    assert current.rstrip().endswith("]")
    assert confirmed.rstrip().endswith("]")


def test_spike_has_no_product_or_drawing_side_effects() -> None:
    source = _source()

    assert "strategy(" not in source
    assert "alert(" not in source
    assert "alertcondition(" not in source
    for constructor in ("label.new(", "line.new(", "box.new(", "table.new("):
        assert constructor not in source
    assert source.count("plot(") == 15
    assert "display = display.data_window" in source


def test_matrix_covers_timeframes_realtime_dst_sessions_and_performance() -> None:
    manifest = build_manifest()
    cases = manifest["cases"]
    tradingview = manifest["requiredTradingView"]

    assert manifest["caseCount"] == len(CASES) == 15
    assert {case["category"] for case in cases} == {
        "compile",
        "timeframe",
        "timeframe_relation",
        "repaint_probe",
        "dst",
        "session",
        "performance",
    }
    assert {case["inspect_timeframe"] for case in cases} >= {"15", "60", "240"}
    assert {case["session_mode"] for case in cases} == {"regular", "extended"}
    assert {case["runtime_mode"] for case in cases} >= {
        "compile",
        "replay",
        "live_observation",
        "profiler",
    }
    assert all(case["tradingViewStatus"] == "pending" for case in cases)
    assert all(case["expected_diagnostics"] for case in cases)
    assert manifest["statusSemantics"].startswith(
        "Per-case tradingViewStatus values preserve the preregistered baseline."
    )
    assert manifest["resultEvidence"] == EVIDENCE.relative_to(ROOT).as_posix()
    assert (
        manifest["temporalCloseoutManifest"]
        == TEMPORAL_CLOSEOUT.relative_to(ROOT).as_posix()
    )
    assert tradingview == {
        "layoutName": "SMC HTF Context R5 Validation",
        "symbol": "NASDAQ:AAPL",
        "chartTimeframes": ["5", "15", "60", "240"],
        "defaultChartTimeframe": "5",
        "savedScript": "SMC HTF Context R5 Spike TEST ONLY",
        "visibility": "private",
        "publicationAllowed": False,
    }


def test_dst_matrix_proves_us_and_europe_switch_on_different_dates() -> None:
    cases = {case.case_id: case for case in CASES}

    assert cases["R5-DST-01"].checkpoint_utc == "2026-03-06T14:45:00Z"
    assert cases["R5-DST-02"].checkpoint_utc == "2026-03-09T13:45:00Z"
    assert cases["R5-DST-03"].checkpoint_utc == "2026-03-30T13:45:00Z"
    assert cases["R5-DST-04"].checkpoint_utc == "2026-10-26T13:45:00Z"
    assert cases["R5-DST-05"].checkpoint_utc == "2026-11-02T14:45:00Z"
    assert all(
        "sessionCode=3" in cases[case_id].expected_diagnostics
        for case_id in (
            "R5-DST-01",
            "R5-DST-02",
            "R5-DST-03",
            "R5-DST-04",
            "R5-DST-05",
        )
    )


def test_partial_private_runtime_evidence_is_truthfully_scoped() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    cases = evidence["results"]["cases"]
    by_id = {case["caseId"]: case for case in cases}

    assert evidence["fixture"]["sha256"] == build_manifest()["fixture"]["sha256"]
    assert (
        evidence["fixture"]["sourceReadbackSha256"]
        == evidence["fixture"]["sha256"]
    )
    assert evidence["fixture"]["compileStatus"] == "passed"
    assert evidence["fixture"]["publicationStatus"] == "not_published"
    assert evidence["implementationDecision"]["rejectedReason"].startswith(
        "CE10061"
    )
    assert evidence["results"]["status"] == "partial"
    assert evidence["results"]["passedLogicalCases"] == 12
    assert evidence["results"]["pendingLogicalCases"] == 3
    assert evidence["results"]["failedLogicalCases"] == 0
    assert {case["caseId"] for case in cases} == {
        runtime_case.case_id for runtime_case in CASES
    }
    assert evidence["results"]["pendingCases"] == [
        "R5-HTF-08",
        "R5-DST-04",
        "R5-DST-05",
    ]
    assert by_id["R5-HTF-08"]["status"] == "pending_live_market_condition"
    assert by_id["R5-DST-04"]["status"] == "pending_future_checkpoint"
    assert by_id["R5-DST-05"]["status"] == "pending_future_checkpoint"
    assert by_id["R5-PERF-01"]["status"] == "passed"
    profiler = by_id["R5-PERF-01"]["observed"]
    assert profiler["uniqueRequestSites"] == 4
    assert profiler["drawingObjects"] == 0
    assert profiler["memoryError"] == profiler["runtimeError"] == 0
    assert profiler["profilerModeCaptured"] is True
    assert profiler["absoluteRuntimeExposedByEditor"] is False
    assert profiler["visibleLineRuntimeShares"]
    assert evidence["tradingView"]["canonicalChartStateRestored"] is True
    restored = evidence["tradingView"]["canonicalStateAfterRestore"]
    assert restored["session"] == "regular"
    assert restored["timezone"] == "Europe/Berlin"
    assert restored["replayActive"] is False
    assert restored["fixtureOnChart"] is False
    assert restored["profilerMode"] is False
    assert restored["layoutSaved"] is True


def test_r5_traceability_points_to_the_executable_temporal_closeout() -> None:
    requirement = _requirement("R5-HTF-SPIKE")

    assert requirement["status"] == "complete"
    assert requirement["openGates"] == []
    for path in (
        FIXTURE.relative_to(ROOT).as_posix(),
        DEFAULT_OUTPUT.relative_to(ROOT).as_posix(),
        EVIDENCE.relative_to(ROOT).as_posix(),
        TEMPORAL_CLOSEOUT.relative_to(ROOT).as_posix(),
        TEMPORAL_EVIDENCE.relative_to(ROOT).as_posix(),
        "scripts/smc_htf_context_r5_spike_manifest.py",
        "scripts/smc_htf_context_r5_temporal_closeout_manifest.py",
        "tests/test_smc_htf_context_r5_spike.py",
        RUNBOOK.relative_to(ROOT).as_posix(),
    ):
        assert path in requirement["evidence"]


def test_plan_no_longer_claims_lookahead_off_alone_is_confirmed() -> None:
    plan = PLAN.read_text(encoding="utf-8")

    assert "one requested-context bar" in plan
    assert "`barmerge.lookahead_on`" in plan
    assert "`lookahead_off` remains in the spike only as a diagnostic" in plan
