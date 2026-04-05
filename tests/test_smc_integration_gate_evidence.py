from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from scripts import collect_smc_gate_evidence as evidence_script


class _Parser:
    def __init__(self, args: Namespace):
        self._args = args

    def parse_args(self) -> Namespace:
        return self._args


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


_BROAD_SYMBOLS = ["AAPL", "MSFT", "AMZN", "JPM", "JNJ", "XOM", "CAT"]
_BROAD_TIMEFRAMES = ["5m", "15m", "1H", "4H"]


def test_gate_evidence_marks_green_ready_for_minimum_success_series(monkeypatch, tmp_path: Path) -> None:
    now_ts = 1_700_000_000.0
    monkeypatch.setattr(evidence_script.time, "time", lambda: now_ts)

    for idx in range(3):
        _write_json(
            tmp_path / f"deeper_{idx}.json",
            {
                "report_kind": "ci_health",
                "checked_at": now_ts - 60.0 * (idx + 1),
                "overall_status": "ok",
                "reference_symbols": _BROAD_SYMBOLS,
                "reference_timeframes": _BROAD_TIMEFRAMES,
                "runtime_metadata": {"git_commit": f"sha-deeper-{idx}"},
            },
        )

    for idx in range(2):
        _write_json(
            tmp_path / f"release_{idx}.json",
            {
                "report_kind": "release_gates",
                "checked_at": now_ts - 500.0 - 60.0 * idx,
                "overall_status": "ok",
                "reference_symbols": _BROAD_SYMBOLS,
                "reference_timeframes": _BROAD_TIMEFRAMES,
                "runtime_metadata": {"git_commit": f"sha-release-{idx}"},
                "gates": [{"name": "provider_health", "status": "ok", "details": {}}],
            },
        )

    captured: list[dict] = []
    monkeypatch.setattr(
        evidence_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                input_glob=str(tmp_path / "*.json"),
                lookback_days=14,
                min_deeper_ok_runs=3,
                min_release_ok_runs=2,
                fail_on_not_ready=False,
                output="-",
            )
        ),
    )
    monkeypatch.setattr(evidence_script, "_render", lambda report, output: captured.append(report))

    rc = evidence_script.main()

    assert rc == 0
    assert captured[-1]["green_ready"] is True
    assert captured[-1]["deeper_ok_runs_in_window"] == 3
    assert captured[-1]["release_ok_runs_in_window"] == 2
    assert captured[-1]["unresolved_core_failures_in_window"] == 0


def test_gate_evidence_detects_unresolved_stale_failure(monkeypatch, tmp_path: Path) -> None:
    now_ts = 1_700_000_000.0
    monkeypatch.setattr(evidence_script.time, "time", lambda: now_ts)

    _write_json(
        tmp_path / "deeper_ok.json",
        {
            "report_kind": "ci_health",
            "checked_at": now_ts - 120.0,
            "overall_status": "ok",
            "runtime_metadata": {"git_commit": "sha-deeper"},
        },
    )
    _write_json(
        tmp_path / "release_fail.json",
        {
            "report_kind": "release_gates",
            "checked_at": now_ts - 60.0,
            "overall_status": "fail",
            "runtime_metadata": {"git_commit": "sha-release"},
            "gates": [
                {
                    "name": "provider_health",
                    "status": "fail",
                    "details": {
                        "failures": [
                            {
                                "code": "STALE_MANIFEST_GENERATED_AT",
                            }
                        ]
                    },
                }
            ],
        },
    )

    captured: list[dict] = []
    monkeypatch.setattr(
        evidence_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                input_glob=str(tmp_path / "*.json"),
                lookback_days=14,
                min_deeper_ok_runs=1,
                min_release_ok_runs=1,
                fail_on_not_ready=True,
                output="-",
            )
        ),
    )
    monkeypatch.setattr(evidence_script, "_render", lambda report, output: captured.append(report))

    rc = evidence_script.main()

    assert rc == 1
    assert captured[-1]["green_ready"] is False
    assert captured[-1]["unresolved_core_failures_in_window"] >= 1
    assert captured[-1]["stale_trend"].get("STALE_MANIFEST_GENERATED_AT") == 1


