"""Tests for release policy defaults, env/CLI overrides, stale thresholds,
evidence coverage, and failure diagnostics."""
from __future__ import annotations

from typing import Any

import pytest

from smc_integration.release_policy import (
    EVIDENCE_MIN_SYMBOL_COVERAGE,
    EVIDENCE_MIN_TIMEFRAME_COVERAGE,
    REASON_INSUFFICIENT_SYMBOLS,
    REASON_INSUFFICIENT_TIMEFRAMES,
    REASON_MEASUREMENT_QUALITY,
    REASON_MISSING_ARTIFACT,
    REASON_PROVIDER_FAILURE,
    REASON_SMOKE_FAILURE,
    REASON_STALE_DATA,
    RELEASE_REFERENCE_SYMBOLS,
    RELEASE_REFERENCE_TIMEFRAMES,
    RELEASE_STALE_AFTER_SECONDS,
    ContextualCalibrationPromotionPolicy,
    ContextualCalibrationRecommendationPolicy,
    MeasurementShadowThresholds,
    assess_contextual_calibration_promotion,
    assess_measurement_shadow_degradations,
    build_measurement_shadow_baseline,
    diagnose_gate_failure,
    parse_csv,
    recommend_contextual_calibration,
    resolve_release_policy,
)

# ---------------------------------------------------------------------------
# Default policy values
# ---------------------------------------------------------------------------

class TestDefaultPolicy:
    def test_reference_symbols_has_broad_coverage(self) -> None:
        assert len(RELEASE_REFERENCE_SYMBOLS) >= 10

    def test_reference_symbols_all_uppercase(self) -> None:
        for sym in RELEASE_REFERENCE_SYMBOLS:
            assert sym == sym.upper(), f"{sym} is not uppercase"

    def test_reference_symbols_no_duplicates(self) -> None:
        assert len(RELEASE_REFERENCE_SYMBOLS) == len(set(RELEASE_REFERENCE_SYMBOLS))

    def test_reference_timeframes_include_intraday_and_higher(self) -> None:
        tfs = set(RELEASE_REFERENCE_TIMEFRAMES)
        assert "5m" in tfs
        assert "10m" in tfs
        assert "15m" in tfs
        assert "30m" in tfs
        assert "1D" in tfs
        assert len(tfs) >= 7, "need the full canonical timeframe set"

    def test_stale_threshold_is_7_days(self) -> None:
        assert RELEASE_STALE_AFTER_SECONDS == 7 * 24 * 60 * 60

    def test_coverage_thresholds_are_positive(self) -> None:
        assert EVIDENCE_MIN_SYMBOL_COVERAGE >= 1
        assert EVIDENCE_MIN_TIMEFRAME_COVERAGE >= 4


# ---------------------------------------------------------------------------
# resolve_release_policy — explicit > env > defaults
# ---------------------------------------------------------------------------

