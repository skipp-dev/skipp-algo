"""SMC microstructure profile validator — schema and publish-readiness checks.

All functions are side-effect free (no file writes).  They raise
``RuntimeError`` on validation failures so callers can decide whether
to surface the error or treat it as a gate result.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from scripts.generate_smc_micro_profiles import (
    assess_csv_against_schema,
    load_schema,
    validate_schema,
)


def validate_generation_input(df: pd.DataFrame, schema: dict[str, Any]) -> None:
    """Validate a coerced input DataFrame against the microstructure schema.

    Delegates to the existing ``validate_schema`` implementation which
    checks required columns, primary-key integrity, single asof_date,
    and value ranges.  Raises ``RuntimeError`` on any violation.
    """
    validate_schema(df, schema)


def validate_publish_readiness(
    *,
    manifest_path: Path,
    core_path: Path,
) -> dict[str, str]:
    """Run the triple-validation publish contract check.

    Returns a status dict on success; raises ``RuntimeError`` when the
    contract is violated.
    """
    from scripts.verify_smc_micro_publish_contract import verify_publish_contract

    return verify_publish_contract(manifest_path, core_path)


def assess_input_coverage(schema: dict[str, Any], csv_path: Path) -> dict[str, Any]:
    """Assess how many required schema columns a CSV already provides.

    Returns a dict with ``present_required``, ``missing_required``,
    ``extra_columns``, and ``required_coverage`` keys.
    """
    return assess_csv_against_schema(schema, csv_path)