def test_gate_evidence_aggregates_measurement_artifacts(monkeypatch, tmp_path: Path) -> None:
    now_ts = 1_700_000_000.0
    monkeypatch.setattr(evidence_script.time, "time", lambda: now_ts)

    measurement_dir = tmp_path / "measurement" / "AAPL" / "15m"
    measurement_dir.mkdir(parents=True)
    _write_json(
        measurement_dir / "benchmark_AAPL_15m.json",
        {
            "schema_version": "2.0.0",
            "symbol": "AAPL",
            "timeframe": "15m",
            "generated_at": now_ts - 60.0,
            "kpis": [
                {"family": "BOS", "n_events": 1},
                {"family": "OB", "n_events": 0},
                {"family": "FVG", "n_events": 0},
                {"family": "SWEEP", "n_events": 1},
            ],
            "stratified": {
                "htf_bias:BULLISH": [
                    {"family": "BOS", "n_events": 1},
                    {"family": "SWEEP", "n_events": 1},
                ],
                "session:NY_AM": [
                    {"family": "BOS", "n_events": 1},
                ],
            },
        },
    )
    _write_json(
        measurement_dir / "manifest.json",
        {
            "schema_version": "2.0.0",
            "generated_at": now_ts - 60.0,
            "artifacts": ["benchmark_AAPL_15m.json"],
        },
    )
    _write_json(
        measurement_dir / "scoring_AAPL_15m.json",
        {
            "schema_version": "2.0.0",
            "symbol": "AAPL",
            "timeframe": "15m",
            "generated_at": now_ts - 60.0,
            "n_events": 2,
            "brier_score": 0.125,
            "log_score": 0.5,
            "hit_rate": 0.5,
            "aggregate": {
                "n_events": 2,
                "brier_score": 0.125,
                "log_score": 0.5,
                "hit_rate": 0.5,
            },
            "calibration": {
                "method": "beta_bin",
                "applied": True,
                "input_kind": "predicted_prob",
                "source_name": "predicted_prob",
                "n_events": 2,
                "positive_rate": 0.5,
                "raw_brier_score": 0.125,
                "calibrated_brier_score": 0.111111,
                "raw_log_score": 0.5,
                "calibrated_log_score": 0.46,
                "raw_ece": 0.15,
                "calibrated_ece": 0.1,
                "delta_brier_score": 0.013889,
                "delta_log_score": 0.04,
                "delta_ece": 0.05,
                "bins": [],
                "parameters": {"bin_count": 10, "alpha": 1.0, "beta": 1.0},
                "warnings": ["insufficient_events_for_platt_scaling"],
            },
            "stratified_calibration": {
                "session": {
                    "dimension": "session",
                    "total_groups": 1,
                    "populated_groups": 1,
                    "groups": {
                        "NY_AM": {
                            "method": "beta_bin",
                            "applied": True,
                            "input_kind": "predicted_prob",
                            "source_name": "predicted_prob",
                            "n_events": 2,
                            "positive_rate": 0.5,
                            "raw_brier_score": 0.125,
                            "calibrated_brier_score": 0.111111,
                            "raw_log_score": 0.5,
                            "calibrated_log_score": 0.46,
                            "raw_ece": 0.15,
                            "calibrated_ece": 0.1,
                            "delta_brier_score": 0.013889,
                            "delta_log_score": 0.04,
                            "delta_ece": 0.05,
                            "bins": [],
                            "parameters": {"bin_count": 10},
                            "warnings": [],
                        }
                    },
                }
            },
            "family_metrics": {
                "BOS": {"family": "BOS", "n_events": 1, "brier_score": 0.16, "log_score": 0.6, "hit_rate": 0.0},
                "SWEEP": {"family": "SWEEP", "n_events": 1, "brier_score": 0.09, "log_score": 0.4, "hit_rate": 1.0},
            },
        },
    )
    _write_json(
        measurement_dir / "measurement_manifest.json",
        {
            "schema_version": "2.0.0",
            "generated_at": now_ts - 60.0,
            "symbol": "AAPL",
            "timeframe": "15m",
            "measurement_evidence_present": True,
            "artifacts": {
                "benchmark": {
                    "present": True,
                    "artifact_path": "benchmark_AAPL_15m.json",
                    "manifest_path": "manifest.json",
                },
                "scoring": {
                    "present": True,
                    "artifact_path": "scoring_AAPL_15m.json",
                },
            },
            "quality_summary": {
                "benchmark_event_counts": {"BOS": 1, "OB": 0, "FVG": 0, "SWEEP": 1},
                "stratification_coverage": {
                    "bucket_count": 2,
                    "populated_bucket_count": 2,
                    "dimensions_present": ["htf_bias", "session"],
                    "bucket_event_counts": {
                        "htf_bias:BULLISH": 2,
                        "session:NY_AM": 1,
                    },
                },
                "n_events": 2,
                "brier_score": 0.125,
                "log_score": 0.5,
                "hit_rate": 0.5,
                "calibration": {
                    "method": "beta_bin",
                    "applied": True,
                    "input_kind": "predicted_prob",
                    "source_name": "predicted_prob",
                    "n_events": 2,
                    "positive_rate": 0.5,
                    "raw_brier_score": 0.125,
                    "calibrated_brier_score": 0.111111,
                    "raw_log_score": 0.5,
                    "calibrated_log_score": 0.46,
                    "raw_ece": 0.15,
                    "calibrated_ece": 0.1,
                    "delta_brier_score": 0.013889,
                    "delta_log_score": 0.04,
                    "delta_ece": 0.05,
                },
                "stratified_calibration": {
                    "dimensions_present": ["session"],
                    "dimension_group_counts": {"session": 1},
                    "dimension_populated_groups": {"session": 1},
                },
                "family_metrics": {
                    "BOS": {"n_events": 1, "brier_score": 0.16, "log_score": 0.6, "hit_rate": 0.0},
                    "SWEEP": {"n_events": 1, "brier_score": 0.09, "log_score": 0.4, "hit_rate": 1.0},
                },
            },
            "warnings": [],
        },
    )
    _write_json(
        tmp_path / "release_measurement.json",
        {
            "report_kind": "release_gates",
            "checked_at": now_ts - 30.0,
            "overall_status": "ok",
            "reference_symbols": _BROAD_SYMBOLS,
            "reference_timeframes": _BROAD_TIMEFRAMES,
            "runtime_metadata": {"git_commit": "sha-measurement"},
            "gates": [
                {"name": "provider_health", "status": "ok", "details": {}},
                {
                    "name": "measurement_lane",
                    "status": "ok",
                    "blocking": False,
                    "details": {
                        "symbol": "AAPL",
                        "timeframe": "15m",
                        "measurement_manifest_present": True,
                        "measurement_manifest_path": "measurement/AAPL/15m/measurement_manifest.json",
                        "measurement_artifacts_present": True,
                        "scoring_artifacts_present": True,
                    },
                },
            ],
        },
    )

    captured: list[dict] = []
    monkeypatch.setattr(
        evidence_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                input_glob=str(tmp_path / "*.json"),
                lookback_days=14,
                min_deeper_ok_runs=0,
                min_release_ok_runs=0,
                fail_on_not_ready=False,
                output="-",
            )
        ),
    )
    monkeypatch.setattr(evidence_script, "_render", lambda report, output: captured.append(report))

    rc = evidence_script.main()

    assert rc == 0
    measurement_history = captured[-1]["measurement_history"]
    assert measurement_history["runs_with_measurement_gate"] == 1
    assert measurement_history["artifact_load_failures"] == []
    latest = measurement_history["latest_by_pair"]["AAPL/15m"]
    assert latest["measurement_manifest_present"] is True
    assert latest["benchmark_artifact_present"] is True
    assert latest["scoring_artifact_present"] is True
    assert latest["brier_score"] == 0.125
    assert latest["log_score"] == 0.5
    assert latest["n_events"] == 2
    assert latest["calibrated_brier_score"] == 0.111111
    assert latest["calibrated_log_score"] == 0.46
    assert latest["calibrated_ece"] == 0.1
    assert latest["benchmark_event_counts"]["SWEEP"] == 1
    assert latest["stratification_coverage"]["bucket_count"] == 2
    assert latest["stratification_coverage"]["dimensions_present"] == ["htf_bias", "session"]
    assert latest["stratified_calibration"]["dimensions_present"] == ["session"]
    assert latest["family_metrics"]["BOS"]["n_events"] == 1
    assert latest["family_metrics"]["SWEEP"]["hit_rate"] == 1.0
    assert latest["measurement_shadow_baseline"]["available"] is False
    assert latest["measurement_degradations_detected"] == []
    assert measurement_history["shadow_degradations_detected"] == []
    assert captured[-1]["runs"][0]["measurement"]["measurement_manifest_path"] == "measurement/AAPL/15m/measurement_manifest.json"


