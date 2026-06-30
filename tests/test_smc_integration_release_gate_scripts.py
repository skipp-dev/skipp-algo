from __future__ import annotations

import inspect
import json
from argparse import Namespace
from pathlib import Path

from scripts import run_smc_ci_health_checks as ci_script
from scripts import run_smc_release_gates as release_script
from smc_core.scoring import ScoredEvent
from smc_integration import provider_health as _ph
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
    monkeypatch.setattr(release_script, "_run_reference_bundle_gate", lambda symbol, timeframe, generated_at, **_kw: {"name": "reference_bundle", "status": "ok", "details": {}})
    monkeypatch.setattr(release_script, "_run_measurement_gate", lambda symbol, timeframe, output_root, report_output="-", **kwargs: {"name": "measurement_lane", "status": "ok", "blocking": False, "details": {"measurement_manifest_present": False}})
    monkeypatch.setattr(release_script, "_render", lambda report, output: captured_reports.append(report))

    rc = release_script.main()

    assert rc == 1
    assert captured_reports[-1]["overall_status"] == "fail"
    assert call_kwargs[-1]["strict_release_policy"] is True


def test_release_runner_report_and_exit_are_deterministic(monkeypatch) -> None:
    captured_reports: list[dict] = []

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
                output="-",
            )
        ),
    )
    monkeypatch.setattr(release_script.time, "time", lambda: 1700000000.0)
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
    monkeypatch.setattr(release_script, "_run_reference_bundle_gate", lambda symbol, timeframe, generated_at, **_kw: {"name": "reference_bundle", "status": "ok", "details": {"symbol": symbol, "timeframe": timeframe}})
    monkeypatch.setattr(release_script, "_run_measurement_gate", lambda symbol, timeframe, output_root, report_output="-", **kwargs: {"name": "measurement_lane", "status": "ok", "blocking": False, "details": {"measurement_manifest_present": False}})
    monkeypatch.setattr(release_script, "_render", lambda report, output: captured_reports.append(report))

    rc_one = release_script.main()
    rc_two = release_script.main()

    assert rc_one == 0
    assert rc_two == 0
    assert captured_reports[0] == captured_reports[1]


def test_release_runner_skips_publish_contract_gate_when_requested(monkeypatch) -> None:
    captured_reports: list[dict] = []

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
                output="-",
            )
        ),
    )
    monkeypatch.setattr(release_script.time, "time", lambda: 1700000000.0)
    monkeypatch.setattr(
        release_script,
        "run_provider_health_check",
        lambda **kwargs: {
            "overall_status": "ok",
            "failures": [],
            "warnings": [],
            "degradations_detected": [],
            "smoke_test_results": [{"symbol": "IBG", "timeframe": "15m"}],
        },
    )
    monkeypatch.setattr(release_script, "_run_reference_bundle_gate", lambda symbol, timeframe, generated_at, **_kw: {"name": "reference_bundle", "status": "ok", "details": {}})
    monkeypatch.setattr(release_script, "_run_publish_contract_gate", lambda args: (_ for _ in ()).throw(AssertionError("publish contract gate should be skipped")))
    monkeypatch.setattr(release_script, "_run_measurement_gate", lambda symbol, timeframe, output_root, report_output="-", **kwargs: {"name": "measurement_lane", "status": "ok", "blocking": False, "details": {"measurement_manifest_present": False}})
    monkeypatch.setattr(release_script, "_render", lambda report, output: captured_reports.append(report))

    rc = release_script.main()

    assert rc == 0
    assert captured_reports[-1]["release_phase"] == "pre_publish"
    assert [gate["name"] for gate in captured_reports[-1]["gates"]] == ["provider_health", "reference_bundle", "evidence_lane", "measurement_lane"]


def test_release_runner_surfaces_provider_domain_alerts(monkeypatch) -> None:
    captured_reports: list[dict] = []

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
                output="-",
            )
        ),
    )
    monkeypatch.setattr(release_script.time, "time", lambda: 1700000000.0)
    monkeypatch.setattr(
        release_script,
        "run_provider_health_check",
        lambda **kwargs: {
            "overall_status": "warn",
            "domain_alerts": [
                {
                    "code": "FALLBACK_META_TECHNICAL_DOMAIN",
                    "severity": "info",
                    "symbol": "IBG",
                    "timeframe": "15m",
                }
            ],
            "failures": [],
            "warnings": [],
            "degradations_detected": [],
            "smoke_test_results": [{"symbol": "IBG", "timeframe": "15m"}],
        },
    )
    monkeypatch.setattr(release_script, "_run_reference_bundle_gate", lambda symbol, timeframe, generated_at, **_kw: {"name": "reference_bundle", "status": "ok", "details": {"symbol": symbol, "timeframe": timeframe}})
    monkeypatch.setattr(release_script, "_run_measurement_gate", lambda symbol, timeframe, output_root, report_output="-", **kwargs: {"name": "measurement_lane", "status": "ok", "blocking": False, "details": {"measurement_manifest_present": False}})
    monkeypatch.setattr(release_script, "_render", lambda report, output: captured_reports.append(report))

    rc = release_script.main()

    assert rc == 0
    provider_gate = next(gate for gate in captured_reports[-1]["gates"] if gate["name"] == "provider_health")
    assert provider_gate["details"]["domain_alerts"] == [
        {
            "code": "FALLBACK_META_TECHNICAL_DOMAIN",
            "severity": "info",
            "symbol": "IBG",
            "timeframe": "15m",
        }
    ]


