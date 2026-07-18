"""Optional MLflow tracking and fail-closed PRE-A0 promotion governance."""

from __future__ import annotations

import hashlib
import importlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from open_prep.pre_a0_model import PreA0ModelArtifact, parse_artifact, verify_artifact_id

DEFAULT_EXPERIMENT_NAME = "pre-a0"
DEFAULT_REGISTERED_MODEL_NAME = "skipp-pre-a0"
PROMOTION_POLICY_CONTRACT_VERSION = "pre-a0-promotion-policy-v1"
RUNTIME_CONTRACT = "local-json-v1"
SUPPORTED_ALIASES = ("candidate", "shadow")


class GovernanceValidationError(ValueError):
    """Raised when the model/evidence bundle cannot be trusted."""


@dataclass(frozen=True, slots=True)
class PromotionGateResult:
    artifact_id: str
    identity_verified: bool
    evidence_linked: bool
    not_expired: bool
    offline_evaluated: bool
    shadow_evaluated: bool
    candidate_eligible: bool
    shadow_eligible: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def require(self, alias: str) -> None:
        if alias not in SUPPORTED_ALIASES:
            raise GovernanceValidationError(
                f"unsupported promotion alias {alias!r}; runtime promotion remains outside MLflow"
            )
        eligible = self.candidate_eligible if alias == "candidate" else self.shadow_eligible
        if not eligible:
            detail = ", ".join(self.reasons) or "promotion gate did not pass"
            raise GovernanceValidationError(f"{alias} promotion rejected: {detail}")


