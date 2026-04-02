from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from scripts import run_smc_ci_health_checks as ci_script
from scripts import run_smc_release_gates as release_script
from smc_core.scoring import ScoredEvent
from smc_integration.measurement_evidence import MeasurementEvidence


class _Parser:
    def __init__(self, args: Namespace):
        self._args = args

    def parse_args(self) -> Namespace:
        return self._args


def test_ci_health_runner_warn_is_non_blocking_by_default(monkeypatch) -> None:
    monkeypatch.setattr(
        ci_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                symbols="IBG",
                timeframes="15m",
                stale_after_seconds=None,
                fail_on_warn=False,
                output="-",
            )
        ),
    )
    monkeypatch.setattr(ci_script, "run_provider_health_check", lambda **kwargs: {"overall_status": "warn"})
    monkeypatch.setattr(ci_script, "write_provider_health_report", lambda report, output: None)

    assert ci_script.main() == 0


def test_ci_health_runner_warn_can_be_forced_blocking(monkeypatch) -> None:
    monkeypatch.setattr(
        ci_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                symbols="IBG",
                timeframes="15m",
                stale_after_seconds=None,
                fail_on_warn=True,
                output="-",
            )
        ),
    )
    monkeypatch.setattr(ci_script, "run_provider_health_check", lambda **kwargs: {"overall_status": "warn"})
    monkeypatch.setattr(ci_script, "write_provider_health_report", lambda report, output: None)

    assert ci_script.main() == 2


def test_release_runner_is_fail_closed_on_core_failures(monkeypatch) -> None:
    captured_reports: list[dict] = []
    call_kwargs: list[dict] = []

    monkeypatch.setattr(
        release_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                symbols="IBG",
                timeframes="15m",
                stale_after_seconds=3600,
                fail_on_warn=False,
                allow_warn=False,
                skip_publish_contract=True,
                manifest="pine/generated/smc_micro_profiles_generated.json",
                core_engine="SMC_Core_Engine.pine",
                measurement_output_root=None,
                measurement_baseline_summary=None,
                strict_measurement_shadow=False,
                output="-",
            )
        ),
    )

    def _provider_stub(**kwargs):
        call_kwargs.append(kwargs)
        return {
            "overall_status": "fail",
            "failures": [{"code": "MISSING_ARTIFACT", "promoted_by": "release_strict_policy"}],
            "warnings": [],
            "degradations_detected": [],
            "smoke_test_results": [{"symbol": "IBG", "timeframe": "15m"}],
        }

    monkeypatch.setattr(release_script, "run_provider_health_check", _provider_stub)
    monkeypatch.setattr(release_script, "_run_reference_bundle_gate", lambda symbol, timeframe, generated_at: {"name": "reference_bundle", "status": "ok", "details": {}})
    monkeypatch.setattr(release_script, "_run_measurement_gate", lambda symbol, timeframe, output_root, report_output="-", **kwargs: {"name": "measurement_lane", "status": "ok", "blocking": False, "details": {"measurement_manifest_present": False}})
    monkeypatch.setattr(release_script, "_render", lambda report, output: captured_reports.append(report))

    rc = release_script.main()

    assert rc == 1
    assert captured_reports[-1]["overall_status"] == "fail"
    assert call_kwargs[-1]["strict_release_policy"] is True