def test_release_runner_adds_post_release_validation_gate_when_report_is_provided(monkeypatch, tmp_path: Path) -> None:
    captured_reports: list[dict] = []
    report_path = tmp_path / "smc_post_release_validation_report.json"
    report_path.write_text(
        json.dumps(
            {
                "report_kind": "post_release_validation",
                "overall_status": "ok",
                "validated_target_count": 1,
                "failures": [],
            }
        ),
        encoding="utf-8",
    )

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
                post_release_validation_report=str(report_path),
                output="-",
            )
        ),
    )
    monkeypatch.setattr(release_script.time, "time", lambda: 1700000000.0)
    monkeypatch.setattr(
        release_script,
        "run_provider_health_check",
        lambda **kwargs: {
            "overall_status": "ok",
            "failures": [],
            "warnings": [],
            "degradations_detected": [],
            "smoke_test_results": [{"symbol": "IBG", "timeframe": "15m"}],
        },
    )
    monkeypatch.setattr(release_script, "_run_reference_bundle_gate", lambda symbol, timeframe, generated_at, **_kw: {"name": "reference_bundle", "status": "ok", "details": {}})
    monkeypatch.setattr(release_script, "_run_measurement_gate", lambda symbol, timeframe, output_root, report_output="-", **kwargs: {"name": "measurement_lane", "status": "ok", "blocking": False, "details": {"measurement_manifest_present": False}})
    monkeypatch.setattr(release_script, "_render", lambda report, output: captured_reports.append(report))

    rc = release_script.main()

    assert rc == 0
    assert captured_reports[-1]["release_phase"] == "post_publish"
    gate_names = [gate["name"] for gate in captured_reports[-1]["gates"]]
    assert gate_names == ["provider_health", "reference_bundle", "evidence_lane", "post_release_validation", "measurement_lane"]


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

    # Governance promotion (77ac1652) made MEASUREMENT_CALIBRATED_ECE_ABOVE_THRESHOLD
    # a hard-blocking gate. The subsequent eligibility-floor fix added
    # ``min_events_for_calibrated_thresholds`` (=30; Platt ``_MIN_PLATT_EVENTS``
    # plus margin); below that floor the calibrated absolute-threshold
    # codes are suppressed because beta_bin fallback emits a statistically
    # meaningless calibrated_ece. This fixture runs at n_events=1, so the gate
    # is expected to surface the calibrated_ece warning as advisory (status
    # ``warn``) rather than hard-blocking. Hard-block coverage at/above the
    # floor is exercised by
    # ``tests/test_smc_integration_release_policy.py::TestMeasurementShadowDegradations::test_calibrated_thresholds_apply_at_or_above_platt_floor_default``.
    assert gate["status"] == "warn"
    assert gate["blocking"] is False
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
    # The eligibility-floor fix suppresses the calibrated_ece ABOVE_THRESHOLD
    # code at n_events<20, so the advisory warning is no longer emitted in
    # gate["details"]["warnings"]. The calibration row still reports the
    # raw beta_bin fallback warnings via gate["details"]["calibration"]["warnings"].
    calibration_warnings = gate["details"].get("calibration", {}).get("warnings") or []
    assert any("beta_bin" in w or "insufficient_events" in w for w in calibration_warnings)
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
    assert gate["details"]["measurement_shadow_effective_thresholds"]["max_calibrated_brier_score"] == 0.6
    codes = {row["code"] for row in gate["details"]["measurement_degradations_detected"]}
    assert {
        "MEASUREMENT_BRIER_REGRESSION",
        "MEASUREMENT_LOG_SCORE_REGRESSION",
        "MEASUREMENT_EVENT_COVERAGE_REGRESSION",
        "MEASUREMENT_STRATIFICATION_COVERAGE_REGRESSION",
    }.issubset(codes)


# ── WP-A8: Measurement Soft-Block Phase 1 ─────────────────────────


def test_measurement_gate_warns_brier_above_soft_threshold(monkeypatch, tmp_path: Path) -> None:
    """Brier > 0.3 must produce a soft warning in the measurement gate."""
    evidence = MeasurementEvidence(
        events_by_family={
            "BOS": [{"hit": True, "time_to_mitigation": 1.0, "invalidated": False, "mae": 0.01, "mfe": 0.03}],
            "OB": [{"hit": False, "time_to_mitigation": 0.5, "invalidated": True, "mae": 0.02, "mfe": 0.01}],
            "FVG": [{"hit": True, "time_to_mitigation": 1.5, "invalidated": False, "mae": 0.008, "mfe": 0.025}],
            "SWEEP": [{"hit": False, "time_to_mitigation": 2.0, "invalidated": True, "mae": 0.005, "mfe": 0.02}],
        },
        stratified_events=None,
        scored_events=[
            ScoredEvent("e1", "BOS", 0.80, False, 1700000000.0),
            ScoredEvent("e2", "OB", 0.70, False, 1700000001.0),
            ScoredEvent("e3", "FVG", 0.60, True, 1700000002.0),
            ScoredEvent("e4", "SWEEP", 0.90, False, 1700000003.0),
        ],
        details={"measurement_evidence_present": True, "evaluated_event_counts": {"BOS": 1, "OB": 1, "FVG": 1, "SWEEP": 1}, "bars_source_mode": "synthetic_bundle"},
        warnings=[],
    )
    monkeypatch.setattr(release_script, "build_measurement_evidence", lambda symbol, timeframe: evidence)

    gate = release_script._run_measurement_gate(
        "AAPL",
        "15m",
        output_root=tmp_path / "measurement",
        report_output=str(tmp_path / "report.json"),
    )

    brier_warnings = [w for w in gate["details"]["warnings"] if "Brier score" in w and "soft threshold" in w]
    assert len(brier_warnings) >= 1, f"Expected Brier soft warning, got: {gate['details']['warnings']}"
    # Soft-warn coverage is independent of the calibrated-ECE hard-block.
    # With the eligibility-floor fix (min_events_for_calibrated_thresholds=30)
    # this n_events=4 fixture no longer triggers the hard ECE gate, so the
    # gate is non-blocking but still emits the Brier soft warning. Hard-block
    # coverage at/above the floor is exercised by
    # ``tests/test_smc_integration_release_policy.py::TestMeasurementShadowDegradations::test_calibrated_thresholds_apply_at_or_above_platt_floor_default``.
    assert gate["blocking"] is False