def test_gate_evidence_detects_measurement_history_regression(monkeypatch, tmp_path: Path) -> None:
    now_ts = 1_700_000_000.0
    monkeypatch.setattr(evidence_script.time, "time", lambda: now_ts)

    def _write_measurement_run(prefix: str, *, checked_at: float, brier: float, log_score: float, n_events: int, populated_buckets: int) -> None:
        calibrated_ece = min(0.29, round(0.03 + (brier * 0.8), 6))
        measurement_dir = tmp_path / prefix / "AAPL" / "15m"
        measurement_dir.mkdir(parents=True)
        _write_json(
            measurement_dir / "benchmark_AAPL_15m.json",
            {
                "schema_version": "2.0.0",
                "symbol": "AAPL",
                "timeframe": "15m",
                "generated_at": checked_at,
                "kpis": [
                    {"family": "BOS", "n_events": n_events},
                ],
                "stratified": {
                    **{f"htf_bias:BULLISH:{idx}": [{"family": "BOS", "n_events": 1}] for idx in range(populated_buckets)},
                },
            },
        )
        _write_json(
            measurement_dir / "manifest.json",
            {
                "schema_version": "2.0.0",
                "generated_at": checked_at,
                "artifacts": ["benchmark_AAPL_15m.json"],
            },
        )
        _write_json(
            measurement_dir / "scoring_AAPL_15m.json",
            {
                "schema_version": "2.0.0",
                "symbol": "AAPL",
                "timeframe": "15m",
                "generated_at": checked_at,
                "n_events": n_events,
                "brier_score": brier,
                "log_score": log_score,
                "hit_rate": 0.5,
                "aggregate": {
                    "n_events": n_events,
                    "brier_score": brier,
                    "log_score": log_score,
                    "hit_rate": 0.5,
                },
                "calibration": {
                    "method": "beta_bin",
                    "applied": True,
                    "input_kind": "predicted_prob",
                    "source_name": "predicted_prob",
                    "n_events": n_events,
                    "positive_rate": 0.5,
                    "raw_brier_score": brier,
                    "calibrated_brier_score": max(0.0, round(brier - 0.02, 6)),
                    "raw_log_score": log_score,
                    "calibrated_log_score": max(0.0, round(log_score - 0.03, 6)),
                    "raw_ece": 0.2,
                    "calibrated_ece": calibrated_ece,
                    "delta_brier_score": 0.02,
                    "delta_log_score": 0.03,
                    "delta_ece": 0.05,
                    "bins": [],
                    "parameters": {"bin_count": 10},
                    "warnings": [],
                },
                "stratified_calibration": {
                    "htf_bias": {
                        "dimension": "htf_bias",
                        "total_groups": 1,
                        "populated_groups": 1,
                        "groups": {
                            "BULLISH": {
                                "method": "beta_bin",
                                "applied": True,
                                "input_kind": "predicted_prob",
                                "source_name": "predicted_prob",
                                "n_events": n_events,
                                "positive_rate": 0.5,
                                "raw_brier_score": brier,
                                "calibrated_brier_score": max(0.0, round(brier - 0.02, 6)),
                                "raw_log_score": log_score,
                                "calibrated_log_score": max(0.0, round(log_score - 0.03, 6)),
                                "raw_ece": 0.2,
                                "calibrated_ece": calibrated_ece,
                                "delta_brier_score": 0.02,
                                "delta_log_score": 0.03,
                                "delta_ece": 0.05,
                                "bins": [],
                                "parameters": {"bin_count": 10},
                                "warnings": [],
                            }
                        },
                    }
                },
                "family_metrics": {
                    "BOS": {"family": "BOS", "n_events": n_events, "brier_score": brier, "log_score": log_score, "hit_rate": 0.5},
                },
            },
        )
        _write_json(
            measurement_dir / "measurement_manifest.json",
            {
                "schema_version": "2.0.0",
                "generated_at": checked_at,
                "symbol": "AAPL",
                "timeframe": "15m",
                "measurement_evidence_present": True,
                "artifacts": {
                    "benchmark": {
                        "present": True,
                        "artifact_path": "benchmark_AAPL_15m.json",
                        "manifest_path": "manifest.json",
                    },
                    "scoring": {
                        "present": True,
                        "artifact_path": "scoring_AAPL_15m.json",
                    },
                },
                "quality_summary": {
                    "benchmark_event_counts": {"BOS": n_events},
                    "stratification_coverage": {
                        "bucket_count": populated_buckets,
                        "populated_bucket_count": populated_buckets,
                        "dimensions_present": ["htf_bias"],
                        "bucket_event_counts": {f"htf_bias:BULLISH:{idx}": 1 for idx in range(populated_buckets)},
                    },
                    "n_events": n_events,
                    "brier_score": brier,
                    "log_score": log_score,
                    "hit_rate": 0.5,
                    "calibration": {
                        "method": "beta_bin",
                        "applied": True,
                        "input_kind": "predicted_prob",
                        "source_name": "predicted_prob",
                        "n_events": n_events,
                        "positive_rate": 0.5,
                        "raw_brier_score": brier,
                        "calibrated_brier_score": max(0.0, round(brier - 0.02, 6)),
                        "raw_log_score": log_score,
                        "calibrated_log_score": max(0.0, round(log_score - 0.03, 6)),
                        "raw_ece": 0.2,
                            "calibrated_ece": calibrated_ece,
                        "delta_brier_score": 0.02,
                        "delta_log_score": 0.03,
                        "delta_ece": 0.05,
                    },
                    "stratified_calibration": {
                        "dimensions_present": ["htf_bias"],
                        "dimension_group_counts": {"htf_bias": 1},
                        "dimension_populated_groups": {"htf_bias": 1},
                    },
                    "family_metrics": {
                        "BOS": {"n_events": n_events, "brier_score": brier, "log_score": log_score, "hit_rate": 0.5},
                    },
                },
                "warnings": [],
            },
        )
        _write_json(
            tmp_path / f"{prefix}.json",
            {
                "report_kind": "release_gates",
                "checked_at": checked_at,
                "overall_status": "ok",
                "reference_symbols": _BROAD_SYMBOLS,
                "reference_timeframes": _BROAD_TIMEFRAMES,
                "runtime_metadata": {"git_commit": f"sha-{prefix}"},
                "gates": [
                    {"name": "provider_health", "status": "ok", "details": {}},
                    {
                        "name": "measurement_lane",
                        "status": "ok",
                        "blocking": False,
                        "details": {
                            "symbol": "AAPL",
                            "timeframe": "15m",
                            "measurement_manifest_present": True,
                            "measurement_manifest_path": f"{prefix}/AAPL/15m/measurement_manifest.json",
                            "measurement_artifacts_present": True,
                            "scoring_artifacts_present": True,
                        },
                    },
                ],
            },
        )

    _write_measurement_run("measurement_prev1", checked_at=now_ts - 180.0, brier=0.10, log_score=0.30, n_events=10, populated_buckets=3)
    _write_measurement_run("measurement_prev2", checked_at=now_ts - 120.0, brier=0.12, log_score=0.34, n_events=9, populated_buckets=3)
    _write_measurement_run("measurement_latest", checked_at=now_ts - 60.0, brier=0.29, log_score=0.72, n_events=3, populated_buckets=1)

    captured: list[dict] = []
    monkeypatch.setattr(
        evidence_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                input_glob=str(tmp_path / "*.json"),
                lookback_days=14,
                min_deeper_ok_runs=0,
                min_release_ok_runs=0,
                fail_on_not_ready=False,
                output="-",
            )
        ),
    )
    monkeypatch.setattr(evidence_script, "_render", lambda report, output: captured.append(report))

    rc = evidence_script.main()

    assert rc == 0
    latest = captured[-1]["measurement_history"]["latest_by_pair"]["AAPL/15m"]
    assert latest["measurement_shadow_baseline"]["available"] is True
    codes = {row["code"] for row in latest["measurement_degradations_detected"]}
    assert codes == {
        "MEASUREMENT_BRIER_REGRESSION",
        "MEASUREMENT_LOG_SCORE_REGRESSION",
            "MEASUREMENT_CALIBRATED_BRIER_ABOVE_THRESHOLD",
            "MEASUREMENT_CALIBRATED_ECE_ABOVE_THRESHOLD",
        "MEASUREMENT_CALIBRATED_BRIER_REGRESSION",
        "MEASUREMENT_CALIBRATED_ECE_REGRESSION",
        "MEASUREMENT_EVENT_COVERAGE_REGRESSION",
        "MEASUREMENT_STRATIFICATION_COVERAGE_REGRESSION",
    }
    assert captured[-1]["measurement_history"]["pairs_with_shadow_degradations"] == ["AAPL/15m"]
    assert len(captured[-1]["measurement_degradations_detected"]) == 8


