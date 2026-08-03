from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from open_prep.pre_a0_mlflow import GovernanceValidationError, validate_bundle

ARTIFACT_ID = "de97b74e6c6f645a513ece01"
ARTIFACT_PATH = Path("services/a0_fast_detector/bootstrap/pre-a0-model.json")
REPORT_PATH = Path("services/a0_fast_detector/bootstrap/validation-report.json")
POLICY_PATH = Path("governance/pre_a0_promotion_policy.json")


def _copy_json(source: Path, target: Path) -> dict:
    payload = json.loads(source.read_text(encoding="utf-8"))
    target.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def test_bootstrap_artifact_is_candidate_but_not_shadow_eligible() -> None:
    bundle = validate_bundle(
        ARTIFACT_PATH,
        REPORT_PATH,
        POLICY_PATH,
        now=datetime(2026, 7, 18, tzinfo=UTC),
        expected_artifact_id=ARTIFACT_ID,
    )
    assert bundle.gates.identity_verified is True
    assert bundle.gates.evidence_linked is True
    assert bundle.gates.candidate_eligible is True
    assert bundle.gates.shadow_eligible is False
    assert bundle.gates.reasons == ("shadow_evaluation_missing",)


def test_content_tampering_blocks_candidate_promotion(tmp_path: Path) -> None:
    artifact_path = tmp_path / "pre-a0-model.json"
    artifact = _copy_json(ARTIFACT_PATH, artifact_path)
    artifact["model"]["intercept"] += 0.01
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    bundle = validate_bundle(
        artifact_path,
        REPORT_PATH,
        POLICY_PATH,
        now=datetime(2026, 7, 18, tzinfo=UTC),
    )
    assert bundle.gates.identity_verified is False
    assert bundle.gates.candidate_eligible is False
    with pytest.raises(GovernanceValidationError, match="artifact_identity_mismatch"):
        bundle.gates.require("candidate")


def test_expired_artifact_blocks_all_promotions() -> None:
    bundle = validate_bundle(
        ARTIFACT_PATH,
        REPORT_PATH,
        POLICY_PATH,
        # One day past the artifact's review_after (2026-11-01T18:14:43Z).
        now=datetime(2026, 11, 2, tzinfo=UTC),
    )
    assert bundle.gates.not_expired is False
    assert bundle.gates.candidate_eligible is False
    assert bundle.gates.shadow_eligible is False


def test_shadow_requires_artifact_and_evidence_flags(tmp_path: Path) -> None:
    original = validate_bundle(
        ARTIFACT_PATH,
        REPORT_PATH,
        POLICY_PATH,
        now=datetime(2026, 7, 18, tzinfo=UTC),
    )
    artifact_path = tmp_path / "pre-a0-model.json"
    report_path = tmp_path / "validation-report.json"
    artifact = _copy_json(ARTIFACT_PATH, artifact_path)
    report = _copy_json(REPORT_PATH, report_path)
    artifact["gates"]["shadow_evaluated"] = True
    report["shadow_gate_passed"] = True
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    report_path.write_text(json.dumps(report), encoding="utf-8")
    bundle = validate_bundle(
        artifact_path,
        report_path,
        POLICY_PATH,
        now=datetime(2026, 7, 18, tzinfo=UTC),
    )
    assert bundle.gates.candidate_eligible is True
    assert bundle.gates.shadow_eligible is True
    assert bundle.bundle_id != original.bundle_id
    bundle.gates.require("shadow")


# ---- lift-based AP gate (promotion policy v2) -----------------------------
#
# Why lift, not absolute AP: an absolute floor is base-rate-dependent. The old
# 0.8 was calibrated on the bootstrap eval (210 rows, 10 positives, base rate
# 4.76% -> 0.8 = 16.8x lift); on the live shadow distribution (base rate
# 0.51%) the same 0.8 would demand 156x lift — unreachable by construction.
# Monte Carlo over random rankings (seed 20260803, 2026-08-03): the null AP
# p99.9 at 287 positives is 1.76x base rate, so a 2.0x floor is above noise —
# but ONLY with enough positives (at 250 positives / base rate 0.5% the noise
# ceiling is 1.93x; at 100 positives it is 3.25x). The lift threshold and the
# positive-rows floor are therefore an inseparable pair.


def _bundle_with_metrics(tmp_path: Path, **metric_overrides) -> object:
    """Re-validate the real bundle with consistently edited metrics.

    Metrics are NOT part of the content-derived artifact id (identity =
    contract/schema/feature/split/model/calibration), so editing them in both
    files keeps identity verified and evidence linked — isolating the gate
    under test. A value of None deletes the metric.
    """
    artifact_path = tmp_path / "pre-a0-model.json"
    report_path = tmp_path / "validation-report.json"
    artifact = _copy_json(ARTIFACT_PATH, artifact_path)
    report = _copy_json(REPORT_PATH, report_path)
    for key, value in metric_overrides.items():
        if value is None:
            artifact["metrics"].pop(key, None)
            report["metrics"].pop(key, None)
            continue
        if key in artifact["metrics"]:
            artifact["metrics"][key] = value
        report["metrics"][key] = value
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return validate_bundle(
        artifact_path,
        report_path,
        POLICY_PATH,
        now=datetime(2026, 8, 3, tzinfo=UTC),
    )


def test_candidate_gate_blocks_when_lift_is_inside_the_noise_ceiling(tmp_path: Path) -> None:
    # 1.2x base rate sits inside the measured null p99.9 (1.76x at 287
    # positives) — statistically indistinguishable from a random ranking.
    base_rate = 0.005123627599750067
    bundle = _bundle_with_metrics(tmp_path, test_average_precision=1.2 * base_rate)
    assert bundle.gates.candidate_eligible is False
    assert "average_precision_lift_below_minimum" in bundle.gates.reasons


def test_candidate_gate_blocks_when_positive_rows_cannot_certify_the_lift(tmp_path: Path) -> None:
    # At 100 positives the noise ceiling (3.25x at base rate 0.5%) exceeds the
    # 2.0x threshold — the lift check would be testing noise, so it must not
    # certify regardless of the observed AP.
    bundle = _bundle_with_metrics(tmp_path, test_positive_rows=100)
    assert bundle.gates.candidate_eligible is False
    assert "test_positive_rows_below_minimum" in bundle.gates.reasons


def test_missing_base_rate_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(GovernanceValidationError, match="test_base_rate"):
        _bundle_with_metrics(tmp_path, test_base_rate=None)


def test_missing_positive_rows_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(GovernanceValidationError, match="test_positive_rows"):
        _bundle_with_metrics(tmp_path, test_positive_rows=None)


def test_v1_policy_contract_is_rejected(tmp_path: Path) -> None:
    # The v1 policy carried the absolute AP floor; a stale v1 file must fail
    # loudly instead of being reinterpreted under v2 semantics.
    policy_path = tmp_path / "policy.json"
    policy = _copy_json(POLICY_PATH, policy_path)
    policy["contract_version"] = "pre-a0-promotion-policy-v1"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(GovernanceValidationError, match="unsupported promotion policy contract"):
        validate_bundle(
            ARTIFACT_PATH,
            REPORT_PATH,
            policy_path,
            now=datetime(2026, 8, 3, tzinfo=UTC),
        )


def test_runtime_production_alias_is_not_available() -> None:
    bundle = validate_bundle(
        ARTIFACT_PATH,
        REPORT_PATH,
        POLICY_PATH,
        now=datetime(2026, 7, 18, tzinfo=UTC),
    )
    with pytest.raises(GovernanceValidationError, match="runtime promotion remains outside MLflow"):
        bundle.gates.require("production")