def test_release_runner_report_and_exit_are_deterministic(monkeypatch) -> None:
    captured_reports: list[dict] = []
    times = [1700000000.0, 1700000000.0]

    monkeypatch.setattr(
        release_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                symbols="IBG",
                timeframes="15m",
                stale_after_seconds=3600,
                fail_on_warn=False,
                allow_warn=True,
                skip_publish_contract=True,
                manifest="pine/generated/smc_micro_profiles_generated.json",
                core_engine="SMC_Core_Engine.pine",
                measurement_output_root=None,
                measurement_baseline_summary=None,
                strict_measurement_shadow=False,
                output="-",
            )
        ),
    )
    monkeypatch.setattr(release_script.time, "time", lambda: times.pop(0))
    monkeypatch.setattr(
        release_script,
        "run_provider_health_check",
        lambda **kwargs: {
            "overall_status": "warn",
            "failures": [],
            "warnings": [{"code": "MISSING_ARTIFACT"}],
            "degradations_detected": [],
            "smoke_test_results": [{"symbol": "IBG", "timeframe": "15m"}],
        },
    )
    monkeypatch.setattr(release_script, "_run_reference_bundle_gate", lambda symbol, timeframe, generated_at: {"name": "reference_bundle", "status": "ok", "details": {"symbol": symbol, "timeframe": timeframe}})
    monkeypatch.setattr(release_script, "_run_measurement_gate", lambda symbol, timeframe, output_root, report_output="-", **kwargs: {"name": "measurement_lane", "status": "ok", "blocking": False, "details": {"measurement_manifest_present": False}})
    monkeypatch.setattr(release_script, "_render", lambda report, output: captured_reports.append(report))

    rc_one = release_script.main()
    rc_two = release_script.main()

    assert rc_one == 0
    assert rc_two == 0
    assert captured_reports[0] == captured_reports[1]


def test_measurement_gate_uses_real_evidence(monkeypatch, tmp_path: Path) -> None:
    evidence = MeasurementEvidence(
        events_by_family={
            "BOS": [{"hit": True, "time_to_mitigation": 1.0, "invalidated": False, "mae": 0.01, "mfe": 0.03}],
            "OB": [],
            "FVG": [],
            "SWEEP": [{"hit": True, "time_to_mitigation": 2.0, "invalidated": False, "mae": 0.005, "mfe": 0.02}],
        },
        stratified_events={
            "htf_bias:BULLISH": {
                "BOS": [{"hit": True, "time_to_mitigation": 1.0, "invalidated": False, "mae": 0.01, "mfe": 0.03}],
                "OB": [],
                "FVG": [],
                "SWEEP": [{"hit": True, "time_to_mitigation": 2.0, "invalidated": False, "mae": 0.005, "mfe": 0.02}],
            }
        },
        scored_events=[ScoredEvent("sw1", "SWEEP", 0.65, True, 1700000000.0)],
        details={
            "measurement_evidence_present": True,
            "evaluated_event_counts": {"BOS": 1, "OB": 0, "FVG": 0, "SWEEP": 1},
            "bars_source_mode": "synthetic_bundle",
        },
        warnings=[],
    )
    monkeypatch.setattr(release_script, "build_measurement_evidence", lambda symbol, timeframe: evidence)

    measurement_root = tmp_path / "measurement"
    report_output = tmp_path / "smc_release_gates_report.json"
    gate = release_script._run_measurement_gate(
        "AAPL",
        "15m",
        output_root=measurement_root,
        report_output=str(report_output),
    )
    measurement_dir = measurement_root / "AAPL" / "15m"
    manifest_path = measurement_dir / "measurement_manifest.json"

    assert gate["status"] == "ok"
    assert gate["details"]["measurement_evidence_present"] is True
    assert gate["details"]["benchmark_event_counts"]["BOS"] == 1
    assert gate["details"]["benchmark_event_counts"]["SWEEP"] == 1
    assert gate["details"]["scoring_event_count"] == 1
    assert gate["details"]["brier_finite"] is True
    assert gate["details"]["measurement_manifest_present"] is True
    assert gate["details"]["scoring_family_metrics"]["SWEEP"]["n_events"] == 1
    assert gate["details"]["scoring_families_present"] == ["SWEEP"]
    assert gate["details"]["measurement_output_dir"] == "measurement/AAPL/15m"
    assert gate["details"]["benchmark_artifact_path"] == "measurement/AAPL/15m/benchmark_AAPL_15m.json"
    assert gate["details"]["scoring_artifact_path"] == "measurement/AAPL/15m/scoring_AAPL_15m.json"
    assert gate["details"]["measurement_manifest_path"] == "measurement/AAPL/15m/measurement_manifest.json"
    assert gate["details"]["stratification_coverage"]["dimensions_present"] == ["htf_bias"]
    assert (measurement_dir / "benchmark_AAPL_15m.json").exists()
    assert (measurement_dir / "manifest.json").exists()
    assert (measurement_dir / "scoring_AAPL_15m.json").exists()
    assert manifest_path.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["symbol"] == "AAPL"
    assert manifest["timeframe"] == "15m"
    assert manifest["artifacts"]["benchmark"]["artifact_path"] == "benchmark_AAPL_15m.json"
    assert manifest["artifacts"]["benchmark"]["manifest_path"] == "manifest.json"
    assert manifest["artifacts"]["scoring"]["artifact_path"] == "scoring_AAPL_15m.json"
    assert manifest["quality_summary"]["benchmark_event_counts"]["BOS"] == 1
    assert manifest["quality_summary"]["n_events"] == 1
    assert manifest["quality_summary"]["family_metrics"]["SWEEP"]["n_events"] == 1