def test_gate_evidence_surfaces_contextual_recommendation_and_promotion(monkeypatch, tmp_path: Path) -> None:
    now_ts = 1_700_000_000.0
    monkeypatch.setattr(evidence_script.time, "time", lambda: now_ts)

    def _contextual_payload() -> dict:
        return {
            "session": {
                "dimension": "session",
                "input_kind": "raw_score_0_100",
                "source_name": "SIGNAL_QUALITY_SCORE",
                "n_events": 12,
                "covered_events": 12,
                "coverage_ratio": 1.0,
                "total_groups": 2,
                "populated_groups": 2,
                "raw_brier_score": 0.18,
                "adjusted_brier_score": 0.14,
                "raw_log_score": 0.42,
                "adjusted_log_score": 0.36,
                "raw_ece": 0.12,
                "adjusted_ece": 0.08,
                "delta_brier_score": 0.04,
                "delta_log_score": 0.06,
                "delta_ece": 0.04,
                "group_method_counts": {"beta_bin": 2},
                "fallback_event_count": 0,
                "warnings": [],
            },
            "htf_bias": {
                "dimension": "htf_bias",
                "input_kind": "raw_score_0_100",
                "source_name": "SIGNAL_QUALITY_SCORE",
                "n_events": 12,
                "covered_events": 12,
                "coverage_ratio": 1.0,
                "total_groups": 2,
                "populated_groups": 2,
                "raw_brier_score": 0.18,
                "adjusted_brier_score": 0.16,
                "raw_log_score": 0.42,
                "adjusted_log_score": 0.39,
                "raw_ece": 0.12,
                "adjusted_ece": 0.1,
                "delta_brier_score": 0.02,
                "delta_log_score": 0.03,
                "delta_ece": 0.02,
                "group_method_counts": {"beta_bin": 2},
                "fallback_event_count": 0,
                "warnings": [],
            },
        }

    def _write_measurement_run(prefix: str, checked_at: float) -> None:
        measurement_dir = tmp_path / prefix / "AAPL" / "15m"
        measurement_dir.mkdir(parents=True)
        _write_json(
            measurement_dir / "benchmark_AAPL_15m.json",
            {
                "schema_version": "2.0.0",
                "symbol": "AAPL",
                "timeframe": "15m",
                "generated_at": checked_at,
                "kpis": [{"family": "BOS", "n_events": 12}],
                "stratified": {"session:NY_AM": [{"family": "BOS", "n_events": 6}]},
            },
        )
        _write_json(
            measurement_dir / "manifest.json",
            {
                "schema_version": "2.0.0",
                "generated_at": checked_at,
                "artifacts": ["benchmark_AAPL_15m.json"],
            },
        )
        _write_json(
            measurement_dir / "scoring_AAPL_15m.json",
            {
                "schema_version": "2.0.0",
                "symbol": "AAPL",
                "timeframe": "15m",
                "generated_at": checked_at,
                "n_events": 12,
                "brier_score": 0.18,
                "log_score": 0.42,
                "hit_rate": 0.5,
                "aggregate": {
                    "n_events": 12,
                    "brier_score": 0.18,
                    "log_score": 0.42,
                    "hit_rate": 0.5,
                },
                "calibration": {
                    "method": "beta_bin",
                    "applied": True,
                    "input_kind": "raw_score_0_100",
                    "source_name": "SIGNAL_QUALITY_SCORE",
                    "n_events": 12,
                    "positive_rate": 0.5,
                    "raw_brier_score": 0.18,
                    "calibrated_brier_score": 0.15,
                    "raw_log_score": 0.42,
                    "calibrated_log_score": 0.37,
                    "raw_ece": 0.12,
                    "calibrated_ece": 0.09,
                    "delta_brier_score": 0.03,
                    "delta_log_score": 0.05,
                    "delta_ece": 0.03,
                    "bins": [],
                    "parameters": {"bin_count": 10},
                    "warnings": [],
                },
                "stratified_calibration": {},
                "contextual_calibration": _contextual_payload(),
                "family_metrics": {
                    "BOS": {"family": "BOS", "n_events": 12, "brier_score": 0.18, "log_score": 0.42, "hit_rate": 0.5},
                },
            },
        )
        _write_json(
            measurement_dir / "measurement_manifest.json",
            {
                "schema_version": "2.0.0",
                "generated_at": checked_at,
                "symbol": "AAPL",
                "timeframe": "15m",
                "measurement_evidence_present": True,
                "artifacts": {
                    "benchmark": {
                        "present": True,
                        "artifact_path": "benchmark_AAPL_15m.json",
                        "manifest_path": "manifest.json",
                    },
                    "scoring": {
                        "present": True,
                        "artifact_path": "scoring_AAPL_15m.json",
                    },
                },
                "quality_summary": {
                    "benchmark_event_counts": {"BOS": 12},
                    "stratification_coverage": {
                        "bucket_count": 1,
                        "populated_bucket_count": 1,
                        "dimensions_present": ["session"],
                        "bucket_event_counts": {"session:NY_AM": 6},
                    },
                    "n_events": 12,
                    "brier_score": 0.18,
                    "log_score": 0.42,
                    "hit_rate": 0.5,
                    "calibration": {
                        "method": "beta_bin",
                        "applied": True,
                        "input_kind": "raw_score_0_100",
                        "source_name": "SIGNAL_QUALITY_SCORE",
                        "n_events": 12,
                        "positive_rate": 0.5,
                        "raw_brier_score": 0.18,
                        "calibrated_brier_score": 0.15,
                        "raw_log_score": 0.42,
                        "calibrated_log_score": 0.37,
                        "raw_ece": 0.12,
                        "calibrated_ece": 0.09,
                        "delta_brier_score": 0.03,
                        "delta_log_score": 0.05,
                        "delta_ece": 0.03,
                    },
                    "stratified_calibration": {
                        "dimensions_present": [],
                        "dimension_group_counts": {},
                        "dimension_populated_groups": {},
                    },
                    "contextual_calibration": {
                        "dimensions_present": ["htf_bias", "session"],
                        "improved_dimensions": ["htf_bias", "session"],
                        "best_dimension_by_adjusted_brier": "session",
                        "best_dimension_by_adjusted_ece": "session",
                    },
                    "family_metrics": {
                        "BOS": {"n_events": 12, "brier_score": 0.18, "log_score": 0.42, "hit_rate": 0.5},
                    },
                },
                "warnings": [],
            },
        )
        _write_json(
            tmp_path / f"{prefix}.json",
            {
                "report_kind": "release_gates",
                "checked_at": checked_at,
                "overall_status": "ok",
                "reference_symbols": _BROAD_SYMBOLS,
                "reference_timeframes": _BROAD_TIMEFRAMES,
                "runtime_metadata": {"git_commit": f"sha-{prefix}"},
                "gates": [
                    {"name": "provider_health", "status": "ok", "details": {}},
                    {
                        "name": "measurement_lane",
                        "status": "ok",
                        "blocking": False,
                        "details": {
                            "symbol": "AAPL",
                            "timeframe": "15m",
                            "measurement_manifest_present": True,
                            "measurement_manifest_path": f"{prefix}/AAPL/15m/measurement_manifest.json",
                            "measurement_artifacts_present": True,
                            "scoring_artifacts_present": True,
                        },
                    },
                ],
            },
        )

    _write_measurement_run("contextual_prev1", now_ts - 180.0)
    _write_measurement_run("contextual_prev2", now_ts - 120.0)
    _write_measurement_run("contextual_latest", now_ts - 60.0)

    captured: list[dict] = []
    monkeypatch.setattr(
        evidence_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                input_glob=str(tmp_path / "*.json"),
                lookback_days=14,
                min_deeper_ok_runs=0,
                min_release_ok_runs=0,
                fail_on_not_ready=False,
                output="-",
            )
        ),
    )
    monkeypatch.setattr(evidence_script, "_render", lambda report, output: captured.append(report))

    rc = evidence_script.main()

    assert rc == 0
    measurement_history = captured[-1]["measurement_history"]
    latest = measurement_history["latest_by_pair"]["AAPL/15m"]
    assert measurement_history["pairs_with_contextual_recommendation"] == ["AAPL/15m"]
    assert measurement_history["pairs_ready_for_contextual_promotion"] == ["AAPL/15m"]
    assert latest["contextual_calibration_recommendation"]["recommended_dimension"] == "session"
    assert latest["contextual_calibration_recommendation"]["basis"] == "metric_consensus"
    assert latest["contextual_calibration_promotion"]["promotion_ready"] is True
    assert latest["contextual_calibration_promotion"]["recommended_dimension"] == "session"
    assert measurement_history["contextual_recommendations_detected"][0]["recommended_dimension"] == "session"
    assert measurement_history["contextual_promotions_ready"][0]["recommended_dimension"] == "session"