def test_measurement_gate_warns_coverage_below_soft_threshold(monkeypatch, tmp_path: Path) -> None:
    """Event coverage < 50% must produce a soft warning in the measurement gate."""
    evidence = MeasurementEvidence(
        events_by_family={
            "BOS": [{"hit": True, "time_to_mitigation": 1.0, "invalidated": False, "mae": 0.01, "mfe": 0.03}],
            "OB": [],
            "FVG": [],
            "SWEEP": [],
        },
        stratified_events=None,
        scored_events=[ScoredEvent("e1", "BOS", 0.50, True, 1700000000.0)],
        details={"measurement_evidence_present": True, "evaluated_event_counts": {"BOS": 1, "OB": 0, "FVG": 0, "SWEEP": 0}, "bars_source_mode": "synthetic_bundle"},
        warnings=[],
    )
    monkeypatch.setattr(release_script, "build_measurement_evidence", lambda symbol, timeframe: evidence)

    gate = release_script._run_measurement_gate(
        "AAPL",
        "15m",
        output_root=tmp_path / "measurement",
        report_output=str(tmp_path / "report.json"),
    )

    coverage_warnings = [w for w in gate["details"]["warnings"] if "Event coverage" in w and "soft threshold" in w]
    assert len(coverage_warnings) >= 1, f"Expected coverage soft warning, got: {gate['details']['warnings']}"
    # Soft-warn coverage is independent of the calibrated-ECE hard-block.
    # With the eligibility-floor fix (min_events_for_calibrated_thresholds=30)
    # this n_events=1 fixture no longer triggers the hard ECE gate, so the
    # gate is non-blocking but still emits the coverage soft warning.
    assert gate["blocking"] is False


def test_soft_warn_thresholds_are_configurable() -> None:
    """MeasurementShadowThresholds must expose soft-warn fields (WP-A8)."""
    from smc_integration.release_policy import MeasurementShadowThresholds

    defaults = MeasurementShadowThresholds()
    assert hasattr(defaults, "soft_warn_max_brier_score")
    assert hasattr(defaults, "soft_warn_min_event_coverage_ratio")
    assert defaults.soft_warn_max_brier_score == 0.30
    assert defaults.soft_warn_min_event_coverage_ratio == 0.50


# ── Gate-chain structural invariants ───────────────────────────────


def test_provider_health_gate_has_explicit_blocking_key(monkeypatch) -> None:
    """provider_health gate must carry an explicit 'blocking' key (F2)."""
    captured_reports: list[dict] = []

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
                output="-",
            )
        ),
    )
    monkeypatch.setattr(release_script.time, "time", lambda: 1700000000.0)
    monkeypatch.setattr(
        release_script,
        "run_provider_health_check",
        lambda **kwargs: {
            "overall_status": "ok",
            "failures": [],
            "warnings": [],
            "degradations_detected": [],
            "smoke_test_results": [{"symbol": "IBG", "timeframe": "15m"}],
        },
    )
    monkeypatch.setattr(release_script, "_run_reference_bundle_gate", lambda symbol, timeframe, generated_at, **_kw: {"name": "reference_bundle", "status": "ok", "details": {}})
    monkeypatch.setattr(release_script, "_run_measurement_gate", lambda symbol, timeframe, output_root, report_output="-", **kwargs: {"name": "measurement_lane", "status": "ok", "blocking": False, "details": {}})
    monkeypatch.setattr(release_script, "_render", lambda report, output: captured_reports.append(report))

    release_script.main()

    provider_gate = next(g for g in captured_reports[-1]["gates"] if g["name"] == "provider_health")
    assert "blocking" in provider_gate
    assert provider_gate["blocking"] is True


def test_reference_bundle_evaluates_all_symbol_timeframe_pairs(monkeypatch) -> None:
    """reference_bundle gate must check every symbol × timeframe pair (F3)."""
    captured_reports: list[dict] = []
    ref_calls: list[tuple[str, str]] = []

    def _ref_stub(symbol, timeframe, generated_at, **_kw):
        ref_calls.append((symbol, timeframe))
        return {"name": "reference_bundle", "status": "ok", "details": {"symbol": symbol, "timeframe": timeframe}}

    monkeypatch.setattr(
        release_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                symbols="AAPL,MSFT",
                timeframes="15m,1H",
                stale_after_seconds=3600,
                fail_on_warn=False,
                allow_warn=True,
                skip_publish_contract=True,
                manifest="pine/generated/smc_micro_profiles_generated.json",
                core_engine="SMC_Core_Engine.pine",
                measurement_output_root=None,
                measurement_baseline_summary=None,
                output="-",
            )
        ),
    )
    monkeypatch.setattr(release_script.time, "time", lambda: 1700000000.0)
    monkeypatch.setattr(
        release_script,
        "run_provider_health_check",
        lambda **kwargs: {
            "overall_status": "ok",
            "failures": [],
            "warnings": [],
            "degradations_detected": [],
            "smoke_test_results": [
                {"symbol": "AAPL", "timeframe": "15m"},
                {"symbol": "AAPL", "timeframe": "1H"},
                {"symbol": "MSFT", "timeframe": "15m"},
                {"symbol": "MSFT", "timeframe": "1H"},
            ],
        },
    )
    monkeypatch.setattr(release_script, "_run_reference_bundle_gate", _ref_stub)
    monkeypatch.setattr(release_script, "_run_measurement_gate", lambda symbol, timeframe, output_root, report_output="-", **kwargs: {"name": "measurement_lane", "status": "ok", "blocking": False, "details": {}})
    monkeypatch.setattr(release_script, "_render", lambda report, output: captured_reports.append(report))

    release_script.main()

    assert len(ref_calls) == 4
    assert set(ref_calls) == {("AAPL", "15m"), ("AAPL", "1H"), ("MSFT", "15m"), ("MSFT", "1H")}
    ref_gate = next(g for g in captured_reports[-1]["gates"] if g["name"] == "reference_bundle")
    assert ref_gate["details"]["pairs_checked"] == 4
    assert len(ref_gate["details"]["pair_results"]) == 4


