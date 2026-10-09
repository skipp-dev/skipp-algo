from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from open_prep.pre_a0_mlflow import GovernanceValidationError, validate_bundle

ARTIFACT_ID = "71831770afe43bdd424aa7ab"
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
        now=datetime(2026, 8, 18, tzinfo=UTC),
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


def test_runtime_production_alias_is_not_available() -> None:
    bundle = validate_bundle(
        ARTIFACT_PATH,
        REPORT_PATH,
        POLICY_PATH,
        now=datetime(2026, 7, 18, tzinfo=UTC),
    )
    with pytest.raises(GovernanceValidationError, match="runtime promotion remains outside MLflow"):
        bundle.gates.require("production")