# ---------------------------------------------------------------------------
# Domain-Staleness aggregation in evidence summary
# ---------------------------------------------------------------------------


def test_gate_evidence_aggregates_stale_domain_codes(monkeypatch, tmp_path: Path) -> None:
    now_ts = 1_700_000_000.0
    monkeypatch.setattr(evidence_script.time, "time", lambda: now_ts)

    # Deeper run with stale technical
    _write_json(
        tmp_path / "deeper_stale_tech.json",
        {
            "report_kind": "ci_health",
            "checked_at": now_ts - 120.0,
            "overall_status": "warn",
            "runtime_metadata": {"git_commit": "sha-1"},
            "degradations_detected": [{"code": "STALE_META_TECHNICAL_DOMAIN"}],
        },
    )
    # Deeper run with stale volume and news
    _write_json(
        tmp_path / "deeper_stale_vol_news.json",
        {
            "report_kind": "ci_health",
            "checked_at": now_ts - 60.0,
            "overall_status": "warn",
            "runtime_metadata": {"git_commit": "sha-2"},
            "degradations_detected": [
                {"code": "STALE_META_VOLUME_DOMAIN"},
                {"code": "STALE_META_NEWS_DOMAIN"},
            ],
        },
    )
    # Release run with stale volume (promoted to failure)
    _write_json(
        tmp_path / "release_stale_vol.json",
        {
            "report_kind": "release_gates",
            "checked_at": now_ts - 30.0,
            "overall_status": "fail",
            "runtime_metadata": {"git_commit": "sha-3"},
            "gates": [
                {
                    "name": "provider_health",
                    "status": "fail",
                    "details": {
                        "failures": [{"code": "STALE_META_VOLUME_DOMAIN", "promoted_by": "release_strict_policy"}],
                    },
                }
            ],
        },
    )

    captured: list[dict] = []
    monkeypatch.setattr(
        evidence_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                input_glob=str(tmp_path / "*.json"),
                lookback_days=14,
                min_deeper_ok_runs=1,
                min_release_ok_runs=1,
                fail_on_not_ready=False,
                output="-",
            )
        ),
    )
    monkeypatch.setattr(evidence_script, "_render", lambda report, output: captured.append(report))

    evidence_script.main()
    summary = captured[-1]

    # stale_domain_trend counts
    assert summary["stale_domain_trend"]["STALE_META_TECHNICAL_DOMAIN"] == 1
    assert summary["stale_domain_trend"]["STALE_META_VOLUME_DOMAIN"] == 2
    assert summary["stale_domain_trend"]["STALE_META_NEWS_DOMAIN"] == 1

    # stale_domain_runs has path info
    vol_runs = summary["stale_domain_runs"]["STALE_META_VOLUME_DOMAIN"]
    assert len(vol_runs) == 2
    assert all("path" in r and "checked_at_iso" in r for r in vol_runs)

    tech_runs = summary["stale_domain_runs"]["STALE_META_TECHNICAL_DOMAIN"]
    assert len(tech_runs) == 1

    # These codes also appear in the generic stale_trend
    assert summary["stale_trend"]["STALE_META_VOLUME_DOMAIN"] == 2
    assert summary["stale_trend"]["STALE_META_TECHNICAL_DOMAIN"] == 1