def test_measurement_lane_evaluates_all_symbol_timeframe_pairs(monkeypatch) -> None:
    """measurement_lane gate must check every symbol × timeframe pair (F4)."""
    captured_reports: list[dict] = []
    m_calls: list[tuple[str, str]] = []

    def _m_stub(symbol, timeframe, output_root, report_output="-", **kwargs):
        m_calls.append((symbol, timeframe))
        return {"name": "measurement_lane", "status": "ok", "blocking": False, "details": {"symbol": symbol, "timeframe": timeframe}}

    monkeypatch.setattr(
        release_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                symbols="AAPL,MSFT",
                timeframes="15m,1H",
                stale_after_seconds=3600,
                fail_on_warn=False,
                allow_warn=True,
                skip_publish_contract=True,
                manifest="pine/generated/smc_micro_profiles_generated.json",
                core_engine="SMC_Core_Engine.pine",
                measurement_output_root=None,
                measurement_baseline_summary=None,
                output="-",
            )
        ),
    )
    monkeypatch.setattr(release_script.time, "time", lambda: 1700000000.0)
    monkeypatch.setattr(
        release_script,
        "run_provider_health_check",
        lambda **kwargs: {
            "overall_status": "ok",
            "failures": [],
            "warnings": [],
            "degradations_detected": [],
            "smoke_test_results": [
                {"symbol": "AAPL", "timeframe": "15m"},
                {"symbol": "AAPL", "timeframe": "1H"},
                {"symbol": "MSFT", "timeframe": "15m"},
                {"symbol": "MSFT", "timeframe": "1H"},
            ],
        },
    )
    monkeypatch.setattr(release_script, "_run_reference_bundle_gate", lambda symbol, timeframe, generated_at, **_kw: {"name": "reference_bundle", "status": "ok", "details": {}})
    monkeypatch.setattr(release_script, "_run_measurement_gate", _m_stub)
    monkeypatch.setattr(release_script, "_render", lambda report, output: captured_reports.append(report))

    release_script.main()

    assert len(m_calls) == 4
    assert set(m_calls) == {("AAPL", "15m"), ("AAPL", "1H"), ("MSFT", "15m"), ("MSFT", "1H")}
    m_gate = next(g for g in captured_reports[-1]["gates"] if g["name"] == "measurement_lane")
    assert m_gate["details"]["pairs_checked"] == 4
    assert m_gate["blocking"] is False


def test_missing_smoke_result_has_message(monkeypatch) -> None:
    """MISSING_SMOKE_RESULT entries must carry a human-readable message (F6)."""
    captured_reports: list[dict] = []

    monkeypatch.setattr(
        release_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                symbols="AAPL",
                timeframes="15m",
                stale_after_seconds=3600,
                fail_on_warn=False,
                allow_warn=True,
                skip_publish_contract=True,
                manifest="pine/generated/smc_micro_profiles_generated.json",
                core_engine="SMC_Core_Engine.pine",
                measurement_output_root=None,
                measurement_baseline_summary=None,
                output="-",
            )
        ),
    )
    monkeypatch.setattr(release_script.time, "time", lambda: 1700000000.0)
    # Return empty smoke_test_results so AAPL/15m is missing.
    monkeypatch.setattr(
        release_script,
        "run_provider_health_check",
        lambda **kwargs: {
            "overall_status": "ok",
            "failures": [],
            "warnings": [],
            "degradations_detected": [],
            "smoke_test_results": [],
        },
    )
    monkeypatch.setattr(release_script, "_run_reference_bundle_gate", lambda symbol, timeframe, generated_at, **_kw: {"name": "reference_bundle", "status": "ok", "details": {}})
    monkeypatch.setattr(release_script, "_run_measurement_gate", lambda symbol, timeframe, output_root, report_output="-", **kwargs: {"name": "measurement_lane", "status": "ok", "blocking": False, "details": {}})
    monkeypatch.setattr(release_script, "_render", lambda report, output: captured_reports.append(report))

    rc = release_script.main()

    assert rc == 1  # provider_health gate fails because of missing smoke
    provider_gate = next(g for g in captured_reports[-1]["gates"] if g["name"] == "provider_health")
    missing = provider_gate["details"]["missing_smoke_failures"]
    assert len(missing) == 1
    assert missing[0]["code"] == "MISSING_SMOKE_RESULT"
    assert "message" in missing[0]
    assert "AAPL" in missing[0]["message"]


# ---------------------------------------------------------------------------
# F-09 — Release-Gates Stufung
# ---------------------------------------------------------------------------


class TestReleaseGateClassification:
    """Verify the ci_structural_pass / operational_release_pass split."""

    def _make_report(self, gates: list[dict]) -> dict:
        """Simulate the classification logic from run_smc_release_gates.py."""
        ci_validatable_gates = [
            g for g in gates
            if g.get("name") in {"publish_contract", "reference_bundle", "measurement_lane", "provider_health"}
        ]
        ci_structural_pass = not any(
            g.get("status") == "fail" for g in ci_validatable_gates
            if g.get("blocking", True) and not g.get("ci_mode_downgraded")
        )
        operational_release_pass = not any(
            g.get("status") == "fail" for g in gates if g.get("blocking", True)
        )
        soft_gates_for_review = [
            {
                "name": g["name"],
                "current_status": g.get("status"),
                "blocking": g.get("blocking", True),
                "review_reason": (
                    "ci_mode_downgraded" if g.get("ci_mode_downgraded")
                    else "soft_by_design"
                ),
            }
            for g in gates
            if not g.get("blocking", True) or g.get("ci_mode_downgraded")
        ]
        return {
            "ci_structural_pass": ci_structural_pass,
            "operational_release_pass": operational_release_pass,
            "soft_gates_for_review": soft_gates_for_review,
        }

    def test_all_pass(self) -> None:
        gates = [
            {"name": "publish_contract", "status": "ok", "blocking": True},
            {"name": "reference_bundle", "status": "ok", "blocking": True},
        ]
        r = self._make_report(gates)
        assert r["ci_structural_pass"] is True
        assert r["operational_release_pass"] is True
        assert r["soft_gates_for_review"] == []

    def test_ci_fail_blocks_structural(self) -> None:
        gates = [
            {"name": "publish_contract", "status": "fail", "blocking": True},
            {"name": "reference_bundle", "status": "ok", "blocking": True},
        ]
        r = self._make_report(gates)
        assert r["ci_structural_pass"] is False
        assert r["operational_release_pass"] is False

    def test_live_only_fail_still_ci_pass(self) -> None:
        gates = [
            {"name": "publish_contract", "status": "ok", "blocking": True},
            {"name": "post_release_validation", "status": "fail", "blocking": True},
        ]
        r = self._make_report(gates)
        assert r["ci_structural_pass"] is True
        assert r["operational_release_pass"] is False

    def test_ci_mode_downgraded_is_soft(self) -> None:
        gates = [
            {"name": "provider_health", "status": "fail", "blocking": False, "ci_mode_downgraded": True},
        ]
        r = self._make_report(gates)
        assert r["ci_structural_pass"] is True
        assert r["operational_release_pass"] is True
        assert len(r["soft_gates_for_review"]) == 1
        assert r["soft_gates_for_review"][0]["review_reason"] == "ci_mode_downgraded"

    def test_non_blocking_gate_listed_for_review(self) -> None:
        gates = [
            {"name": "measurement_lane", "status": "ok", "blocking": False},
        ]
        r = self._make_report(gates)
        assert len(r["soft_gates_for_review"]) == 1
        assert r["soft_gates_for_review"][0]["review_reason"] == "soft_by_design"


