"""Version-governance decision engine for the SMC library refresh workflow.

Replaces the shell-based breaking-change detection with a deterministic
Python helper that uses the canonical ``smc_core.schema_version`` semver
policy as its single decision source.

Usage (CI)::

    python scripts/smc_version_governance.py \\
        --old-manifest /tmp/manifest_before.json \\
        --new-manifest pine/generated/smc_micro_profiles_generated.json \\
        --library pine/generated/smc_micro_profiles_generated.pine \\
        --old-library /tmp/library_before.pine

Exit codes::

    0  — auto-commit allowed (unchanged / patch / minor)
    1  — breaking change detected → PR or operator review required

Stdout: JSON governance decision (machine-readable).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Ensure repo root is importable
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from smc_core.schema_version import (
    VersionChangeType,
    auto_commit_allowed,
    classify_version_change,
    parse_semver,
)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _count_export_fields(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(
        1 for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("export const")
    )


def evaluate_governance(
    *,
    old_manifest: dict[str, Any],
    new_manifest: dict[str, Any],
    old_field_count: int = 0,
    new_field_count: int = 0,
) -> dict[str, Any]:
    """Evaluate the governance decision for a library refresh.

    Returns a structured dict with the decision and supporting metadata.
    """
    # Determine whether this is an initial deployment (no prior manifest).
    # Initial deploys are always auto-commit allowed — there are no existing
    # consumers to break.
    is_initial = not old_manifest or "schema_version" not in old_manifest

    old_schema = old_manifest.get("schema_version", "0.0.0")
    new_schema = new_manifest.get("schema_version", "0.0.0")

    # Validate both versions are valid semver (or use fallback)
    try:
        parse_semver(old_schema)
    except ValueError:
        old_schema = "0.0.0"
    try:
        parse_semver(new_schema)
    except ValueError:
        new_schema = "0.0.0"

    schema_change = classify_version_change(old_schema, new_schema)

    old_field_ver = old_manifest.get("library_field_version", "")
    new_field_ver = new_manifest.get("library_field_version", "")
    field_version_changed = bool(old_field_ver and old_field_ver != new_field_ver)

    field_count_changed = (
        old_field_count > 0 and new_field_count != old_field_count
    )

    # Decision: schema_version semver is the primary policy source.
    # Field-version and field-count changes are secondary signals that
    # escalate to breaking when the semver alone would allow auto-commit.
    reasons: list[str] = []

    if schema_change == VersionChangeType.MAJOR:
        reasons.append(
            f"schema_version major bump: {old_schema} → {new_schema}"
        )

    if field_version_changed:
        reasons.append(
            f"library_field_version changed: {old_field_ver} → {new_field_ver}"
        )

    if field_count_changed:
        reasons.append(
            f"export field count changed: {old_field_count} → {new_field_count}"
        )

    # Effective change type: escalate to MAJOR when secondary signals fire
    # but the semver didn't bump major (defensive — catches mismatches
    # between schema_version and actual layout).
    # Initial deploys are exempt from escalation.
    effective_change = schema_change
    if not is_initial and (field_version_changed or field_count_changed) and schema_change != VersionChangeType.MAJOR:
        effective_change = VersionChangeType.MAJOR
        if schema_change != VersionChangeType.MAJOR:
            reasons.append(
                "escalated to MAJOR: field layout changed without schema_version major bump"
            )

    allowed = is_initial or auto_commit_allowed(effective_change)

    return {
        "schema_version_old": old_schema,
        "schema_version_new": new_schema,
        "schema_change_type": schema_change.value,
        "effective_change_type": effective_change.value,
        "auto_commit_allowed": allowed,
        "pr_required": not allowed,
        "field_version_old": old_field_ver,
        "field_version_new": new_field_ver,
        "field_count_old": old_field_count,
        "field_count_new": new_field_count,
        "reasons": reasons,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate version-governance decision for SMC library refresh."
    )
    parser.add_argument(
        "--old-manifest", type=Path, required=True,
        help="Path to the pre-generation manifest snapshot.",
    )
    parser.add_argument(
        "--new-manifest", type=Path, required=True,
        help="Path to the newly generated manifest.",
    )
    parser.add_argument(
        "--old-library", type=Path, default=None,
        help="Path to the pre-generation Pine library snapshot.",
    )
    parser.add_argument(
        "--library", type=Path, default=None,
        help="Path to the newly generated Pine library.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    old_manifest = _read_json(args.old_manifest)
    new_manifest = _read_json(args.new_manifest)

    old_field_count = _count_export_fields(args.old_library) if args.old_library else 0
    new_field_count = _count_export_fields(args.library) if args.library else 0

    decision = evaluate_governance(
        old_manifest=old_manifest,
        new_manifest=new_manifest,
        old_field_count=old_field_count,
        new_field_count=new_field_count,
    )

    print(json.dumps(decision, indent=2))

    if decision["pr_required"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