def test_gate_evidence_no_domain_stale_produces_empty_aggregation(monkeypatch, tmp_path: Path) -> None:
    now_ts = 1_700_000_000.0
    monkeypatch.setattr(evidence_script.time, "time", lambda: now_ts)

    _write_json(
        tmp_path / "deeper_ok.json",
        {
            "report_kind": "ci_health",
            "checked_at": now_ts - 60.0,
            "overall_status": "ok",
            "runtime_metadata": {"git_commit": "sha-clean"},
        },
    )

    captured: list[dict] = []
    monkeypatch.setattr(
        evidence_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                input_glob=str(tmp_path / "*.json"),
                lookback_days=14,
                min_deeper_ok_runs=1,
                min_release_ok_runs=0,
                fail_on_not_ready=False,
                output="-",
            )
        ),
    )
    monkeypatch.setattr(evidence_script, "_render", lambda report, output: captured.append(report))

    evidence_script.main()
    summary = captured[-1]

    assert summary["stale_domain_trend"] == {}
    assert summary["stale_domain_runs"] == {}


def test_gate_evidence_domain_stale_aggregation_is_deterministic(monkeypatch, tmp_path: Path) -> None:
    now_ts = 1_700_000_000.0
    monkeypatch.setattr(evidence_script.time, "time", lambda: now_ts)

    _write_json(
        tmp_path / "deeper_warn.json",
        {
            "report_kind": "ci_health",
            "checked_at": now_ts - 60.0,
            "overall_status": "warn",
            "runtime_metadata": {"git_commit": "sha-det"},
            "degradations_detected": [
                {"code": "STALE_META_NEWS_DOMAIN"},
                {"code": "STALE_META_VOLUME_DOMAIN"},
            ],
        },
    )

    results = []
    for _ in range(2):
        captured: list[dict] = []
        monkeypatch.setattr(
            evidence_script,
            "build_parser",
            lambda: _Parser(
                Namespace(
                    input_glob=str(tmp_path / "*.json"),
                    lookback_days=14,
                    min_deeper_ok_runs=0,
                    min_release_ok_runs=0,
                    fail_on_not_ready=False,
                    output="-",
                )
            ),
        )
        monkeypatch.setattr(evidence_script, "_render", lambda report, output: captured.append(report))
        evidence_script.main()
        results.append(captured[-1])

    import json
    assert json.dumps(results[0]["stale_domain_trend"], sort_keys=True) == json.dumps(results[1]["stale_domain_trend"], sort_keys=True)
    assert json.dumps(results[0]["stale_domain_runs"], sort_keys=True) == json.dumps(results[1]["stale_domain_runs"], sort_keys=True)