class TestResolvePolicy:
    def test_defaults_when_no_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SMC_RELEASE_SYMBOLS", raising=False)
        monkeypatch.delenv("SMC_RELEASE_TIMEFRAMES", raising=False)
        monkeypatch.delenv("SMC_RELEASE_STALE_SECONDS", raising=False)
        policy = resolve_release_policy()
        assert policy["symbols"] == list(RELEASE_REFERENCE_SYMBOLS)
        assert policy["timeframes"] == list(RELEASE_REFERENCE_TIMEFRAMES)
        assert policy["stale_after_seconds"] == RELEASE_STALE_AFTER_SECONDS

    def test_env_overrides_symbols(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SMC_RELEASE_SYMBOLS", "TSLA,NVDA")
        monkeypatch.delenv("SMC_RELEASE_TIMEFRAMES", raising=False)
        monkeypatch.delenv("SMC_RELEASE_STALE_SECONDS", raising=False)
        policy = resolve_release_policy()
        assert policy["symbols"] == ["TSLA", "NVDA"]
        assert policy["timeframes"] == list(RELEASE_REFERENCE_TIMEFRAMES)

    def test_env_overrides_timeframes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SMC_RELEASE_SYMBOLS", raising=False)
        monkeypatch.setenv("SMC_RELEASE_TIMEFRAMES", "1m,5m")
        monkeypatch.delenv("SMC_RELEASE_STALE_SECONDS", raising=False)
        policy = resolve_release_policy()
        assert policy["timeframes"] == ["1m", "5m"]

    def test_env_overrides_stale_seconds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SMC_RELEASE_SYMBOLS", raising=False)
        monkeypatch.delenv("SMC_RELEASE_TIMEFRAMES", raising=False)
        monkeypatch.setenv("SMC_RELEASE_STALE_SECONDS", "3600")
        policy = resolve_release_policy()
        assert policy["stale_after_seconds"] == 3600

    def test_explicit_args_override_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SMC_RELEASE_SYMBOLS", "TSLA,NVDA")
        monkeypatch.setenv("SMC_RELEASE_TIMEFRAMES", "1m")
        monkeypatch.setenv("SMC_RELEASE_STALE_SECONDS", "9999")
        policy = resolve_release_policy(
            symbols="GOOG,AMZN",
            timeframes="4H",
            stale_after_seconds=1800,
        )
        assert policy["symbols"] == ["GOOG", "AMZN"]
        assert policy["timeframes"] == ["4H"]
        assert policy["stale_after_seconds"] == 1800

    def test_csv_with_whitespace_and_duplicates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SMC_RELEASE_SYMBOLS", raising=False)
        policy = resolve_release_policy(symbols=" AAPL , msft ,AAPL ")
        assert policy["symbols"] == ["AAPL", "MSFT"]

    def test_parse_csv_uppercases_and_deduplicates(self) -> None:
        assert parse_csv(" aapl ,, msft , AAPL , meta ", normalize_upper=True) == ["AAPL", "MSFT", "META"]

    def test_parse_csv_preserves_non_uppercase_tokens(self) -> None:
        assert parse_csv("5m, 15m,5m, 1H") == ["5m", "15m", "1H"]


# ---------------------------------------------------------------------------
# Stale threshold semantics
# ---------------------------------------------------------------------------

class TestStaleThreshold:
    def test_seven_day_threshold_in_seconds(self) -> None:
        assert RELEASE_STALE_AFTER_SECONDS == 604800

    def test_env_can_tighten_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SMC_RELEASE_STALE_SECONDS", "86400")  # 1 day
        monkeypatch.delenv("SMC_RELEASE_SYMBOLS", raising=False)
        monkeypatch.delenv("SMC_RELEASE_TIMEFRAMES", raising=False)
        policy = resolve_release_policy()
        assert policy["stale_after_seconds"] == 86400


# ---------------------------------------------------------------------------
# diagnose_gate_failure
# ---------------------------------------------------------------------------

class TestDiagnoseGateFailure:
    def test_empty_report_yields_only_breadth_reasons(self) -> None:
        reasons = diagnose_gate_failure({})
        # No failure/gate codes, but missing reference_symbols/timeframes triggers breadth warnings.
        assert all(r["reason"] in {REASON_INSUFFICIENT_SYMBOLS, REASON_INSUFFICIENT_TIMEFRAMES} for r in reasons)

    def test_stale_failure_classified(self) -> None:
        report: dict[str, Any] = {
            "failures": [{"code": "STALE_MANIFEST_GENERATED_AT"}],
        }
        reasons = diagnose_gate_failure(report)
        assert any(r["reason"] == REASON_STALE_DATA for r in reasons)

    def test_missing_artifact_classified(self) -> None:
        report: dict[str, Any] = {
            "failures": [{"code": "MISSING_ARTIFACT"}],
        }
        reasons = diagnose_gate_failure(report)
        assert any(r["reason"] == REASON_MISSING_ARTIFACT for r in reasons)

    def test_smoke_failure_classified(self) -> None:
        report: dict[str, Any] = {
            "gates": [
                {
                    "name": "provider_health",
                    "status": "fail",
                    "details": {
                        "missing_smoke_failures": [
                            {"code": "MISSING_SMOKE_RESULT", "symbol": "AAPL", "timeframe": "15m"},
                        ],
                    },
                }
            ],
        }
        reasons = diagnose_gate_failure(report)
        assert any(r["reason"] == REASON_SMOKE_FAILURE for r in reasons)

    def test_insufficient_symbol_breadth(self) -> None:
        report: dict[str, Any] = {
            "reference_symbols": ["AAPL"],
            "reference_timeframes": ["5m", "15m", "1H", "4H"],
        }
        reasons = diagnose_gate_failure(report)
        assert any(r["reason"] == REASON_INSUFFICIENT_SYMBOLS for r in reasons)

    def test_sufficient_breadth_emits_no_breadth_reason(self) -> None:
        report: dict[str, Any] = {
            "reference_symbols": [f"SYM{i}" for i in range(EVIDENCE_MIN_SYMBOL_COVERAGE)],
            "reference_timeframes": [f"tf{i}" for i in range(EVIDENCE_MIN_TIMEFRAME_COVERAGE)],
        }
        reasons = diagnose_gate_failure(report)
        breadth_reasons = [r for r in reasons if r["reason"] in {REASON_INSUFFICIENT_SYMBOLS, REASON_INSUFFICIENT_TIMEFRAMES}]
        assert breadth_reasons == []

    def test_multiple_reasons_deduplicated(self) -> None:
        report: dict[str, Any] = {
            "failures": [
                {"code": "STALE_MANIFEST_GENERATED_AT"},
                {"code": "STALE_MANIFEST_GENERATED_AT"},
            ],
        }
        reasons = diagnose_gate_failure(report)
        stale = [r for r in reasons if r["reason"] == REASON_STALE_DATA]
        assert len(stale) == 1

    def test_warn_only_measurement_degradation_is_not_reported_as_failure_reason(self) -> None:
        report: dict[str, Any] = {
            "gates": [
                {
                    "name": "measurement_lane",
                    "status": "warn",
                    "blocking": False,
                    "details": {
                        "degradations_detected": [
                            {"code": "MEASUREMENT_BRIER_REGRESSION"},
                        ],
                    },
                }
            ],
        }
        reasons = diagnose_gate_failure(report)
        assert not any(r["reason"] == REASON_MEASUREMENT_QUALITY for r in reasons)

    def test_blocking_measurement_quality_degradation_classified(self) -> None:
        report: dict[str, Any] = {
            "gates": [
                {
                    "name": "measurement_lane",
                    "status": "fail",
                    "blocking": True,
                    "details": {
                        "degradations_detected": [
                            {"code": "MEASUREMENT_BRIER_REGRESSION"},
                        ],
                    },
                }
            ],
        }
        reasons = diagnose_gate_failure(report)
        assert any(r["reason"] == REASON_MEASUREMENT_QUALITY for r in reasons)

    def test_empty_structure_smoke_issue_classified(self) -> None:
        report: dict[str, Any] = {
            "gates": [
                {
                    "name": "provider_health",
                    "status": "fail",
                    "details": {
                        "degradations_detected": [
                            {"code": "EMPTY_STRUCTURE_INPUT", "symbol": "AAPL", "timeframe": "5m"},
                        ],
                    },
                }
            ],
        }
        reasons = diagnose_gate_failure(report)
        assert {"reason": REASON_SMOKE_FAILURE, "detail": "EMPTY_STRUCTURE_INPUT (AAPL/5m)"} in reasons

    def test_provider_failure_classified(self) -> None:
        report: dict[str, Any] = {
            "failures": [{"code": "PROVIDER_MATRIX_REFRESH_FAILED"}],
            "reference_symbols": [f"SYM{i}" for i in range(EVIDENCE_MIN_SYMBOL_COVERAGE)],
            "reference_timeframes": [f"tf{i}" for i in range(EVIDENCE_MIN_TIMEFRAME_COVERAGE)],
        }
        reasons = diagnose_gate_failure(report)
        assert {"reason": REASON_PROVIDER_FAILURE, "detail": "PROVIDER_MATRIX_REFRESH_FAILED"} in reasons


class TestMeasurementShadowGovernance:
    def test_shadow_baseline_requires_history(self) -> None:
        baseline = build_measurement_shadow_baseline(
            [
                {
                    "brier_score": 0.12,
                    "calibrated_brier_score": 0.10,
                    "calibrated_ece": 0.08,
                    "n_events": 8,
                    "stratification_coverage": {"populated_bucket_count": 2},
                }
            ]
        )
        assert baseline["available"] is False
        assert baseline["history_runs"] == 1
        assert baseline["calibrated_brier_score"] == 0.1
        assert baseline["calibrated_ece"] == 0.08
        assert baseline["effective_thresholds"] == {}
        assert baseline["history_tightened_metrics"] == []

    def test_shadow_baseline_exposes_history_tightened_effective_thresholds(self) -> None:
        thresholds = MeasurementShadowThresholds(
            max_calibrated_brier_score=0.60,
            max_calibrated_ece=0.30,
            max_calibrated_brier_regression_abs=0.05,
            max_calibrated_ece_regression_abs=0.04,
            min_history_runs=2,
            # legacy: keep calibrated-threshold eligibility at 1 event so this
            # fixture (n_events=8) continues to trigger ABOVE_THRESHOLD rows.
            min_events_for_calibrated_thresholds=1,
        )
        current = {
            "calibrated_brier_score": 0.19,
            "calibrated_ece": 0.14,
            "n_events": 8,
            "stratification_coverage": {"populated_bucket_count": 2},
        }
        history = [
            {
                "calibrated_brier_score": 0.10,
                "calibrated_ece": 0.07,
                "n_events": 10,
                "stratification_coverage": {"populated_bucket_count": 3},
            },
            {
                "calibrated_brier_score": 0.12,
                "calibrated_ece": 0.09,
                "n_events": 9,
                "stratification_coverage": {"populated_bucket_count": 3},
            },
        ]

        degradations, baseline = assess_measurement_shadow_degradations(
            current,
            history,
            thresholds=thresholds,
        )

        assert baseline["available"] is True
        assert baseline["effective_thresholds"]["max_calibrated_brier_score"] == 0.16
        assert baseline["effective_thresholds"]["max_calibrated_ece"] == 0.12
        assert baseline["history_tightened_metrics"] == ["calibrated_brier_score", "calibrated_ece"]
        threshold_rows = {row["metric"]: row for row in degradations if row["code"].endswith("ABOVE_THRESHOLD")}
        assert threshold_rows["calibrated_brier_score"]["basis"] == "history_tightened_threshold"
        assert threshold_rows["calibrated_brier_score"]["threshold_value"] == 0.16
        assert threshold_rows["calibrated_ece"]["basis"] == "history_tightened_threshold"
        assert threshold_rows["calibrated_ece"]["threshold_value"] == 0.12

    def test_shadow_degradations_detect_calibrated_absolute_thresholds(self) -> None:
        thresholds = MeasurementShadowThresholds(
            max_brier_score=0.60,
            max_log_score=1.20,
            max_calibrated_brier_score=0.20,
            max_calibrated_ece=0.10,
            min_scoring_events=1,
            # legacy: keep calibrated-threshold eligibility at 1 event so this
            # fixture (n_events=6) continues to trigger ABOVE_THRESHOLD rows.
            min_events_for_calibrated_thresholds=1,
            min_populated_stratification_buckets=1,
            min_history_runs=2,
            max_brier_regression_abs=0.05,
            max_log_regression_abs=0.10,
            max_calibrated_brier_regression_abs=0.05,
            max_calibrated_ece_regression_abs=0.05,
            min_event_coverage_ratio=0.60,
            min_stratification_coverage_ratio=0.60,
        )
        current = {
            "brier_score": 0.18,
            "log_score": 0.31,
            "calibrated_brier_score": 0.27,
            "calibrated_ece": 0.16,
            "n_events": 6,
            "stratification_coverage": {"populated_bucket_count": 2},
        }

        degradations, baseline = assess_measurement_shadow_degradations(
            current,
            [],
            thresholds=thresholds,
        )

        assert baseline["available"] is False
        codes = {row["code"] for row in degradations}
        assert codes == {
            "MEASUREMENT_CALIBRATED_BRIER_ABOVE_THRESHOLD",
            "MEASUREMENT_CALIBRATED_ECE_ABOVE_THRESHOLD",
        }

    def test_shadow_degradations_apply_calibrated_thresholds_using_scoring_event_floor(self) -> None:
        thresholds = MeasurementShadowThresholds(
            max_calibrated_brier_score=0.20,
            max_calibrated_ece=0.10,
            min_scoring_events=1,
            # legacy: this test predates the calibrated-threshold eligibility
            # floor; pin to 1 event so n_events=1 still trips the gate.
            min_events_for_calibrated_thresholds=1,
            min_history_runs=5,
        )

        degradations, baseline = assess_measurement_shadow_degradations(
            {
                "calibrated_brier_score": 0.27,
                "calibrated_ece": 0.16,
                "n_events": 1,
                "stratification_coverage": {"populated_bucket_count": 2},
            },
            [],
            thresholds=thresholds,
        )

        assert baseline["available"] is False
        codes = {row["code"] for row in degradations}
        assert codes == {
            "MEASUREMENT_CALIBRATED_BRIER_ABOVE_THRESHOLD",
            "MEASUREMENT_CALIBRATED_ECE_ABOVE_THRESHOLD",
        }

    def test_shadow_degradations_detect_historical_regressions(self) -> None:
        thresholds = MeasurementShadowThresholds(
            max_brier_score=0.60,
            max_log_score=1.20,
            max_calibrated_brier_score=0.60,
            max_calibrated_ece=0.30,
            min_scoring_events=1,
            # legacy: keep calibrated-threshold eligibility at 1 event so this
            # fixture (n_events=3) still emits ABOVE_THRESHOLD codes.
            min_events_for_calibrated_thresholds=1,
            min_populated_stratification_buckets=1,
            min_history_runs=2,
            max_brier_regression_abs=0.05,
            max_log_regression_abs=0.10,
            max_calibrated_brier_regression_abs=0.05,
            max_calibrated_ece_regression_abs=0.10,
            min_event_coverage_ratio=0.60,
            min_stratification_coverage_ratio=0.60,
        )
        current = {
            "brier_score": 0.31,
            "log_score": 0.74,
            "calibrated_brier_score": 0.25,
            "calibrated_ece": 0.24,
            "n_events": 3,
            "stratification_coverage": {"populated_bucket_count": 1},
        }
        history = [
            {
                "brier_score": 0.11,
                "log_score": 0.33,
                "calibrated_brier_score": 0.09,
                "calibrated_ece": 0.07,
                "n_events": 10,
                "stratification_coverage": {"populated_bucket_count": 3},
            },
            {
                "brier_score": 0.13,
                "log_score": 0.35,
                "calibrated_brier_score": 0.11,
                "calibrated_ece": 0.09,
                "n_events": 8,
                "stratification_coverage": {"populated_bucket_count": 3},
            },
        ]

        degradations, baseline = assess_measurement_shadow_degradations(
            current,
            history,
            thresholds=thresholds,
        )

        assert baseline["available"] is True
        codes = {row["code"] for row in degradations}
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

    def test_shadow_degradations_detect_low_coverage_floors(self) -> None:
        thresholds = MeasurementShadowThresholds(
            min_scoring_events=5,
            min_populated_stratification_buckets=2,
            min_history_runs=2,
        )

        degradations, baseline = assess_measurement_shadow_degradations(
            {
                "n_events": 3,
                "stratification_coverage": {"populated_bucket_count": 1},
            },
            [],
            thresholds=thresholds,
        )

        assert baseline["available"] is False
        codes = {row["code"] for row in degradations}
        assert codes == {
            "MEASUREMENT_EVENT_COVERAGE_LOW",
            "MEASUREMENT_STRATIFICATION_COVERAGE_LOW",
        }

    def test_calibrated_thresholds_skipped_below_platt_floor_default(self) -> None:
        # Default eligibility floor is 30 events. (The Platt-scaler fitting
        # minimum smc_core.scoring._MIN_PLATT_EVENTS is 20; the floor adds a
        # margin on top — see MeasurementShadowThresholds.) Below the Platt
        # minimum the calibration code path falls back to beta_bin and emits
        # warnings; calibrated_ece is statistically meaningless (e.g. n=1
        # with positive_rate=0 yields 0.333333), so the ABOVE_THRESHOLD
        # hard-blocks must not fire.
        thresholds = MeasurementShadowThresholds()  # all defaults
        degradations, baseline = assess_measurement_shadow_degradations(
            {
                "brier_score": 0.38,
                "log_score": 0.97,
                "calibrated_brier_score": 0.11,
                # Constructed degenerate example: n=1 with positive_rate=0
                # trivially yields ECE = 1/3 — NOT the incident value from
                # the 2026-06-10 failing runs (that was n=20, see
                # test_calibrated_thresholds_skipped_at_platt_minimum_regression).
                "calibrated_ece": 0.333333,
                "n_events": 1,
                "stratification_coverage": {"populated_bucket_count": 0},
            },
            [],
            thresholds=thresholds,
        )

        assert baseline["available"] is False
        codes = {row["code"] for row in degradations}
        # Sparse-data warnings still fire (advisory), but the calibrated
        # ABOVE_THRESHOLD hard-block codes do not.
        assert "MEASUREMENT_CALIBRATED_BRIER_ABOVE_THRESHOLD" not in codes
        assert "MEASUREMENT_CALIBRATED_ECE_ABOVE_THRESHOLD" not in codes
        # Stratification coverage gate still fires (advisory) — note that
        # MEASUREMENT_EVENT_COVERAGE_LOW does not, because the default
        # min_scoring_events=1 is met by the n_events=1 fixture.
        assert "MEASUREMENT_STRATIFICATION_COVERAGE_LOW" in codes

    def test_calibrated_thresholds_apply_at_or_above_platt_floor_default(self) -> None:
        # At/above the eligibility floor (n_events=30) the calibrated
        # ABOVE_THRESHOLD hard-blocks fire as before.
        thresholds = MeasurementShadowThresholds()
        degradations, baseline = assess_measurement_shadow_degradations(
            {
                "brier_score": 0.25,
                "log_score": 0.50,
                "calibrated_brier_score": 0.70,  # > 0.60 default
                "calibrated_ece": 0.40,           # > 0.30 default
                "n_events": 30,
                "stratification_coverage": {"populated_bucket_count": 3},
            },
            [],
            thresholds=thresholds,
        )
        codes = {row["code"] for row in degradations}
        assert "MEASUREMENT_CALIBRATED_BRIER_ABOVE_THRESHOLD" in codes
        assert "MEASUREMENT_CALIBRATED_ECE_ABOVE_THRESHOLD" in codes
        assert baseline["calibrated_thresholds_eligible"] is True

    def test_calibrated_thresholds_skipped_at_platt_minimum_regression(self) -> None:
        # Regression for the 2026-06-10 incident: PG sat at exactly n=20 (the
        # Platt fitting minimum) with calibrated_ece 0.331 vs the 0.30 ceiling
        # and hard-failed three consecutive smc-library-refresh runs. At the
        # bare fitting minimum ECE sampling noise (~±0.15) dwarfs the
        # threshold, so the hard-blocks must stay suppressed until the
        # 30-event eligibility floor is reached.
        thresholds = MeasurementShadowThresholds()
        degradations, baseline = assess_measurement_shadow_degradations(
            {
                "brier_score": 0.25,
                "log_score": 0.50,
                "calibrated_brier_score": 0.11,
                "calibrated_ece": 0.331385,  # the failing-run PG 5m value
                "n_events": 20,
                "stratification_coverage": {"populated_bucket_count": 3},
            },
            [],
            thresholds=thresholds,
        )
        codes = {row["code"] for row in degradations}
        assert "MEASUREMENT_CALIBRATED_ECE_ABOVE_THRESHOLD" not in codes
        assert "MEASUREMENT_CALIBRATED_BRIER_ABOVE_THRESHOLD" not in codes
        # The suppression must be observable in the baseline payload so gate
        # reports show why the breach did not fire.
        assert baseline["calibrated_thresholds_eligible"] is False
        assert baseline["calibrated_thresholds_floor"] == 30

    def test_calibrated_thresholds_skipped_just_below_floor_default(self) -> None:
        # Upper edge of the suppression window: n=29 (one below the floor)
        # must still suppress; n=30 fires (covered by
        # test_calibrated_thresholds_apply_at_or_above_platt_floor_default).
        thresholds = MeasurementShadowThresholds()
        degradations, baseline = assess_measurement_shadow_degradations(
            {
                "calibrated_brier_score": 0.70,  # > 0.60 default
                "calibrated_ece": 0.40,  # > 0.30 default
                "n_events": 29,
                "stratification_coverage": {"populated_bucket_count": 3},
            },
            [],
            thresholds=thresholds,
        )
        codes = {row["code"] for row in degradations}
        assert "MEASUREMENT_CALIBRATED_ECE_ABOVE_THRESHOLD" not in codes
        assert "MEASUREMENT_CALIBRATED_BRIER_ABOVE_THRESHOLD" not in codes
        assert baseline["calibrated_thresholds_eligible"] is False

    def test_ece_breach_at_floor_carries_recalibration_required_signal(self) -> None:
        # PG observation follow-up (#2693): an ECE breach AT/ABOVE the
        # eligibility floor is by construction not small-sample noise (that
        # regime is the suppressed n<floor band) — it must carry an explicit
        # RECALIBRATION_REQUIRED marker so the correct operator response
        # (recalibrate) is machine-distinguishable from the suppressed
        # small-sample case, and nobody reaches for another floor bump.
        thresholds = MeasurementShadowThresholds()
        degradations, baseline = assess_measurement_shadow_degradations(
            {
                "calibrated_brier_score": 0.11,
                "calibrated_ece": 0.331385,  # PG-like incident value, now at n=30
                "n_events": 30,
                "stratification_coverage": {"populated_bucket_count": 3},
            },
            [],
            thresholds=thresholds,
        )
        assert baseline["calibrated_thresholds_eligible"] is True
        ece_rows = [
            row
            for row in degradations
            if row["code"] == "MEASUREMENT_CALIBRATED_ECE_ABOVE_THRESHOLD"
        ]
        assert len(ece_rows) == 1
        row = ece_rows[0]
        assert row["recalibration_required"] is True
        assert row["recommended_action"] == "recalibrate"
        assert "RECALIBRATION_REQUIRED" in row["detail"]
        # The detail must name both n_events and the floor so the report is
        # self-explanatory without cross-referencing the thresholds dataclass.
        assert "n_events=30" in row["detail"]
        assert str(thresholds.min_events_for_calibrated_thresholds) in row["detail"]

    def test_recalibration_marker_is_scoped_to_the_ece_degradation(self) -> None:
        # The marker is an ECE-specific signal; other degradation rows (e.g.
        # the calibrated-Brier breach firing in the same assessment) must not
        # carry it.
        thresholds = MeasurementShadowThresholds()
        degradations, _baseline = assess_measurement_shadow_degradations(
            {
                "calibrated_brier_score": 0.70,  # > 0.60 default
                "calibrated_ece": 0.40,  # > 0.30 default
                "n_events": 30,
                "stratification_coverage": {"populated_bucket_count": 3},
            },
            [],
            thresholds=thresholds,
        )
        by_code = {row["code"]: row for row in degradations}
        assert by_code["MEASUREMENT_CALIBRATED_ECE_ABOVE_THRESHOLD"]["recalibration_required"] is True
        assert "recalibration_required" not in by_code["MEASUREMENT_CALIBRATED_BRIER_ABOVE_THRESHOLD"]
        assert "recommended_action" not in by_code["MEASUREMENT_CALIBRATED_BRIER_ABOVE_THRESHOLD"]


class TestContextualCalibrationGovernance:
    def test_recommend_contextual_calibration_reports_missing_dimensions(self) -> None:
        recommendation = recommend_contextual_calibration(
            {
                "n_events": 12,
                "contextual_calibration": {"dimensions_present": ["session"]},
            }
        )

        assert recommendation["available"] is False
        assert recommendation["reason"] == "no_contextual_calibration_dimensions"
        assert recommendation["candidate_dimensions"] == []
        assert recommendation["eligible_dimensions"] == []

    def test_recommend_contextual_calibration_prefers_consensus_dimension(self) -> None:
        recommendation = recommend_contextual_calibration(
            {
                "n_events": 18,
                "contextual_calibration": {
                    "session": {
                        "n_events": 18,
                        "covered_events": 18,
                        "coverage_ratio": 1.0,
                        "populated_groups": 2,
                        "delta_brier_score": 0.02,
                        "delta_ece": 0.03,
                        "adjusted_brier_score": 0.11,
                        "adjusted_ece": 0.08,
                        "fallback_event_count": 0,
                    },
                    "htf_bias": {
                        "n_events": 18,
                        "covered_events": 18,
                        "coverage_ratio": 1.0,
                        "populated_groups": 2,
                        "delta_brier_score": 0.014,
                        "delta_ece": 0.02,
                        "adjusted_brier_score": 0.13,
                        "adjusted_ece": 0.1,
                        "fallback_event_count": 0,
                    },
                    "vol_regime": {
                        "n_events": 18,
                        "covered_events": 18,
                        "coverage_ratio": 1.0,
                        "populated_groups": 3,
                        "delta_brier_score": 0.016,
                        "delta_ece": 0.022,
                        "adjusted_brier_score": 0.12,
                        "adjusted_ece": 0.09,
                        "fallback_event_count": 0,
                    },
                },
            },
            policy=ContextualCalibrationRecommendationPolicy(),
        )

        assert recommendation["available"] is True
        assert recommendation["recommended_dimension"] == "session"
        assert recommendation["basis"] == "metric_consensus"
        assert recommendation["metric_consensus"] is True

    def test_recommend_contextual_calibration_rejects_ineligible_dimensions(self) -> None:
        recommendation = recommend_contextual_calibration(
            {
                "n_events": 12,
                "contextual_calibration": {
                    "session": {
                        "n_events": 12,
                        "covered_events": 5,
                        "coverage_ratio": 0.416667,
                        "populated_groups": 1,
                        "delta_brier_score": 0.0005,
                        "delta_ece": 0.001,
                        "adjusted_brier_score": 0.18,
                        "adjusted_ece": 0.12,
                        "fallback_event_count": 7,
                    },
                    "htf_bias": {
                        "n_events": 12,
                        "covered_events": 12,
                        "coverage_ratio": 1.0,
                        "populated_groups": 2,
                        "delta_brier_score": 0.0002,
                        "delta_ece": 0.0004,
                        "adjusted_brier_score": 0.17,
                        "adjusted_ece": 0.11,
                        "fallback_event_count": 0,
                    },
                },
            },
            policy=ContextualCalibrationRecommendationPolicy(),
        )

        assert recommendation["available"] is False
        assert recommendation["reason"] == "no_dimension_met_recommendation_policy"
        assert recommendation["candidate_dimensions"] == ["htf_bias", "session"]
        assert recommendation["eligible_dimensions"] == []

    def test_contextual_calibration_promotion_requires_stable_history(self) -> None:
        template = {
            "n_events": 18,
            "contextual_calibration": {
                "session": {
                    "n_events": 18,
                    "covered_events": 18,
                    "coverage_ratio": 1.0,
                    "populated_groups": 2,
                    "delta_brier_score": 0.02,
                    "delta_ece": 0.03,
                    "adjusted_brier_score": 0.11,
                    "adjusted_ece": 0.08,
                    "fallback_event_count": 0,
                },
                "htf_bias": {
                    "n_events": 18,
                    "covered_events": 18,
                    "coverage_ratio": 1.0,
                    "populated_groups": 2,
                    "delta_brier_score": 0.014,
                    "delta_ece": 0.02,
                    "adjusted_brier_score": 0.13,
                    "adjusted_ece": 0.1,
                    "fallback_event_count": 0,
                },
            },
        }

        promotion = assess_contextual_calibration_promotion(
            template,
            [template, template],
            recommendation_policy=ContextualCalibrationRecommendationPolicy(),
            promotion_policy=ContextualCalibrationPromotionPolicy(),
        )

        assert promotion["available"] is True
        assert promotion["promotion_ready"] is True
        assert promotion["recommended_dimension"] == "session"
        assert promotion["recommended_run_ratio"] == 1.0
        assert promotion["reasons"] == []

    def test_contextual_calibration_promotion_requires_current_recommendation(self) -> None:
        current = {
            "n_events": 12,
            "contextual_calibration": {
                "session": {
                    "n_events": 12,
                    "covered_events": 4,
                    "coverage_ratio": 0.333333,
                    "populated_groups": 1,
                    "delta_brier_score": 0.0004,
                    "delta_ece": 0.0005,
                    "adjusted_brier_score": 0.18,
                    "adjusted_ece": 0.12,
                    "fallback_event_count": 8,
                },
            },
        }
        history = [
            {
                "n_events": 18,
                "contextual_calibration": {
                    "session": {
                        "n_events": 18,
                        "covered_events": 18,
                        "coverage_ratio": 1.0,
                        "populated_groups": 2,
                        "delta_brier_score": 0.02,
                        "delta_ece": 0.03,
                        "adjusted_brier_score": 0.11,
                        "adjusted_ece": 0.08,
                        "fallback_event_count": 0,
                    },
                    "htf_bias": {
                        "n_events": 18,
                        "covered_events": 18,
                        "coverage_ratio": 1.0,
                        "populated_groups": 2,
                        "delta_brier_score": 0.015,
                        "delta_ece": 0.02,
                        "adjusted_brier_score": 0.13,
                        "adjusted_ece": 0.1,
                        "fallback_event_count": 0,
                    },
                },
            }
        ]

        promotion = assess_contextual_calibration_promotion(
            current,
            history,
            recommendation_policy=ContextualCalibrationRecommendationPolicy(),
            promotion_policy=ContextualCalibrationPromotionPolicy(
                min_history_runs=1,
                min_recommended_run_ratio=0.5,
                require_metric_consensus=False,
            ),
        )

        assert promotion["available"] is False
        assert promotion["promotion_ready"] is False
        assert promotion["recommended_dimension"] is None
        assert promotion["reasons"] == ["current_run_has_no_contextual_recommendation"]

    def test_contextual_calibration_promotion_detects_unstable_history(self) -> None:
        def _entry(preferred_dimension: str) -> dict[str, Any]:
            if preferred_dimension == "session":
                preferred_scores = (0.11, 0.08)
                alternate_scores = (0.13, 0.1)
            else:
                preferred_scores = (0.11, 0.08)
                alternate_scores = (0.13, 0.1)

            return {
                "n_events": 18,
                "contextual_calibration": {
                    preferred_dimension: {
                        "n_events": 18,
                        "covered_events": 18,
                        "coverage_ratio": 1.0,
                        "populated_groups": 2,
                        "delta_brier_score": 0.02,
                        "delta_ece": 0.03,
                        "adjusted_brier_score": preferred_scores[0],
                        "adjusted_ece": preferred_scores[1],
                        "fallback_event_count": 0,
                    },
                    ("htf_bias" if preferred_dimension == "session" else "session"): {
                        "n_events": 18,
                        "covered_events": 18,
                        "coverage_ratio": 1.0,
                        "populated_groups": 2,
                        "delta_brier_score": 0.015,
                        "delta_ece": 0.02,
                        "adjusted_brier_score": alternate_scores[0],
                        "adjusted_ece": alternate_scores[1],
                        "fallback_event_count": 0,
                    },
                },
            }

        promotion = assess_contextual_calibration_promotion(
            _entry("session"),
            [_entry("htf_bias"), _entry("htf_bias")],
            recommendation_policy=ContextualCalibrationRecommendationPolicy(),
            promotion_policy=ContextualCalibrationPromotionPolicy(),
        )

        assert promotion["available"] is True
        assert promotion["promotion_ready"] is False
        assert promotion["recommended_dimension"] == "session"
        assert promotion["recommended_run_ratio"] == pytest.approx(1.0 / 3.0, rel=0.0, abs=1e-6)
        assert promotion["reasons"] == ["recommended_dimension_not_stable_across_history"]


# ---------------------------------------------------------------------------
# Evidence coverage expectations
# ---------------------------------------------------------------------------

class TestEvidenceCoverage:
    def test_default_symbols_satisfy_coverage(self) -> None:
        assert len(RELEASE_REFERENCE_SYMBOLS) >= EVIDENCE_MIN_SYMBOL_COVERAGE

    def test_default_timeframes_satisfy_coverage(self) -> None:
        assert len(RELEASE_REFERENCE_TIMEFRAMES) >= EVIDENCE_MIN_TIMEFRAME_COVERAGE


# ---------------------------------------------------------------------------
# Hard-blocking measurement degradation classification (WP5)
# ---------------------------------------------------------------------------

class TestHardBlockingMeasurementDegradations:
    def test_hard_blocking_codes_are_defined(self) -> None:
        from smc_integration.release_policy import HARD_BLOCKING_DEGRADATION_CODES
        assert "MEASUREMENT_CALIBRATED_BRIER_ABOVE_THRESHOLD" in HARD_BLOCKING_DEGRADATION_CODES
        assert "MEASUREMENT_CALIBRATED_BRIER_REGRESSION" in HARD_BLOCKING_DEGRADATION_CODES
        assert "MEASUREMENT_CALIBRATED_ECE_ABOVE_THRESHOLD" in HARD_BLOCKING_DEGRADATION_CODES
        # MEASUREMENT_EVENT_COVERAGE_LOW was removed to avoid bootstrap deadlock
        assert "MEASUREMENT_EVENT_COVERAGE_LOW" not in HARD_BLOCKING_DEGRADATION_CODES
        assert len(HARD_BLOCKING_DEGRADATION_CODES) == 3

    def test_classify_separates_hard_from_advisory(self) -> None:
        from smc_integration.release_policy import classify_measurement_degradation_severity
        degradations = [
            {"code": "MEASUREMENT_CALIBRATED_BRIER_ABOVE_THRESHOLD", "detail": "hard"},
            {"code": "MEASUREMENT_CALIBRATED_BRIER_REGRESSION", "detail": "hard"},
            {"code": "MEASUREMENT_BRIER_REGRESSION", "detail": "advisory"},
            {"code": "MEASUREMENT_EVENT_COVERAGE_LOW", "detail": "advisory"},
            {"code": "MEASUREMENT_LOG_SCORE_REGRESSION", "detail": "advisory"},
        ]
        hard, advisory = classify_measurement_degradation_severity(degradations)
        assert len(hard) == 2
        assert len(advisory) == 3
        assert all(d["detail"] == "hard" for d in hard)
        assert all(d["detail"] == "advisory" for d in advisory)

    def test_classify_empty_returns_empty(self) -> None:
        from smc_integration.release_policy import classify_measurement_degradation_severity
        hard, advisory = classify_measurement_degradation_severity([])
        assert hard == []
        assert advisory == []

    def test_classify_all_advisory(self) -> None:
        from smc_integration.release_policy import classify_measurement_degradation_severity
        degradations = [
            {"code": "MEASUREMENT_BRIER_REGRESSION"},
            {"code": "MEASUREMENT_STRATIFICATION_COVERAGE_REGRESSION"},
        ]
        hard, advisory = classify_measurement_degradation_severity(degradations)
        assert hard == []
        assert len(advisory) == 2

    def test_hard_blocking_calibrated_brier_triggers_gate_fail(self) -> None:
        thresholds = MeasurementShadowThresholds(
            max_calibrated_brier_score=0.30,
            min_scoring_events=1,
            # legacy: keep calibrated-threshold eligibility at 1 event so the
            # n_events=5 fixture still trips the hard-block ABOVE_THRESHOLD.
            min_events_for_calibrated_thresholds=1,
        )
        current = {
            "brier_score": 0.25,
            "log_score": 0.50,
            "calibrated_brier_score": 0.40,
            "calibrated_ece": 0.10,
            "n_events": 5,
            "stratification_coverage": {"populated_bucket_count": 3},
        }
        degradations, _ = assess_measurement_shadow_degradations(
            current, [], thresholds=thresholds
        )
        from smc_integration.release_policy import classify_measurement_degradation_severity
        hard, _ = classify_measurement_degradation_severity(degradations)
        assert len(hard) >= 1
        assert any(d["code"] == "MEASUREMENT_CALIBRATED_BRIER_ABOVE_THRESHOLD" for d in hard)

    def test_advisory_regression_does_not_hard_block(self) -> None:
        from smc_integration.release_policy import classify_measurement_degradation_severity
        degradations = [
            {"code": "MEASUREMENT_BRIER_REGRESSION", "detail": "regressed"},
            {"code": "MEASUREMENT_LOG_SCORE_REGRESSION", "detail": "regressed"},
            {"code": "MEASUREMENT_CALIBRATED_ECE_REGRESSION", "detail": "regressed"},
            {"code": "MEASUREMENT_EVENT_COVERAGE_REGRESSION", "detail": "regressed"},
            {"code": "MEASUREMENT_STRATIFICATION_COVERAGE_REGRESSION", "detail": "regressed"},
            {"code": "MEASUREMENT_STRATIFICATION_COVERAGE_LOW", "detail": "low"},
        ]
        hard, advisory = classify_measurement_degradation_severity(degradations)
        assert hard == []
        assert len(advisory) == 6

    def test_promoted_hard_blocking_codes_trigger_gate_fail(self) -> None:
        from smc_integration.release_policy import classify_measurement_degradation_severity
        degradations = [
            {"code": "MEASUREMENT_CALIBRATED_BRIER_REGRESSION", "detail": "regressed"},
            {"code": "MEASUREMENT_CALIBRATED_ECE_ABOVE_THRESHOLD", "detail": "threshold"},
        ]
        hard, advisory = classify_measurement_degradation_severity(degradations)
        assert len(hard) == 2
        assert advisory == []
        assert {d["code"] for d in hard} == {
            "MEASUREMENT_CALIBRATED_BRIER_REGRESSION",
            "MEASUREMENT_CALIBRATED_ECE_ABOVE_THRESHOLD",
        }


# ---------------------------------------------------------------------------
# F-01: Governance enforcement — GovernanceStatus, GateGovernance, registry
# ---------------------------------------------------------------------------

class TestGovernanceEnforcementGaps:
    def test_governance_registry_is_valid(self) -> None:
        from smc_integration.release_policy import validate_gate_governance_registry
        errors = validate_gate_governance_registry()
        assert errors == [], f"Governance registry validation failed: {errors}"

    def test_all_known_codes_have_governance(self) -> None:
        from smc_integration.release_policy import GATE_GOVERNANCE_REGISTRY
        registered_codes = {g.code for g in GATE_GOVERNANCE_REGISTRY}
        # All codes that can appear from assess_measurement_shadow_degradations
        expected_codes = {
            "MEASUREMENT_CALIBRATED_BRIER_ABOVE_THRESHOLD",
            "MEASUREMENT_CALIBRATED_BRIER_REGRESSION",
            "MEASUREMENT_CALIBRATED_ECE_ABOVE_THRESHOLD",
            "MEASUREMENT_BRIER_ABOVE_THRESHOLD",
            "MEASUREMENT_LOG_SCORE_ABOVE_THRESHOLD",
            "MEASUREMENT_BRIER_REGRESSION",
            "MEASUREMENT_LOG_SCORE_REGRESSION",
            "MEASUREMENT_CALIBRATED_ECE_REGRESSION",
            "MEASUREMENT_EVENT_COVERAGE_LOW",
            "MEASUREMENT_STRATIFICATION_COVERAGE_LOW",
            "MEASUREMENT_EVENT_COVERAGE_REGRESSION",
            "MEASUREMENT_STRATIFICATION_COVERAGE_REGRESSION",
        }
        missing = expected_codes - registered_codes
        assert missing == set(), f"Codes missing governance: {missing}"

    def test_governance_status_enum_has_four_values(self) -> None:
        from smc_integration.release_policy import GovernanceStatus
        assert set(GovernanceStatus) == {
            GovernanceStatus.EXCLUDED,
            GovernanceStatus.SHADOW,
            GovernanceStatus.ADVISORY,
            GovernanceStatus.HARD_BLOCKING,
        }

    def test_invalid_status_rejected_by_enum(self) -> None:
        from smc_integration.release_policy import GovernanceStatus
        with pytest.raises(ValueError):
            GovernanceStatus("INVALID_STATUS")

    def test_hard_blocking_codes_consistent_with_frozenset(self) -> None:
        from smc_integration.release_policy import (
            GATE_GOVERNANCE_REGISTRY,
            HARD_BLOCKING_DEGRADATION_CODES,
            GovernanceStatus,
        )
        registry_hard = {
            g.code for g in GATE_GOVERNANCE_REGISTRY
            if g.promotion_state == GovernanceStatus.HARD_BLOCKING
        }
        assert registry_hard == HARD_BLOCKING_DEGRADATION_CODES

    def test_hard_blocking_gates_have_evidence_reference(self) -> None:
        from smc_integration.release_policy import GATE_GOVERNANCE_REGISTRY, GovernanceStatus
        for gate in GATE_GOVERNANCE_REGISTRY:
            if gate.promotion_state == GovernanceStatus.HARD_BLOCKING:
                assert gate.evidence_reference, f"{gate.code} missing evidence_reference"

    def test_hard_blocking_gates_have_minimum_baselines(self) -> None:
        from smc_integration.release_policy import GATE_GOVERNANCE_REGISTRY, GovernanceStatus
        for gate in GATE_GOVERNANCE_REGISTRY:
            if gate.promotion_state == GovernanceStatus.HARD_BLOCKING:
                assert gate.minimum_required_baselines >= 1, f"{gate.code} needs baselines >= 1"

    def test_all_gates_have_nonempty_promotion_reason(self) -> None:
        from smc_integration.release_policy import GATE_GOVERNANCE_REGISTRY
        for gate in GATE_GOVERNANCE_REGISTRY:
            assert gate.promotion_reason.strip(), f"{gate.code} has empty promotion_reason"

    def test_all_gates_have_nonempty_reviewer(self) -> None:
        from smc_integration.release_policy import GATE_GOVERNANCE_REGISTRY
        for gate in GATE_GOVERNANCE_REGISTRY:
            assert gate.reviewer.strip(), f"{gate.code} has empty reviewer"

    def test_no_duplicate_codes_in_registry(self) -> None:
        from smc_integration.release_policy import GATE_GOVERNANCE_REGISTRY
        codes = [g.code for g in GATE_GOVERNANCE_REGISTRY]
        assert len(codes) == len(set(codes)), "Duplicate codes in registry"

    def test_get_gate_governance_returns_entry(self) -> None:
        from smc_integration.release_policy import GovernanceStatus, get_gate_governance
        entry = get_gate_governance("MEASUREMENT_CALIBRATED_BRIER_ABOVE_THRESHOLD")
        assert entry is not None
        assert entry.promotion_state == GovernanceStatus.HARD_BLOCKING

    def test_get_gate_governance_returns_none_for_unknown(self) -> None:
        from smc_integration.release_policy import get_gate_governance
        assert get_gate_governance("UNKNOWN_CODE") is None

    def test_shadow_not_in_hard_blocking(self) -> None:
        from smc_integration.release_policy import (
            GATE_GOVERNANCE_REGISTRY,
            HARD_BLOCKING_DEGRADATION_CODES,
            GovernanceStatus,
        )
        shadow_codes = {
            g.code for g in GATE_GOVERNANCE_REGISTRY
            if g.promotion_state == GovernanceStatus.SHADOW
        }
        overlap = shadow_codes & HARD_BLOCKING_DEGRADATION_CODES
        assert overlap == set(), f"SHADOW codes must not be in HARD_BLOCKING_DEGRADATION_CODES: {overlap}"

    def test_excluded_not_in_hard_blocking(self) -> None:
        from smc_integration.release_policy import (
            GATE_GOVERNANCE_REGISTRY,
            HARD_BLOCKING_DEGRADATION_CODES,
            GovernanceStatus,
        )
        excluded_codes = {
            g.code for g in GATE_GOVERNANCE_REGISTRY
            if g.promotion_state == GovernanceStatus.EXCLUDED
        }
        overlap = excluded_codes & HARD_BLOCKING_DEGRADATION_CODES
        assert overlap == set(), f"EXCLUDED codes must not be in HARD_BLOCKING_DEGRADATION_CODES: {overlap}"


# ---------------------------------------------------------------------------
# Coverage-boost tests — targeted at uncovered lines
# ---------------------------------------------------------------------------


class TestValidateGovernanceRegistryErrors:
    """Cover lines 219-256: error branches in validate_gate_governance_registry."""

    def test_duplicate_code_detected(self, monkeypatch) -> None:
        from smc_integration.release_policy import (
            GateGovernance,
            GovernanceStatus,
            validate_gate_governance_registry,
        )
        dup_entry = GateGovernance(
            code="MEASUREMENT_BRIER_ABOVE_THRESHOLD",
            promotion_state=GovernanceStatus.ADVISORY,
            promotion_reason="duplicate entry for testing.",
            reviewer="owner",
            minimum_required_baselines=0,
        )
        import smc_integration.release_policy as rp_mod
        from smc_integration.release_policy import GATE_GOVERNANCE_REGISTRY
        extended = (*GATE_GOVERNANCE_REGISTRY, dup_entry)
        monkeypatch.setattr(rp_mod, "GATE_GOVERNANCE_REGISTRY", extended)
        errors = validate_gate_governance_registry()
        assert any("duplicate" in e for e in errors)

    def test_empty_reviewer_detected(self, monkeypatch) -> None:
        import smc_integration.release_policy as rp_mod
        from smc_integration.release_policy import (
            GateGovernance,
            GovernanceStatus,
            validate_gate_governance_registry,
        )
        bad_entry = GateGovernance(
            code="TEST_BAD_REVIEWER",
            promotion_state=GovernanceStatus.ADVISORY,
            promotion_reason="test reason",
            reviewer="  ",
            minimum_required_baselines=0,
        )
        monkeypatch.setattr(rp_mod, "GATE_GOVERNANCE_REGISTRY", (bad_entry,))
        monkeypatch.setattr(rp_mod, "HARD_BLOCKING_DEGRADATION_CODES", frozenset())
        errors = validate_gate_governance_registry()
        assert any("reviewer is empty" in e for e in errors)

    def test_empty_promotion_reason_detected(self, monkeypatch) -> None:
        import smc_integration.release_policy as rp_mod
        from smc_integration.release_policy import (
            GateGovernance,
            GovernanceStatus,
            validate_gate_governance_registry,
        )
        bad_entry = GateGovernance(
            code="TEST_BAD_REASON",
            promotion_state=GovernanceStatus.ADVISORY,
            promotion_reason="  ",
            reviewer="owner",
            minimum_required_baselines=0,
        )
        monkeypatch.setattr(rp_mod, "GATE_GOVERNANCE_REGISTRY", (bad_entry,))
        monkeypatch.setattr(rp_mod, "HARD_BLOCKING_DEGRADATION_CODES", frozenset())
        errors = validate_gate_governance_registry()
        assert any("promotion_reason is empty" in e for e in errors)

    def test_hard_blocking_without_baselines_detected(self, monkeypatch) -> None:
        import smc_integration.release_policy as rp_mod
        from smc_integration.release_policy import (
            GateGovernance,
            GovernanceStatus,
            validate_gate_governance_registry,
        )
        bad_entry = GateGovernance(
            code="TEST_NO_BASELINES",
            promotion_state=GovernanceStatus.HARD_BLOCKING,
            promotion_reason="test reason",
            reviewer="owner",
            minimum_required_baselines=0,
            evidence_reference="some.md",
        )
        monkeypatch.setattr(rp_mod, "GATE_GOVERNANCE_REGISTRY", (bad_entry,))
        monkeypatch.setattr(rp_mod, "HARD_BLOCKING_DEGRADATION_CODES", frozenset({"TEST_NO_BASELINES"}))
        errors = validate_gate_governance_registry()
        assert any("minimum_required_baselines" in e for e in errors)

    def test_hard_blocking_without_evidence_detected(self, monkeypatch) -> None:
        import smc_integration.release_policy as rp_mod
        from smc_integration.release_policy import (
            GateGovernance,
            GovernanceStatus,
            validate_gate_governance_registry,
        )
        bad_entry = GateGovernance(
            code="TEST_NO_EVIDENCE",
            promotion_state=GovernanceStatus.HARD_BLOCKING,
            promotion_reason="test reason",
            reviewer="owner",
            minimum_required_baselines=2,
            evidence_reference=None,
        )
        monkeypatch.setattr(rp_mod, "GATE_GOVERNANCE_REGISTRY", (bad_entry,))
        monkeypatch.setattr(rp_mod, "HARD_BLOCKING_DEGRADATION_CODES", frozenset({"TEST_NO_EVIDENCE"}))
        errors = validate_gate_governance_registry()
        assert any("evidence_reference" in e for e in errors)

    def test_cross_check_mismatch_detected(self, monkeypatch) -> None:
        import smc_integration.release_policy as rp_mod
        from smc_integration.release_policy import (
            GateGovernance,
            GovernanceStatus,
            validate_gate_governance_registry,
        )
        entry = GateGovernance(
            code="TEST_CROSS",
            promotion_state=GovernanceStatus.HARD_BLOCKING,
            promotion_reason="test reason",
            reviewer="owner",
            minimum_required_baselines=2,
            evidence_reference="doc.md",
        )
        monkeypatch.setattr(rp_mod, "GATE_GOVERNANCE_REGISTRY", (entry,))
        # frozenset has a different code → mismatch in both directions
        monkeypatch.setattr(rp_mod, "HARD_BLOCKING_DEGRADATION_CODES", frozenset({"OTHER_CODE"}))
        errors = validate_gate_governance_registry()
        assert any("HARD_BLOCKING in registry but not" in e for e in errors)
        assert any("in HARD_BLOCKING_DEGRADATION_CODES but not" in e for e in errors)


class TestClassifyArtifactDrift:
    """Cover lines 355-359."""

    def test_known_restore_path(self) -> None:
        from smc_integration.release_policy import classify_artifact_drift
        result = classify_artifact_drift("artifacts/databento_volatility_cache/foo.json")
        assert result == "restore_on_commit"

    def test_known_stage_only_path(self) -> None:
        from smc_integration.release_policy import classify_artifact_drift
        result = classify_artifact_drift("pine/generated/lib.pine")
        assert result == "stage_only"

    def test_unknown_path_returns_none(self) -> None:
        from smc_integration.release_policy import classify_artifact_drift
        assert classify_artifact_drift("random/path.txt") is None

    def test_exact_match(self) -> None:
        from smc_integration.release_policy import classify_artifact_drift
        result = classify_artifact_drift("SMC_Core_Engine.pine")
        assert result == "stage_only"


class TestFiniteAndIntMetricEdges:
    """Cover lines 463-464, 470, 495, 505."""

    def test_finite_metric_nan_returns_none(self) -> None:
        from smc_integration.release_policy import _finite_metric
        assert _finite_metric(float("nan")) is None

    def test_finite_metric_inf_returns_none(self) -> None:
        from smc_integration.release_policy import _finite_metric
        assert _finite_metric(float("inf")) is None

    def test_int_metric_invalid_returns_none(self) -> None:
        from smc_integration.release_policy import _int_metric
        assert _int_metric("not_a_number") is None

    def test_median_metric_empty_returns_none(self) -> None:
        from smc_integration.release_policy import _median_metric
        assert _median_metric([]) is None

    def test_optional_stripped_string_empty_returns_none(self) -> None:
        from smc_integration.release_policy import _optional_stripped_string
        assert _optional_stripped_string("  ") is None
        assert _optional_stripped_string(None) is None
        assert _optional_stripped_string("hello") == "hello"


class TestCoerceContextualDimensionsEdges:
    """Cover line 522: dimensions_present key but no dimensions dict."""

    def test_dimensions_present_without_dimensions_returns_empty(self) -> None:
        from smc_integration.release_policy import _coerce_contextual_calibration_dimensions
        result = _coerce_contextual_calibration_dimensions({"dimensions_present": True})
        assert result == {}


class TestBestContextualDimensionDirect:
    """Cover lines 567, 573: direct metric_name on raw dict."""

    def test_direct_value_on_raw(self) -> None:
        from smc_integration.release_policy import _best_contextual_dimension
        result = _best_contextual_dimension(
            {"best_dimension_by_adjusted_brier": "vol_regime"},
            {"vol_regime": {"adjusted_brier_score": 0.2}},
            metric_name="best_dimension_by_adjusted_brier",
        )
        assert result == "vol_regime"

    def test_iteration_fallback(self) -> None:
        from smc_integration.release_policy import _best_contextual_dimension
        result = _best_contextual_dimension(
            {},
            {
                "dim_a": {"adjusted_ece": 0.5},
                "dim_b": {"adjusted_ece": 0.2},
            },
            metric_name="best_dimension_by_adjusted_ece",
        )
        assert result == "dim_b"


class TestRawBrierAboveThreshold:
    """Cover line 812: MEASUREMENT_BRIER_ABOVE_THRESHOLD."""

    def test_raw_brier_above_threshold(self) -> None:
        thresholds = MeasurementShadowThresholds(
            max_brier_score=0.50,
            max_log_score=10.0,
            max_calibrated_brier_score=10.0,
            max_calibrated_ece=10.0,
            min_scoring_events=1,
            min_history_runs=99,
        )
        current = {
            "brier_score": 0.65,
            "n_events": 5,
            "stratification_coverage": {"populated_bucket_count": 2},
        }
        degradations, _baseline = assess_measurement_shadow_degradations(
            current, [], thresholds=thresholds,
        )
        codes = {d["code"] for d in degradations}
        assert "MEASUREMENT_BRIER_ABOVE_THRESHOLD" in codes


class TestCsvFromValues:
    """Cover lines 1032, 1034."""

    def test_dedup_and_strip(self) -> None:
        from smc_integration.release_policy import csv_from_values
        result = csv_from_values(["  a ", "b", "a", "  ", "c"])
        assert result == "a,b,c"

    def test_empty_values_skipped(self) -> None:
        from smc_integration.release_policy import csv_from_values
        assert csv_from_values(["", "  ", ""]) == ""


class TestResolveGitCommit:
    """Cover lines 1057, 1065-1066, 1068."""

    def test_env_sha_takes_precedence(self, monkeypatch) -> None:
        from smc_integration.release_policy import resolve_git_commit
        monkeypatch.setenv("GITHUB_SHA", "abc123")
        assert resolve_git_commit() == "abc123"

    def test_subprocess_exception_returns_none(self, monkeypatch) -> None:
        import subprocess

        from smc_integration.release_policy import resolve_git_commit
        monkeypatch.delenv("GITHUB_SHA", raising=False)
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(OSError("no git")))
        assert resolve_git_commit() is None

    def test_subprocess_nonzero_returns_none(self, monkeypatch) -> None:
        import subprocess as sp

        from smc_integration.release_policy import resolve_git_commit
        monkeypatch.delenv("GITHUB_SHA", raising=False)

        class FakeResult:
            returncode = 1
            stdout = ""
        monkeypatch.setattr(sp, "run", lambda *a, **kw: FakeResult())
        assert resolve_git_commit() is None

    def test_subprocess_empty_stdout_returns_none(self, monkeypatch) -> None:
        import subprocess as sp

        from smc_integration.release_policy import resolve_git_commit
        monkeypatch.delenv("GITHUB_SHA", raising=False)

        class FakeResult:
            returncode = 0
            stdout = "   "
        monkeypatch.setattr(sp, "run", lambda *a, **kw: FakeResult())
        assert resolve_git_commit() is None


