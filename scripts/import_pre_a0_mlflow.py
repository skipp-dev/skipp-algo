#!/usr/bin/env python3
"""Import a validated PRE-A0 JSON bundle into MLflow as a candidate."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from open_prep.pre_a0_mlflow import (
    DEFAULT_EXPERIMENT_NAME,
    DEFAULT_REGISTERED_MODEL_NAME,
    import_validated_bundle,
    validate_bundle,
)

DEFAULT_ARTIFACT = Path("services/a0_fast_detector/bootstrap/pre-a0-model.json")
DEFAULT_REPORT = Path("services/a0_fast_detector/bootstrap/validation-report.json")
DEFAULT_POLICY = Path("governance/pre_a0_promotion_policy.json")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--validation-report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--expected-artifact-id")
    parser.add_argument("--tracking-uri")
    parser.add_argument("--experiment-name", default=DEFAULT_EXPERIMENT_NAME)
    parser.add_argument("--registered-model-name", default=DEFAULT_REGISTERED_MODEL_NAME)
    parser.add_argument("--run-name")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform MLflow writes; without this flag only validate and print the plan",
    )
    args = parser.parse_args()
    bundle = validate_bundle(
        args.artifact,
        args.validation_report,
        args.policy,
        expected_artifact_id=args.expected_artifact_id,
    )
    bundle.gates.require("candidate")
    tracking_uri = args.tracking_uri or os.environ.get("MLFLOW_TRACKING_URI")
    if not args.apply:
        print(
            json.dumps(
                {
                    "action": "dry_run",
                    "artifact_id": bundle.artifact.artifact_id,
                    "bundle_id": bundle.bundle_id,
                    "gates": bundle.gates.to_dict(),
                    "registered_model": args.registered_model_name,
                    "target_alias": "candidate",
                    "tracking_uri_configured": bool(tracking_uri),
                },
                sort_keys=True,
            )
        )
        return 0
    if not tracking_uri:
        parser.error("--tracking-uri or MLFLOW_TRACKING_URI is required with --apply")
    result = import_validated_bundle(
        bundle=bundle,
        tracking_uri=tracking_uri,
        experiment_name=args.experiment_name,
        registered_model_name=args.registered_model_name,
        run_name=args.run_name,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