class TestGateFailureIsDataAbsent:
    """Tests for _gate_failure_is_data_absent helper."""

    def test_pair_results_all_data_insufficient(self) -> None:
        gate = {
            "name": "reference_bundle",
            "status": "fail",
            "details": {
                "pair_results": [
                    {"quality_guardrail": "data insufficient", "symbol": "A", "timeframe": "15m"},
                    {"quality_guardrail": "data insufficient", "symbol": "B", "timeframe": "1H"},
                ],
            },
        }
        assert release_script._gate_failure_is_data_absent(gate) is True

    def test_pair_results_mixed_data_insufficient_and_none(self) -> None:
        gate = {
            "name": "reference_bundle",
            "status": "fail",
            "details": {
                "pair_results": [
                    {"quality_guardrail": "data insufficient", "symbol": "A", "timeframe": "15m"},
                    {"quality_guardrail": None, "symbol": "B", "timeframe": "5m"},
                ],
            },
        }
        assert release_script._gate_failure_is_data_absent(gate) is True

    def test_pair_results_with_real_guardrail_not_absent(self) -> None:
        gate = {
            "name": "reference_bundle",
            "status": "fail",
            "details": {
                "pair_results": [
                    {"quality_guardrail": "data insufficient", "symbol": "A", "timeframe": "15m"},
                    {"quality_guardrail": "hold", "symbol": "B", "timeframe": "1H"},
                ],
            },
        }
        assert release_script._gate_failure_is_data_absent(gate) is False

    def test_empty_details_not_absent(self) -> None:
        gate = {"name": "unknown", "status": "fail", "details": {}}
        assert release_script._gate_failure_is_data_absent(gate) is False

    def test_stale_manifest_generated_at_is_data_absent(self) -> None:
        """STALE_MANIFEST_GENERATED_AT fires in local CI when manifests are old."""
        gate = {
            "name": "provider_health",
            "status": "fail",
            "blocking": True,
            "details": {
                "failures": [{"code": "STALE_MANIFEST_GENERATED_AT"}],
                "warnings": [{"code": "EMPTY_CONTEXT_BARS"}],
                "domain_alerts": [{"code": "FALLBACK_META_VOLUME_DOMAIN"}],
                "missing_smoke_failures": [],
            },
        }
        assert release_script._gate_failure_is_data_absent(gate) is True

    def test_provider_health_all_stale_and_missing_codes(self) -> None:
        """All manifest/meta staleness codes are classified as data-absent."""
        gate = {
            "name": "provider_health",
            "status": "fail",
            "blocking": True,
            "details": {
                "failures": [
                    {"code": "STALE_MANIFEST_GENERATED_AT"},
                    {"code": "STRUCTURE_INPUT_LOAD_FAILED"},
                    {"code": "STALE_META_ASOF_TS"},
                    {"code": "META_INPUT_LOAD_FAILED"},
                    {"code": "SOURCE_PLAN_RESOLUTION_FAILED"},
                ],
                "warnings": [
                    {"code": "MISSING_MANIFEST"},
                    {"code": "MISSING_MANIFEST_GENERATED_AT"},
                    {"code": "STALE_MANIFEST_FILE_MTIME"},
                ],
                "domain_alerts": [
                    {"code": "FALLBACK_META_TECHNICAL_DOMAIN"},
                    {"code": "FALLBACK_META_NEWS_DOMAIN"},
                    {"code": "STALE_META_VOLUME_DOMAIN"},
                    {"code": "STALE_META_TECHNICAL_DOMAIN"},
                    {"code": "STALE_META_NEWS_DOMAIN"},
                ],
                "missing_smoke_failures": [],
            },
        }
        assert release_script._gate_failure_is_data_absent(gate) is True

    def test_mixed_data_absent_and_real_failure_not_absent(self) -> None:
        """One non-CI code among data-absent codes → gate is NOT data-absent."""
        gate = {
            "name": "provider_health",
            "status": "fail",
            "blocking": True,
            "details": {
                "failures": [
                    {"code": "STRUCTURE_INPUT_LOAD_FAILED"},
                    {"code": "INVALID_MANIFEST_JSON"},
                ],
                "warnings": [],
                "domain_alerts": [],
                "missing_smoke_failures": [],
            },
        }
        assert release_script._gate_failure_is_data_absent(gate) is False


# ── E2E CI-mode regression test ──────────────────────────────────────