class TestClassifyCodeBranches:
    """Cover lines 1149-1150, 1156, 1187, 1192, 1213."""

    def test_smoke_with_symbol_and_timeframe(self) -> None:
        results: list[dict[str, str]] = []

        def add_fn(reason: str, detail: str) -> None:
            results.append({"reason": reason, "detail": detail})

        from smc_integration.release_policy import _classify_code
        _classify_code("EMPTY_STRUCTURE_INPUT", {"symbol": "AAPL", "timeframe": "15m"}, add_fn)
        assert any(r["reason"] == REASON_SMOKE_FAILURE and "AAPL/15m" in r["detail"] for r in results)

    def test_missing_smoke_code(self) -> None:
        results: list[dict[str, str]] = []

        def add_fn(reason: str, detail: str) -> None:
            results.append({"reason": reason, "detail": detail})

        from smc_integration.release_policy import _classify_code
        _classify_code("MISSING_SMOKE_RESULT", {"symbol": "MSFT", "timeframe": "5m"}, add_fn)
        assert any(r["reason"] == REASON_SMOKE_FAILURE for r in results)

    def test_generic_missing_code(self) -> None:
        results: list[dict[str, str]] = []

        def add_fn(reason: str, detail: str) -> None:
            results.append({"reason": reason, "detail": detail})

        from smc_integration.release_policy import _classify_code
        _classify_code("MISSING_MANIFEST", {}, add_fn)
        assert any(r["reason"] == REASON_MISSING_ARTIFACT for r in results)

    def test_provider_failure_code(self) -> None:
        results: list[dict[str, str]] = []

        def add_fn(reason: str, detail: str) -> None:
            results.append({"reason": reason, "detail": detail})

        from smc_integration.release_policy import _classify_code
        _classify_code("BUNDLE_BUILD_FAILED", {}, add_fn)
        assert any(r["reason"] == REASON_PROVIDER_FAILURE for r in results)

    def test_refresh_code_classified_as_provider_failure(self) -> None:
        results: list[dict[str, str]] = []

        def add_fn(reason: str, detail: str) -> None:
            results.append({"reason": reason, "detail": detail})

        from smc_integration.release_policy import _classify_code
        _classify_code("REFRESH_FAILED", {}, add_fn)
        assert any(r["reason"] == REASON_PROVIDER_FAILURE for r in results)

    def test_empty_code_is_noop(self) -> None:
        results: list[dict[str, str]] = []
        from smc_integration.release_policy import _classify_code
        _classify_code("", {}, lambda r, d: results.append({"reason": r}))
        assert results == []

    def test_stale_code_with_symbol(self) -> None:
        """Cover line 1192: STALE branch with symbol."""
        results: list[dict[str, str]] = []

        def add_fn(reason: str, detail: str) -> None:
            results.append({"reason": reason, "detail": detail})

        from smc_integration.release_policy import _classify_code
        _classify_code("STALE_MANIFEST", {"symbol": "TSLA"}, add_fn)
        assert any(r["reason"] == REASON_STALE_DATA and "TSLA" in r["detail"] for r in results)

    def test_provider_code_with_symbol(self) -> None:
        """Cover line 1192 variant: PROVIDER with symbol."""
        results: list[dict[str, str]] = []

        def add_fn(reason: str, detail: str) -> None:
            results.append({"reason": reason, "detail": detail})

        from smc_integration.release_policy import _classify_code
        _classify_code("PROVIDER_FMP_TIMEOUT", {"symbol": "MSFT"}, add_fn)
        assert any(r["reason"] == REASON_PROVIDER_FAILURE for r in results)