def test_measurement_gate_emits_shadow_degradations_from_baseline(monkeypatch, tmp_path: Path) -> None:
    evidence = MeasurementEvidence(
        events_by_family={
            "BOS": [{"hit": True, "time_to_mitigation": 1.0, "invalidated": False, "mae": 0.01, "mfe": 0.03}],
            "OB": [],
            "FVG": [],
            "SWEEP": [{"hit": True, "time_to_mitigation": 2.0, "invalidated": False, "mae": 0.005, "mfe": 0.02}],
        },
        stratified_events={
            "htf_bias:BULLISH": {
                "BOS": [{"hit": True, "time_to_mitigation": 1.0, "invalidated": False, "mae": 0.01, "mfe": 0.03}],
                "OB": [],
                "FVG": [],
                "SWEEP": [{"hit": True, "time_to_mitigation": 2.0, "invalidated": False, "mae": 0.005, "mfe": 0.02}],
            }
        },
        scored_events=[ScoredEvent("sw1", "SWEEP", 0.65, True, 1700000000.0)],
        details={
            "measurement_evidence_present": True,
            "evaluated_event_counts": {"BOS": 1, "OB": 0, "FVG": 0, "SWEEP": 1},
            "bars_source_mode": "synthetic_bundle",
        },
        warnings=[],
    )
    monkeypatch.setattr(release_script, "build_measurement_evidence", lambda symbol, timeframe: evidence)

    baseline_summary_path = tmp_path / "baseline_summary.json"
    baseline_summary_path.write_text(
        json.dumps(
            {
                "measurement_history": {
                    "history_by_pair": {
                        "AAPL/15m": [
                            {
                                "brier_score": 0.02,
                                "log_score": 0.08,
                                "n_events": 8,
                                "stratification_coverage": {"populated_bucket_count": 3},
                            },
                            {
                                "brier_score": 0.03,
                                "log_score": 0.10,
                                "n_events": 10,
                                "stratification_coverage": {"populated_bucket_count": 3},
                            },
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    gate = release_script._run_measurement_gate(
        "AAPL",
        "15m",
        output_root=tmp_path / "measurement",
        report_output=str(tmp_path / "smc_release_gates_report.json"),
        baseline_summary_path=str(baseline_summary_path),
        strict_measurement_shadow=True,
    )

    assert gate["status"] == "fail"
    assert gate["blocking"] is True
    assert gate["details"]["measurement_shadow_baseline"]["available"] is True
    codes = {row["code"] for row in gate["details"]["measurement_degradations_detected"]}
    assert {
        "MEASUREMENT_BRIER_REGRESSION",
        "MEASUREMENT_LOG_SCORE_REGRESSION",
        "MEASUREMENT_EVENT_COVERAGE_REGRESSION",
        "MEASUREMENT_STRATIFICATION_COVERAGE_REGRESSION",
    }.issubset(codes)