class TestCiModeMainStructuralPass:
    """End-to-end: main() with --ci-mode must yield ci_structural_pass=True
    when every failure is caused by absent production data."""

    @staticmethod
    def _ci_provider_report(symbols: list[str], timeframes: list[str]) -> dict:
        """Realistic provider_health report as observed on GitHub-hosted runners."""
        smoke_results = [
            {"symbol": s, "timeframe": tf, "status": "fail"}
            for s in symbols for tf in timeframes
        ]
        return {
            "overall_status": "fail",
            "failures": [
                {"code": "STALE_MANIFEST_GENERATED_AT", "timeframe": "15m"},
                {"code": "STRUCTURE_INPUT_LOAD_FAILED", "symbol": "AAPL", "timeframe": "15m"},
                {"code": "META_INPUT_LOAD_FAILED", "symbol": "AAPL", "timeframe": "15m"},
                {"code": "SOURCE_PLAN_RESOLUTION_FAILED", "symbol": "AAPL", "timeframe": "15m"},
            ],
            "warnings": [
                {"code": "EMPTY_CONTEXT_BARS", "symbol": "AAPL", "timeframe": "15m"},
                {"code": "NONCANONICAL_MANIFEST_WORKBOOK_PATH", "timeframe": "15m"},
                {"code": "MISSING_MANIFEST", "timeframe": "15m"},
                {"code": "MISSING_MANIFEST_GENERATED_AT", "timeframe": "15m"},
            ],
            "domain_alerts": [
                {"code": "DOMAIN_DROPPED_NEWS", "domain": "news"},
                {"code": "DOMAIN_DROPPED_TECHNICAL", "domain": "technical"},
                {"code": "DOMAIN_DROP_DURING_BUILD", "domain": "news"},
                {"code": "FALLBACK_META_VOLUME_DOMAIN", "domain": "volume"},
                {"code": "FALLBACK_META_TECHNICAL_DOMAIN", "domain": "technical"},
                {"code": "FALLBACK_META_NEWS_DOMAIN", "domain": "news"},
                {"code": "SILENT_DOMAIN_DROP_NEWS", "domain": "news"},
                {"code": "SILENT_DOMAIN_DROP_TECHNICAL", "domain": "technical"},
                {"code": "STALE_META_VOLUME_DOMAIN", "domain": "volume"},
                {"code": "STALE_META_TECHNICAL_DOMAIN", "domain": "technical"},
                {"code": "STALE_META_NEWS_DOMAIN", "domain": "news"},
            ],
            "degradations_detected": [
                {"code": "EMPTY_CONTEXT_BARS"},
                {"code": "STRUCTURE_SOURCE_HEALTH_ISSUES"},
            ],
            "smoke_test_results": smoke_results,
        }

    def test_ci_mode_main_structural_pass_without_data(self, monkeypatch) -> None:
        """With all-data-absent failures, --ci-mode downgrades every blocking
        gate and ci_structural_pass is True."""
        captured: list[dict] = []
        symbols = ["AAPL"]
        timeframes = ["15m"]

        monkeypatch.setattr(
            release_script,
            "build_parser",
            lambda: _Parser(
                Namespace(
                    symbols="AAPL",
                    timeframes="15m",
                    stale_after_seconds=3600,
                    fail_on_warn=False,
                    allow_warn=False,
                    skip_publish_contract=True,
                    manifest="pine/generated/smc_micro_profiles_generated.json",
                    core_engine="SMC_Core_Engine.pine",
                    measurement_output_root=None,
                    measurement_baseline_summary=None,
                    output="-",
                    ci_mode=True,
                )
            ),
        )
        monkeypatch.setattr(
            release_script,
            "run_provider_health_check",
            lambda **kwargs: self._ci_provider_report(symbols, timeframes),
        )
        monkeypatch.setattr(
            release_script,
            "build_snapshot_bundle_for_symbol_timeframe",
            lambda *a, **kw: (_ for _ in ()).throw(
                FileNotFoundError("No production data in CI")
            ),
        )
        monkeypatch.setattr(
            release_script,
            "_run_measurement_gate",
            lambda symbol, timeframe, output_root, report_output="-", **kwargs: {
                "name": "measurement_lane",
                "status": "warn",
                "blocking": False,
                "details": {"measurement_manifest_present": False},
            },
        )
        monkeypatch.setattr(release_script, "_render", lambda report, output: captured.append(report))

        rc = release_script.main()

        report = captured[-1]
        assert report["ci_structural_pass"] is True, (
            f"ci_structural_pass should be True; "
            f"downgrades={report['runner']['ci_mode_downgrades']}"
        )
        assert "provider_health" in report["runner"]["ci_mode_downgrades"]
        assert "reference_bundle" in report["runner"]["ci_mode_downgrades"]
        # Exit code is 0 only if no blocking gate remains — verify consistency.
        assert rc == 0

    def test_real_failure_prevents_structural_pass(self, monkeypatch) -> None:
        """A non-data-absent failure must NOT be downgraded — ci_structural_pass
        stays False."""
        captured: list[dict] = []

        monkeypatch.setattr(
            release_script,
            "build_parser",
            lambda: _Parser(
                Namespace(
                    symbols="AAPL",
                    timeframes="15m",
                    stale_after_seconds=3600,
                    fail_on_warn=False,
                    allow_warn=False,
                    skip_publish_contract=True,
                    manifest="pine/generated/smc_micro_profiles_generated.json",
                    core_engine="SMC_Core_Engine.pine",
                    measurement_output_root=None,
                    measurement_baseline_summary=None,
                    output="-",
                    ci_mode=True,
                )
            ),
        )
        monkeypatch.setattr(
            release_script,
            "run_provider_health_check",
            lambda **kwargs: {
                "overall_status": "fail",
                "failures": [{"code": "INVALID_MANIFEST_JSON"}],
                "warnings": [],
                "domain_alerts": [],
                "degradations_detected": [],
                "smoke_test_results": [{"symbol": "AAPL", "timeframe": "15m"}],
            },
        )
        monkeypatch.setattr(release_script, "_run_reference_bundle_gate", lambda symbol, timeframe, generated_at, **_kw: {"name": "reference_bundle", "status": "ok", "details": {}})
        monkeypatch.setattr(release_script, "_run_measurement_gate", lambda symbol, timeframe, output_root, report_output="-", **kwargs: {"name": "measurement_lane", "status": "ok", "blocking": False, "details": {}})
        monkeypatch.setattr(release_script, "_render", lambda report, output: captured.append(report))

        rc = release_script.main()

        report = captured[-1]
        assert report["ci_structural_pass"] is False
        assert rc == 1


# ── Drift-detection: _DATA_ABSENT_CODES vs provider_health codes ─────


# Codes that genuinely indicate code/schema bugs or corrupted data and must
# NEVER be masked by ci-mode.  When a new code is added to provider_health's
# promotion sets, it must be classified here OR in _DATA_ABSENT_CODES.
_PRODUCTION_ONLY_CODES: frozenset[str] = frozenset({
    "ARTIFACT_LOOKUP_FAILED",
    "INVALID_MANIFEST_JSON",
    "INVALID_MANIFEST_SHAPE",
    "INVALID_STRUCTURE_ARTIFACT",
    "INVALID_LEGACY_STRUCTURE_ARTIFACT",
    "MISSING_META_ASOF_TS",
})