class TestPopulatedBucketCountEdge:
    """Cover line 470: _populated_bucket_count with non-dict raw."""

    def test_non_dict_stratification_returns_none(self) -> None:
        from smc_integration.release_policy import _populated_bucket_count
        assert _populated_bucket_count({"stratification_coverage": "bad"}) is None


class TestCoerceDimensionsNonDictRaw:
    """Cover line 495: _coerce_contextual_calibration_dimensions with non-dict."""

    def test_non_dict_returns_empty(self) -> None:
        from smc_integration.release_policy import _coerce_contextual_calibration_dimensions
        assert _coerce_contextual_calibration_dimensions("not_a_dict") == {}

    def test_non_dict_item_skipped(self) -> None:
        """Cover line 505: non-dict item in dimensions skipped."""
        from smc_integration.release_policy import _coerce_contextual_calibration_dimensions
        result = _coerce_contextual_calibration_dimensions({
            "dimensions": {"good": {"brier": 0.1}, "bad": "not_a_dict"},
        })
        assert "good" in result
        assert "bad" not in result


class TestBestDimensionSkipNone:
    """Cover line 522: dimension with no metric value skipped."""

    def test_none_value_skipped(self) -> None:
        from smc_integration.release_policy import _best_contextual_dimension
        result = _best_contextual_dimension(
            None,
            {
                "dim_no_val": {"other_key": 42},
                "dim_with_val": {"adjusted_brier_score": 0.2},
            },
            metric_name="best_dimension_by_adjusted_brier",
        )
        assert result == "dim_with_val"