@dataclass(frozen=True, slots=True)
class ValidatedBundle:
    bundle_id: str
    artifact: PreA0ModelArtifact
    artifact_path: Path
    report: dict[str, Any]
    report_path: Path
    policy: dict[str, Any]
    policy_path: Path
    gates: PromotionGateResult


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GovernanceValidationError(f"cannot read {label}: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise GovernanceValidationError(f"{label} must contain a JSON object")
    return payload


def _metric(payload: dict[str, Any], name: str) -> float:
    try:
        value = float(payload[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise GovernanceValidationError(f"missing or invalid metric: {name}") from exc
    if not math.isfinite(value):
        raise GovernanceValidationError(f"non-finite metric: {name}")
    return value


def _parse_timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise GovernanceValidationError(f"invalid {label}") from exc
    if parsed.tzinfo is None:
        raise GovernanceValidationError(f"{label} must include a timezone")
    return parsed.astimezone(UTC)


def _bundle_id(
    artifact: PreA0ModelArtifact, report: dict[str, Any], policy: dict[str, Any]
) -> str:
    payload = {
        "artifact": artifact.to_dict(),
        "report": report,
        "policy": policy,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]


def validate_bundle(
    artifact_path: Path,
    report_path: Path,
    policy_path: Path,
    *,
    now: datetime | None = None,
    expected_artifact_id: str | None = None,
) -> ValidatedBundle:
    """Validate content identity, evidence linkage, freshness, and promotion gates."""
    artifact_payload = _read_object(Path(artifact_path), "PRE-A0 artifact")
    report = _read_object(Path(report_path), "validation report")
    policy = _read_object(Path(policy_path), "promotion policy")
    try:
        artifact = parse_artifact(artifact_payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise GovernanceValidationError(f"invalid PRE-A0 artifact: {type(exc).__name__}") from exc
    if policy.get("contract_version") != PROMOTION_POLICY_CONTRACT_VERSION:
        raise GovernanceValidationError("unsupported promotion policy contract")
    if expected_artifact_id and artifact.artifact_id != expected_artifact_id:
        raise GovernanceValidationError(
            f"unexpected artifact ID {artifact.artifact_id}; expected {expected_artifact_id}"
        )

    reasons: list[str] = []
    identity_verified = verify_artifact_id(artifact)
    if not identity_verified:
        reasons.append("artifact_identity_mismatch")

    evidence_linked = (
        report.get("artifact_id") == artifact.artifact_id
        and report.get("split_sha256") == artifact.split_manifest_sha256
    )
    report_metrics = report.get("metrics")
    if not isinstance(report_metrics, dict):
        raise GovernanceValidationError("validation report metrics must be an object")
    for name, artifact_value in artifact.metrics.items():
        if name not in report_metrics or not math.isclose(
            float(artifact_value), _metric(report_metrics, name), rel_tol=1e-12, abs_tol=1e-12
        ):
            evidence_linked = False
            break
    if not evidence_linked:
        reasons.append("validation_evidence_mismatch")

    checked_at = (now or datetime.now(UTC)).astimezone(UTC)
    not_expired = checked_at <= _parse_timestamp(artifact.review_after, "review_after")
    if not not_expired:
        reasons.append("artifact_expired")

    candidate_policy = policy.get("candidate")
    shadow_policy = policy.get("shadow")
    if not isinstance(candidate_policy, dict) or not isinstance(shadow_policy, dict):
        raise GovernanceValidationError("promotion policy is missing candidate or shadow rules")

    offline_evaluated = bool(artifact.gates.get("offline_evaluated")) and bool(report.get("offline_gate_passed"))
    if candidate_policy.get("require_offline_evaluated", True) and not offline_evaluated:
        reasons.append("offline_evaluation_missing")
    if candidate_policy.get("require_calibration", True) and not artifact.is_calibrated:
        reasons.append("calibration_missing")
    test_rows = _metric(report_metrics, "test_rows")
    if test_rows < float(candidate_policy["min_test_rows"]):
        reasons.append("test_rows_below_minimum")
    model_brier = _metric(report_metrics, "test_brier")
    baseline_brier = _metric(report_metrics, "test_base_rate_brier")
    if baseline_brier <= 0 or model_brier / baseline_brier >= float(candidate_policy["max_test_brier_ratio"]):
        reasons.append("brier_does_not_beat_baseline")
    if _metric(report_metrics, "test_ece") > float(candidate_policy["max_test_ece"]):
        reasons.append("test_ece_above_maximum")
    if _metric(report_metrics, "test_average_precision") < float(candidate_policy["min_test_average_precision"]):
        reasons.append("average_precision_below_minimum")

    candidate_blockers = {
        "artifact_identity_mismatch",
        "validation_evidence_mismatch",
        "artifact_expired",
        "offline_evaluation_missing",
        "calibration_missing",
        "test_rows_below_minimum",
        "brier_does_not_beat_baseline",
        "test_ece_above_maximum",
        "average_precision_below_minimum",
    }
    candidate_eligible = not candidate_blockers.intersection(reasons)
    shadow_evaluated = bool(artifact.gates.get("shadow_evaluated")) and bool(report.get("shadow_gate_passed"))
    if not shadow_evaluated:
        reasons.append("shadow_evaluation_missing")
    shadow_eligible = candidate_eligible and shadow_evaluated
    gates = PromotionGateResult(
        artifact_id=artifact.artifact_id,
        identity_verified=identity_verified,
        evidence_linked=evidence_linked,
        not_expired=not_expired,
        offline_evaluated=offline_evaluated,
        shadow_evaluated=shadow_evaluated,
        candidate_eligible=candidate_eligible,
        shadow_eligible=shadow_eligible,
        reasons=tuple(reasons),
    )
    return ValidatedBundle(
        bundle_id=_bundle_id(artifact, report, policy),
        artifact=artifact,
        artifact_path=Path(artifact_path),
        report=report,
        report_path=Path(report_path),
        policy=policy,
        policy_path=Path(policy_path),
        gates=gates,
    )


def _load_mlflow() -> Any:
    try:
        return importlib.import_module("mlflow")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "MLflow support is optional; install requirements-mlflow.txt before enabling tracking"
        ) from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_params(artifact: PreA0ModelArtifact) -> dict[str, str | int]:
    return {
        "artifact_id": artifact.artifact_id,
        "contract_version": artifact.contract_version,
        "schema_version": artifact.schema_version,
        "feature_version": artifact.feature_version,
        "split_manifest_sha256": artifact.split_manifest_sha256,
        "trained_from": artifact.trained_from,
        "trained_through": artifact.trained_through,
        "calibrated_from": artifact.calibrated_from,
        "calibrated_through": artifact.calibrated_through,
        "review_after": artifact.review_after,
        "feature_count": len(artifact.model.feature_names),
        "horizons": ",".join(str(value) for value in artifact.horizons),
        "runtime_contract": RUNTIME_CONTRACT,
    }


def log_training_run(
    *,
    tracking_uri: str,
    experiment_name: str,
    run_name: str | None,
    artifact_path: Path,
    training_input_path: Path,
    training_rows: int,
    calibration_rows: int,
) -> str:
    """Log a training run without registering or promoting the model."""
    mlflow = _load_mlflow()
    artifact_payload = _read_object(artifact_path, "PRE-A0 artifact")
    artifact = parse_artifact(artifact_payload)
    if not verify_artifact_id(artifact):
        raise GovernanceValidationError("refusing to track an artifact with an invalid identity")
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(experiment_name)
    with mlflow.start_run(run_name=run_name) as run:
        mlflow.set_tags(
            {
                "pre_a0_run_kind": "training",
                "pre_a0_artifact_id": artifact.artifact_id,
                "promotion_status": "trained",
                "runtime_contract": RUNTIME_CONTRACT,
            }
        )
        mlflow.log_params(
            {
                **_artifact_params(artifact),
                "training_input_sha256": _sha256(training_input_path),
                "training_rows": training_rows,
                "calibration_rows": calibration_rows,
            }
        )
        mlflow.log_metrics(artifact.metrics)
        mlflow.log_artifact(str(artifact_path), artifact_path="runtime-contract")
        return run.info.run_id


def import_validated_bundle(
    *,
    bundle: ValidatedBundle,
    tracking_uri: str,
    experiment_name: str = DEFAULT_EXPERIMENT_NAME,
    registered_model_name: str = DEFAULT_REGISTERED_MODEL_NAME,
    run_name: str | None = None,
) -> dict[str, str]:
    """Log and register a validated candidate, preserving JSON as runtime truth."""
    bundle.gates.require("candidate")
    mlflow = _load_mlflow()
    mlflow.set_tracking_uri(tracking_uri)
    experiment = mlflow.set_experiment(experiment_name)
    client = mlflow.MlflowClient()
    existing = client.search_runs(
        experiment_ids=[experiment.experiment_id],
        filter_string=f"tags.pre_a0_bundle_id = '{bundle.bundle_id}'",
        max_results=1,
    )
    if existing:
        raise GovernanceValidationError(
            f"validated bundle {bundle.bundle_id} already has MLflow run {existing[0].info.run_id}"
        )

    with mlflow.start_run(run_name=run_name) as run:
        mlflow.set_tags(
            {
                "pre_a0_run_kind": "validated_import",
                "pre_a0_artifact_id": bundle.artifact.artifact_id,
                "pre_a0_bundle_id": bundle.bundle_id,
                "promotion_status": "candidate",
                "runtime_contract": RUNTIME_CONTRACT,
            }
        )
        mlflow.log_params(_artifact_params(bundle.artifact))
        mlflow.log_metrics(bundle.artifact.metrics)
        mlflow.log_dict(bundle.gates.to_dict(), "governance/gate-result.json")
        mlflow.log_dict(bundle.artifact.to_dict(), "runtime-contract/pre-a0-model.json")
        mlflow.log_dict(bundle.report, "evidence/validation-report.json")
        mlflow.log_dict(bundle.policy, "governance/pre-a0-promotion-policy.json")
        pandas = importlib.import_module("pandas")
        example_values = {
            name: (minimum + maximum) / 2
            for name, minimum, maximum in zip(
                bundle.artifact.model.feature_names,
                bundle.artifact.model.feature_min,
                bundle.artifact.model.feature_max,
                strict=True,
            )
        }
        if "horizon_s" in example_values:
            example_values["horizon_s"] = float(bundle.artifact.horizons[0])
        model_info = mlflow.pyfunc.log_model(
            name="model",
            python_model=str(Path(__file__).with_name("pre_a0_mlflow_model.py")),
            artifacts={"pre_a0_contract": str(bundle.artifact_path)},
            code_paths=[str(Path(__file__).resolve().parent)],
            input_example=pandas.DataFrame([example_values]),
            pip_requirements=[f"mlflow=={mlflow.__version__}"],
        )
        version = mlflow.register_model(model_uri=model_info.model_uri, name=registered_model_name)
        version_number = str(version.version)
        version_tags = {
            "pre_a0.artifact_id": bundle.artifact.artifact_id,
            "pre_a0.bundle_id": bundle.bundle_id,
            "pre_a0.gate.offline_evaluated": str(bundle.gates.offline_evaluated).lower(),
            "pre_a0.gate.shadow_evaluated": str(bundle.gates.shadow_evaluated).lower(),
            "pre_a0.review_after": bundle.artifact.review_after,
            "pre_a0.runtime_contract": RUNTIME_CONTRACT,
            "pre_a0.promotion_status": "candidate",
        }
        for key, value in version_tags.items():
            client.set_model_version_tag(registered_model_name, version_number, key, value)
        client.set_registered_model_alias(registered_model_name, "candidate", version_number)
        return {
            "run_id": run.info.run_id,
            "registered_model": registered_model_name,
            "model_version": version_number,
            "alias": "candidate",
            "artifact_id": bundle.artifact.artifact_id,
            "bundle_id": bundle.bundle_id,
        }


def promote_registered_model(
    *,
    tracking_uri: str,
    registered_model_name: str,
    version: str,
    alias: str,
    policy_path: Path,
    now: datetime | None = None,
) -> dict[str, str]:
    """Re-download canonical evidence and apply an eligible registry alias."""
    if alias not in SUPPORTED_ALIASES:
        raise GovernanceValidationError("only candidate and shadow aliases are supported")
    mlflow = _load_mlflow()
    mlflow.set_tracking_uri(tracking_uri)
    client = mlflow.MlflowClient()
    model_version = client.get_model_version(registered_model_name, version)
    run_id = model_version.run_id
    if not run_id:
        raise GovernanceValidationError("registered model version has no source run")
    artifact_path = Path(
        mlflow.artifacts.download_artifacts(
            run_id=run_id,
            artifact_path="runtime-contract/pre-a0-model.json",
        )
    )
    report_path = Path(
        mlflow.artifacts.download_artifacts(
            run_id=run_id,
            artifact_path="evidence/validation-report.json",
        )
    )
    stored_policy_path = Path(
        mlflow.artifacts.download_artifacts(
            run_id=run_id,
            artifact_path="governance/pre-a0-promotion-policy.json",
        )
    )
    if _read_object(stored_policy_path, "stored promotion policy") != _read_object(
        policy_path, "local promotion policy"
    ):
        raise GovernanceValidationError(
            "local promotion policy differs from the policy recorded with this bundle"
        )
    expected_id = model_version.tags.get("pre_a0.artifact_id")
    if not expected_id:
        raise GovernanceValidationError("registered model version is missing its artifact identity")
    bundle = validate_bundle(
        artifact_path,
        report_path,
        policy_path,
        now=now,
        expected_artifact_id=expected_id,
    )
    expected_bundle_id = model_version.tags.get("pre_a0.bundle_id")
    if not expected_bundle_id or bundle.bundle_id != expected_bundle_id:
        raise GovernanceValidationError("registered bundle identity does not match its evidence")
    bundle.gates.require(alias)
    client.set_registered_model_alias(registered_model_name, alias, version)
    client.set_model_version_tag(registered_model_name, version, "pre_a0.promotion_status", alias)
    return {
        "registered_model": registered_model_name,
        "model_version": version,
        "alias": alias,
        "artifact_id": bundle.artifact.artifact_id,
        "bundle_id": bundle.bundle_id,
    }