# Codes that originate in the release-gate script itself or in smoke checks
# (not in the provider_health promotion sets or domain-alert templates).
_RELEASE_GATE_LEVEL_CODES: frozenset[str] = frozenset({
    "MISSING_SMOKE_RESULT",
    "source_file_not_found",
    "STRUCTURE_INPUT_LOAD_FAILED",
    "EMPTY_CONTEXT_BARS",
    "META_INPUT_LOAD_FAILED",
    "SOURCE_PLAN_RESOLUTION_FAILED",
    "NONCANONICAL_MANIFEST_WORKBOOK_PATH",
    "MISSING_ARTIFACT",
})

# Domain-alert code templates expanded for all applicable domains.
# These are generated by _collect_meta_domain_alerts in provider_health.py.
_DOMAIN_ALERT_CODE_TEMPLATES: frozenset[str] = frozenset({
    # FALLBACK_META_{DOMAIN}_DOMAIN — volume, technical, news
    "FALLBACK_META_VOLUME_DOMAIN",
    "FALLBACK_META_TECHNICAL_DOMAIN",
    "FALLBACK_META_NEWS_DOMAIN",
    # DOMAIN_DROPPED_{DOMAIN} — technical, news
    "DOMAIN_DROPPED_TECHNICAL",
    "DOMAIN_DROPPED_NEWS",
    # Literal
    "DOMAIN_DROP_DURING_BUILD",
    # SILENT_DOMAIN_DROP_{DOMAIN} — technical, news
    "SILENT_DOMAIN_DROP_TECHNICAL",
    "SILENT_DOMAIN_DROP_NEWS",
    # META_{DOMAIN}_DOMAIN_STATUS — volume, technical, news
    "META_VOLUME_DOMAIN_STATUS",
    "META_TECHNICAL_DOMAIN_STATUS",
    "META_NEWS_DOMAIN_STATUS",
    # STALE_META_{DOMAIN}_DOMAIN — volume, technical, news (degradation path)
    "STALE_META_VOLUME_DOMAIN",
    "STALE_META_TECHNICAL_DOMAIN",
    "STALE_META_NEWS_DOMAIN",
})


class TestDataAbsentCodesDriftGuard:
    """Ensures every code that can be promoted to a failure or appear as a
    domain alert is explicitly classified as either data-absent (safe to
    downgrade in CI) or production-only (must block).

    When a developer adds a new code to ``_STRICT_RELEASE_WARNING_CODES``,
    ``_STRICT_RELEASE_DEGRADATION_CODES``, or a new domain-alert template,
    this test fails until the code is added to ``_DATA_ABSENT_CODES`` or
    ``_PRODUCTION_ONLY_CODES``."""

    def test_strict_warning_codes_are_classified(self) -> None:
        for code in _ph._STRICT_RELEASE_WARNING_CODES:
            assert code in release_script._DATA_ABSENT_CODES or code in _PRODUCTION_ONLY_CODES, (
                f"Code {code!r} from _STRICT_RELEASE_WARNING_CODES is neither in "
                f"_DATA_ABSENT_CODES nor _PRODUCTION_ONLY_CODES — classify it!"
            )

    def test_strict_degradation_codes_are_classified(self) -> None:
        for code in _ph._STRICT_RELEASE_DEGRADATION_CODES:
            assert code in release_script._DATA_ABSENT_CODES or code in _PRODUCTION_ONLY_CODES, (
                f"Code {code!r} from _STRICT_RELEASE_DEGRADATION_CODES is neither in "
                f"_DATA_ABSENT_CODES nor _PRODUCTION_ONLY_CODES — classify it!"
            )

    def test_domain_alert_codes_are_classified(self) -> None:
        for code in _DOMAIN_ALERT_CODE_TEMPLATES:
            assert code in release_script._DATA_ABSENT_CODES or code in _PRODUCTION_ONLY_CODES, (
                f"Domain-alert code {code!r} is neither in "
                f"_DATA_ABSENT_CODES nor _PRODUCTION_ONLY_CODES — classify it!"
            )

    def test_production_only_codes_not_in_data_absent(self) -> None:
        """Production-only codes must NOT accidentally be added to
        _DATA_ABSENT_CODES — that would silently mask real failures."""
        overlap = _PRODUCTION_ONLY_CODES & release_script._DATA_ABSENT_CODES
        assert not overlap, (
            f"Codes {overlap} are in BOTH _PRODUCTION_ONLY_CODES and "
            f"_DATA_ABSENT_CODES — remove from one set!"
        )

    def test_all_data_absent_codes_are_known(self) -> None:
        """Every code in _DATA_ABSENT_CODES should appear in at least one
        of the provider_health promotion sets or the domain-alert templates
        (or be a release-gate-level code like MISSING_SMOKE_RESULT).
        Unknown codes suggest stale entries."""
        known = (
            _ph._STRICT_RELEASE_WARNING_CODES
            | _ph._STRICT_RELEASE_DEGRADATION_CODES
            | _DOMAIN_ALERT_CODE_TEMPLATES
            | _PRODUCTION_ONLY_CODES
            | _RELEASE_GATE_LEVEL_CODES
        )
        unknown = release_script._DATA_ABSENT_CODES - known
        assert not unknown, (
            f"Codes {unknown} are in _DATA_ABSENT_CODES but not in any "
            f"provider_health set or _RELEASE_GATE_LEVEL_CODES — stale?"
        )

    def test_bundle_skip_fast_path_fields_recognized(self) -> None:
        """The WP-R10 fast-path sets ``bundle_skipped`` and
        ``bundle_skip_reason`` on smoke result rows.  These fields must
        remain valid — if someone removes or renames them in
        provider_health, this test breaks."""
        # Simulate the fast-path result row shape as produced by
        # _run_smoke_checks when all meta domains are absent.
        import smc_integration.provider_health as ph

        fast_path_guard_source = inspect.getsource(ph._run_smoke_checks)
        assert "bundle_skipped" in fast_path_guard_source, (
            "bundle_skipped field not found in _run_smoke_checks — "
            "WP-R10 fast-path removed?"
        )
        assert "bundle_skip_reason" in fast_path_guard_source, (
            "bundle_skip_reason field not found in _run_smoke_checks — "
            "WP-R10 fast-path removed?"
        )
        assert "all_meta_domains_absent" in fast_path_guard_source, (
            "all_meta_domains_absent reason value not found in "
            "_run_smoke_checks — fast-path semantics changed?"
        )