class TestRecommendContextualCoverageAndFallback:
    """Cover lines 567, 573: coverage_ratio fallback and fallback_event_count."""

    def test_coverage_ratio_fallback(self) -> None:
        from smc_integration.release_policy import recommend_contextual_calibration
        entry = {
            "n_events": 100,
            "contextual_calibration": {
                "dimensions": {
                    "vol_regime": {
                        "n_events": 100,
                        "covered_events": 80,
                        # no coverage_ratio → triggers line 567
                        "fallback_event_count": "bad",
                        # _int_metric("bad") → None → triggers line 573
                        "populated_groups": 5,
                        "delta_brier_score": 0.05,
                        "delta_ece": 0.03,
                        "adjusted_brier_score": 0.15,
                        "adjusted_ece": 0.10,
                    },
                },
            },
        }
        result = recommend_contextual_calibration(entry)
        # candidate_dimensions is a list of strings (dimension names)
        all_dims = result.get("candidate_dimensions", []) + result.get("eligible_dimensions", [])
        # eligible_dimensions may contain dicts with "dimension" key
        dim_names = [d["dimension"] if isinstance(d, dict) else d for d in all_dims]
        assert "vol_regime" in dim_names


class TestInvalidPromotionState:
    """Cover line 224: promotion_state that is not a GovernanceStatus."""

    def test_non_enum_promotion_state(self, monkeypatch) -> None:
        import types

        import smc_integration.release_policy as rp_mod
        from smc_integration.release_policy import validate_gate_governance_registry

        fake = types.SimpleNamespace(
            code="TEST_NON_ENUM",
            promotion_state="NOT_AN_ENUM",
            promotion_reason="valid reason",
            reviewer="owner",
            minimum_required_baselines=0,
            evidence_reference=None,
        )
        monkeypatch.setattr(rp_mod, "GATE_GOVERNANCE_REGISTRY", (fake,))
        monkeypatch.setattr(rp_mod, "HARD_BLOCKING_DEGRADATION_CODES", frozenset())
        errors = validate_gate_governance_registry()
        assert any("not a GovernanceStatus" in e for e in errors)