# ---------------------------------------------------------------------------
# latest_domain_diagnostics in evidence summary
# ---------------------------------------------------------------------------


def test_gate_evidence_surfaces_latest_domain_diagnostics(monkeypatch, tmp_path: Path) -> None:
    """Evidence summary should include the most recent meta_domain_diagnostics
    extracted from smoke_test_results in the input reports."""
    now_ts = 1_700_000_000.0
    monkeypatch.setattr(evidence_script.time, "time", lambda: now_ts)

    diag_old = {
        "volume": "present",
        "volume_source": "databento_watchlist_csv",
        "volume_fallback_used": False,
        "volume_asof_ts": 1_699_990_000.0,
        "volume_age_hours": 2.8,
        "volume_stale": False,
        "technical": "present",
        "technical_source": "fmp_watchlist_json",
        "technical_fallback_used": False,
        "technical_asof_ts": 1_699_800_000.0,
        "technical_age_hours": 55.6,
        "technical_stale": True,
        "news": "present",
        "news_source": "benzinga_watchlist_json",
        "news_fallback_used": False,
        "news_asof_ts": 1_699_992_000.0,
        "news_age_hours": 2.2,
        "news_stale": False,
    }
    diag_new = {**diag_old, "technical_age_hours": 1.0, "technical_stale": False}

    # Older report
    _write_json(
        tmp_path / "health_old.json",
        {
            "report_kind": "ci_health",
            "checked_at": now_ts - 300.0,
            "overall_status": "warn",
            "runtime_metadata": {"git_commit": "sha-old"},
            "smoke_test_results": [
                {"symbol": "USAR", "timeframe": "15m", "status": "warn", "meta_domain_diagnostics": diag_old},
            ],
        },
    )
    # Newer report with fresh technical
    _write_json(
        tmp_path / "health_new.json",
        {
            "report_kind": "ci_health",
            "checked_at": now_ts - 60.0,
            "overall_status": "ok",
            "runtime_metadata": {"git_commit": "sha-new"},
            "smoke_test_results": [
                {"symbol": "USAR", "timeframe": "15m", "status": "ok", "meta_domain_diagnostics": diag_new},
            ],
        },
    )

    captured: list[dict] = []
    monkeypatch.setattr(
        evidence_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                input_glob=str(tmp_path / "*.json"),
                lookback_days=14,
                min_deeper_ok_runs=0,
                min_release_ok_runs=0,
                fail_on_not_ready=False,
                output="-",
            )
        ),
    )
    monkeypatch.setattr(evidence_script, "_render", lambda report, output: captured.append(report))

    evidence_script.main()
    summary = captured[-1]

    assert "latest_domain_diagnostics" in summary
    usar_diag = summary["latest_domain_diagnostics"].get("USAR/15m")
    assert usar_diag is not None
    # Should reflect the newer report (technical not stale)
    assert usar_diag["technical_stale"] is False
    assert usar_diag["technical_age_hours"] == 1.0
    # Internal tracking key must not leak
    assert "_checked_at" not in usar_diag


