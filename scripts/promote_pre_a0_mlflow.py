#!/usr/bin/env python3
"""Promote a registered PRE-A0 version after rechecking canonical evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from open_prep.pre_a0_mlflow import (
    DEFAULT_REGISTERED_MODEL_NAME,
    SUPPORTED_ALIASES,
    promote_registered_model,
)

DEFAULT_POLICY = Path("governance/pre_a0_promotion_policy.json")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    parser.add_argument("alias", choices=SUPPORTED_ALIASES)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--tracking-uri")
    parser.add_argument("--registered-model-name", default=DEFAULT_REGISTERED_MODEL_NAME)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform the alias write; without this flag print the intended action",
    )
    args = parser.parse_args()
    tracking_uri = args.tracking_uri or os.environ.get("MLFLOW_TRACKING_URI")
    if not tracking_uri:
        parser.error("--tracking-uri or MLFLOW_TRACKING_URI is required")
    if not args.apply:
        print(
            json.dumps(
                {
                    "action": "dry_run",
                    "registered_model": args.registered_model_name,
                    "model_version": args.version,
                    "target_alias": args.alias,
                    "note": "--apply downloads and revalidates canonical JSON evidence before writing",
                },
                sort_keys=True,
            )
        )
        return 0
    result = promote_registered_model(
        tracking_uri=tracking_uri,
        registered_model_name=args.registered_model_name,
        version=args.version,
        alias=args.alias,
        policy_path=args.policy,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