class TestDiagnoseGateDegradationsAndGateDetails:
    """Cover lines 1149-1150 (degradations_detected) and 1156 (non-dict gate details)."""

    def test_degradations_detected_scanned(self) -> None:
        report: dict[str, Any] = {
            "degradations_detected": [
                {"code": "MEASUREMENT_BRIER_ABOVE_THRESHOLD"},
            ],
            "reference_symbols": [f"S{i}" for i in range(EVIDENCE_MIN_SYMBOL_COVERAGE)],
            "reference_timeframes": [f"tf{i}" for i in range(EVIDENCE_MIN_TIMEFRAME_COVERAGE)],
        }
        reasons = diagnose_gate_failure(report)
        assert any(r["reason"] == REASON_MEASUREMENT_QUALITY for r in reasons)

    def test_gate_with_non_dict_details_skipped(self) -> None:
        report: dict[str, Any] = {
            "gates": [
                {"name": "bad_gate", "status": "fail", "details": "not_a_dict"},
            ],
            "reference_symbols": [f"S{i}" for i in range(EVIDENCE_MIN_SYMBOL_COVERAGE)],
            "reference_timeframes": [f"tf{i}" for i in range(EVIDENCE_MIN_TIMEFRAME_COVERAGE)],
        }
        reasons = diagnose_gate_failure(report)
        # Gate with non-dict details is simply skipped — no error, no crash
        assert isinstance(reasons, list)

def test_release_reference_timeframes_supported_by_price_action_engine() -> None:
    from scripts.explicit_structure_from_bars import _TIMEFRAME_TO_PANDAS_FREQ
    from scripts.smc_price_action_engine import canonical_timeframe
    from smc_integration.release_policy import RELEASE_REFERENCE_TIMEFRAMES

    for tf in RELEASE_REFERENCE_TIMEFRAMES:
        canonical = canonical_timeframe(tf)
        assert canonical in _TIMEFRAME_TO_PANDAS_FREQ, f"{tf} -> {canonical} missing in explicit_structure_from_bars _TIMEFRAME_TO_PANDAS_FREQ"

