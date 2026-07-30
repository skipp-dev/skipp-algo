"""Truthfulness and freeze gates for the R5 HTF Context technical spike."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.smc_htf_context_r5_spike_manifest import (
    CASES,
    DEFAULT_OUTPUT,
    FIXTURE,
    build_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
TRACE = ROOT / "artifacts/governance/pine_extended_migration_traceability.json"
PLAN = ROOT / "docs/SMC_EXTENDED_PINE_ARCHITECTURE_AND_ROLLOUT_2026-07-26.md"
RUNBOOK = ROOT / "docs/SMC_HTF_CONTEXT_R5_SPIKE_RUNBOOK.md"


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


def test_fixture_runs_the_stateful_context_builder_inside_requests() -> None:
    source = _source()
    code = _code(source)

    assert "preuss_steffen/smc_context_engine_private/4 as ctx" in source
    assert code.count("ctx.build_context_frame()") == 2
    assert "_confirmed_snapshot()" in source
    assert "_current_snapshot()" in source
    assert code.count("request.security(") == 2
    assert "calc_bars_count = CALC_BARS" in source
    assert "const int CALC_BARS = 1000" in source


def test_confirmed_arm_uses_the_documented_non_repainting_pair() -> None:
    source = _code(_source())
    confirmed = source[source.index("_confirmed_snapshot() =>") :]
    confirmed = confirmed[: confirmed.index("_strictly_higher(")]
    request = source[source.index("_request_confirmed(") :]
    request = request[: request.index("_request_raw_15m(")]

    for primitive in (
        "time[1]",
        "time_close[1]",
        "frame.structure.trend[1]",
        "frame.bias[1]",
        "frame.available_domains[1]",
        "frame.quality_score[1]",
        "frame.session.session_code[1]",
        "barstate.isconfirmed[1]",
    ):
        assert primitive in confirmed
    assert "lookahead = barmerge.lookahead_on" in request
    assert "lookahead_off" not in request


def test_unoffset_lookahead_off_arm_is_diagnostic_only_and_default_off() -> None:
    source = _source()

    assert 'bool show_raw_probe = input.bool(\n     false,' in source
    assert "Diagnostic only" in source
    raw = source[source.index("_request_raw_15m(") :]
    raw = raw[: raw.index("HtfSnapshot confirmed_15m")]
    assert "if enabled and _strictly_higher(TF_15M)" in raw
    assert "_current_snapshot()" in raw
    assert "lookahead = barmerge.lookahead_off" in raw
    assert "lookahead_on" not in raw


def test_lower_and_equal_timeframes_fail_closed_before_requesting() -> None:
    source = _source()

    assert (
        "timeframe.in_seconds(requested_tf) > timeframe.in_seconds()" in source
    )
    assert "if _strictly_higher(requested_tf)" in source
    assert "if enabled and _strictly_higher(TF_15M)" in source
    assert source.count("_request_confirmed(TF_15M)") == 1
    assert source.count("_request_confirmed(TF_1H)") == 1
    assert source.count("_request_confirmed(TF_4H)") == 1


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


def test_r5_traceability_is_partial_until_private_runtime_evidence_exists() -> None:
    requirement = _requirement("R5-HTF-SPIKE")

    assert requirement["status"] == "partial"
    assert requirement["openGates"]
    for path in (
        FIXTURE.relative_to(ROOT).as_posix(),
        DEFAULT_OUTPUT.relative_to(ROOT).as_posix(),
        "scripts/smc_htf_context_r5_spike_manifest.py",
        "tests/test_smc_htf_context_r5_spike.py",
        RUNBOOK.relative_to(ROOT).as_posix(),
    ):
        assert path in requirement["evidence"]


def test_plan_no_longer_claims_lookahead_off_alone_is_confirmed() -> None:
    plan = PLAN.read_text(encoding="utf-8")

    assert "one requested-context bar" in plan
    assert "`barmerge.lookahead_on`" in plan
    assert "`lookahead_off` remains in the spike only as a diagnostic" in plan