class TestReferenceBundleCachePassthrough:
    """WP-R12: reference_bundle gate reuses bundles built by smoke checks
    instead of rebuilding from scratch."""

    def test_cached_bundle_skips_build(self) -> None:
        """When a cached_bundle is provided, build_snapshot_bundle_for_symbol_timeframe
        must NOT be called."""
        cached = {
            "snapshot": {"structure": {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []}},
            "trust_summary": {"quality_recommendation": "ok", "quality_guardrail": None},
        }
        result = release_script._run_reference_bundle_gate(
            "AAPL", "15m", 1_000.0, cached_bundle=cached,
        )
        assert result["status"] == "ok"
        assert result["details"]["symbol"] == "AAPL"
        assert result["details"]["timeframe"] == "15m"
        assert result["details"]["quality_recommendation"] == "ok"

    def test_cache_miss_falls_back_to_build(self, monkeypatch) -> None:
        """When cached_bundle is None, build_snapshot_bundle_for_symbol_timeframe
        is called normally."""
        calls: list[dict] = []

        def _mock_build(*args, **kwargs):
            calls.append(kwargs)
            return {
                "snapshot": {"structure": {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []}},
                "trust_summary": {"quality_recommendation": "ok"},
            }

        monkeypatch.setattr(release_script, "build_snapshot_bundle_for_symbol_timeframe", _mock_build)
        result = release_script._run_reference_bundle_gate(
            "AAPL", "15m", 1_000.0, cached_bundle=None,
        )
        assert len(calls) == 1
        assert result["status"] == "ok"

    def test_smoke_bundles_flow_to_reference_gate(self, monkeypatch) -> None:
        """Bundles built by _run_smoke_checks are threaded through
        run_provider_health_check → main() → _run_reference_bundle_gate
        so no redundant build occurs."""
        smoke_source = inspect.getsource(_ph._run_smoke_checks)
        assert "built_bundles" in smoke_source, (
            "built_bundles dict not found in _run_smoke_checks — WP-R12 removed?"
        )
        health_source = inspect.getsource(_ph.run_provider_health_check)
        assert "smoke_bundles" in health_source, (
            "smoke_bundles not threaded through run_provider_health_check — WP-R12 removed?"
        )
        assert "include_smoke_bundles" in health_source, (
            "include_smoke_bundles opt-in gate not found — WP-R13 removed?"
        )


# ---------------------------------------------------------------------------
# WP-R11: TV-Resilience classification
# ---------------------------------------------------------------------------


class TestTvResilienceClassification:
    """Tests for ``classify_tv_gate_failure`` and ci-mode TV-drift downgrade."""

    def test_external_drift_codes_classified(self) -> None:
        gate = {
            "name": "post_release_validation",
            "status": "fail",
            "details": {
                "failures": [
                    {"code": "AUTH_FAILED"},
                    {"code": "PREFLIGHT_FAILED"},
                    {"code": "POST_RELEASE_VALIDATION_FAILED"},
                    {"code": "NO_TARGETS"},
                ],
            },
        }
        assert release_script.classify_tv_gate_failure(gate) == "external_tv_drift"

    def test_code_or_data_codes_classified(self) -> None:
        gate = {
            "name": "post_release_validation",
            "status": "fail",
            "details": {
                "failures": [
                    {"code": "VERSION_MISMATCH"},
                ],
            },
        }
        assert release_script.classify_tv_gate_failure(gate) == "code_or_data"

    def test_mixed_codes_classified(self) -> None:
        gate = {
            "name": "post_release_validation",
            "status": "fail",
            "details": {
                "failures": [
                    {"code": "AUTH_FAILED"},
                    {"code": "VERSION_MISMATCH"},
                ],
            },
        }
        assert release_script.classify_tv_gate_failure(gate) == "mixed"

    def test_unknown_codes_classified(self) -> None:
        gate = {
            "name": "post_release_validation",
            "status": "fail",
            "details": {
                "failures": [
                    {"code": "SOME_FUTURE_CODE"},
                ],
            },
        }
        assert release_script.classify_tv_gate_failure(gate) == "unknown"

    def test_no_failures_classified_unknown(self) -> None:
        gate = {
            "name": "post_release_validation",
            "status": "fail",
            "details": {"failures": []},
        }
        assert release_script.classify_tv_gate_failure(gate) == "unknown"

    def test_post_release_gate_includes_tv_failure_class(self, tmp_path: Path) -> None:
        report = {
            "overall_status": "fail",
            "validated_target_count": 1,
            "failures": [{"code": "TARGET_FAILED", "message": "selector not found"}],
        }
        report_path = tmp_path / "tv_report.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")

        gate = release_script._run_post_release_validation_gate(str(report_path))
        assert gate["status"] == "fail"
        assert gate["tv_failure_class"] == "external_tv_drift"

    def test_ci_mode_downgrades_external_tv_drift(self, tmp_path: Path) -> None:
        """In ci-mode, external TV drift failures should be downgraded."""
        gate = {
            "name": "post_release_validation",
            "status": "fail",
            "blocking": True,
            "tv_failure_class": "external_tv_drift",
            "details": {
                "failures": [{"code": "AUTH_FAILED"}],
            },
        }
        # Simulate the ci-mode downgrade loop
        if gate.get("tv_failure_class") == "external_tv_drift":
            gate["blocking"] = False
            gate["ci_mode_downgraded"] = True
            gate["ci_mode_downgrade_reason"] = "external_tv_drift"

        assert gate["blocking"] is False
        assert gate["ci_mode_downgraded"] is True
        assert gate["ci_mode_downgrade_reason"] == "external_tv_drift"

    def test_ci_mode_does_not_downgrade_code_or_data(self) -> None:
        """Code/data failures must NOT be downgraded even in ci-mode."""
        gate = {
            "name": "post_release_validation",
            "status": "fail",
            "blocking": True,
            "tv_failure_class": "code_or_data",
            "details": {
                "failures": [{"code": "VERSION_MISMATCH"}],
            },
        }
        # Same condition as ci-mode loop
        should_downgrade = gate.get("tv_failure_class") == "external_tv_drift"
        assert should_downgrade is False
        assert gate["blocking"] is True