def test_gate_evidence_no_smoke_results_produces_empty_diagnostics(monkeypatch, tmp_path: Path) -> None:
    now_ts = 1_700_000_000.0
    monkeypatch.setattr(evidence_script.time, "time", lambda: now_ts)

    _write_json(
        tmp_path / "deeper_ok.json",
        {
            "report_kind": "ci_health",
            "checked_at": now_ts - 60.0,
            "overall_status": "ok",
            "runtime_metadata": {"git_commit": "sha-no-smoke"},
        },
    )

    captured: list[dict] = []
    monkeypatch.setattr(
        evidence_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                input_glob=str(tmp_path / "*.json"),
                lookback_days=14,
                min_deeper_ok_runs=0,
                min_release_ok_runs=0,
                fail_on_not_ready=False,
                output="-",
            )
        ),
    )
    monkeypatch.setattr(evidence_script, "_render", lambda report, output: captured.append(report))

    evidence_script.main()
    assert captured[-1]["latest_domain_diagnostics"] == {}


# ---------------------------------------------------------------------------
# Coverage breadth checks
# ---------------------------------------------------------------------------


def test_gate_evidence_not_green_when_symbol_breadth_insufficient(monkeypatch, tmp_path: Path) -> None:
    """Enough runs, but only 2 symbols — should fail green_ready due to breadth."""
    now_ts = 1_700_000_000.0
    monkeypatch.setattr(evidence_script.time, "time", lambda: now_ts)

    for idx in range(3):
        _write_json(
            tmp_path / f"deeper_{idx}.json",
            {
                "report_kind": "ci_health",
                "checked_at": now_ts - 60.0 * (idx + 1),
                "overall_status": "ok",
                "reference_symbols": ["AAPL", "MSFT"],
                "reference_timeframes": ["5m", "15m", "1H", "4H"],
            },
        )
    for idx in range(2):
        _write_json(
            tmp_path / f"release_{idx}.json",
            {
                "report_kind": "release_gates",
                "checked_at": now_ts - 500.0 - 60.0 * idx,
                "overall_status": "ok",
                "reference_symbols": ["AAPL", "MSFT"],
                "reference_timeframes": ["5m", "15m", "1H", "4H"],
                "gates": [{"name": "provider_health", "status": "ok", "details": {}}],
            },
        )

    captured: list[dict] = []
    monkeypatch.setattr(
        evidence_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                input_glob=str(tmp_path / "*.json"),
                lookback_days=14,
                min_deeper_ok_runs=3,
                min_release_ok_runs=2,
                fail_on_not_ready=True,
                output="-",
            )
        ),
    )
    monkeypatch.setattr(evidence_script, "_render", lambda report, output: captured.append(report))

    rc = evidence_script.main()
    assert rc == 1
    assert captured[-1]["green_ready"] is False
    assert captured[-1]["symbol_breadth_ok"] is False
    assert any(r["reason"] == "INSUFFICIENT_SYMBOL_BREADTH" for r in captured[-1]["not_ready_reasons"])


def test_gate_evidence_includes_coverage_fields_when_green(monkeypatch, tmp_path: Path) -> None:
    now_ts = 1_700_000_000.0
    monkeypatch.setattr(evidence_script.time, "time", lambda: now_ts)

    for idx in range(3):
        _write_json(
            tmp_path / f"deeper_{idx}.json",
            {
                "report_kind": "ci_health",
                "checked_at": now_ts - 60.0 * (idx + 1),
                "overall_status": "ok",
                "reference_symbols": _BROAD_SYMBOLS,
                "reference_timeframes": _BROAD_TIMEFRAMES,
            },
        )
    for idx in range(2):
        _write_json(
            tmp_path / f"release_{idx}.json",
            {
                "report_kind": "release_gates",
                "checked_at": now_ts - 500.0 - 60.0 * idx,
                "overall_status": "ok",
                "reference_symbols": _BROAD_SYMBOLS,
                "reference_timeframes": _BROAD_TIMEFRAMES,
                "gates": [{"name": "provider_health", "status": "ok", "details": {}}],
            },
        )

    captured: list[dict] = []
    monkeypatch.setattr(
        evidence_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                input_glob=str(tmp_path / "*.json"),
                lookback_days=14,
                min_deeper_ok_runs=3,
                min_release_ok_runs=2,
                fail_on_not_ready=False,
                output="-",
            )
        ),
    )
    monkeypatch.setattr(evidence_script, "_render", lambda report, output: captured.append(report))

    rc = evidence_script.main()
    assert rc == 0
    summary = captured[-1]
    assert summary["green_ready"] is True
    assert summary["symbol_breadth_ok"] is True
    assert summary["timeframe_breadth_ok"] is True
    assert set(summary["covered_symbols"]) == set(s.upper() for s in _BROAD_SYMBOLS)
    assert set(summary["covered_timeframes"]) == set(_BROAD_TIMEFRAMES)
    assert summary["not_ready_reasons"] == []
