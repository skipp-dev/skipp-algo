"""SMC microstructure profile generator — pure computation, no file I/O.

Takes a base snapshot CSV and produces scored features, membership state,
and list assignments.  Every function in this module is side-effect free
(reads from DataFrames, not from disk).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.generate_smc_micro_profiles import (
    LISTS,
    STATE_COLUMNS,
    Thresholds,
    add_bucket_features,
    apply_candidate_rules,
    apply_overrides,
    build_lists_from_state,
    coerce_input_frame,
    load_overrides,
    load_state,
    update_membership_state,
)


@dataclass(frozen=True)
class GenerationResult:
    """Pure computation result — no file I/O has occurred."""

    features_df: pd.DataFrame
    previous_state: pd.DataFrame
    state_df: pd.DataFrame
    lists: dict[str, list[str]]
    asof_date: str
    universe_size: int
    schema: dict[str, Any]
    input_path: Path
    schema_path: Path
    overrides_applied: bool = False


def generate(
    *,
    schema: dict[str, Any],
    input_df: pd.DataFrame,
    schema_path: Path,
    input_path: Path,
    state_path: Path | None = None,
    overrides_path: Path | None = None,
) -> GenerationResult:
    """Run the full generation pipeline without writing any files.

    Parameters
    ----------
    schema:
        Parsed microstructure schema dict.
    input_df:
        Raw base-snapshot DataFrame (will be coerced and validated
        by the caller through the validator module).
    schema_path / input_path:
        Recorded for manifest metadata only — not read here.
    state_path:
        Path to prior membership state CSV.  ``None`` triggers
        bootstrap mode (empty state).
    overrides_path:
        Optional per-run membership overrides CSV.
    """
    df = coerce_input_frame(input_df)
    df = add_bucket_features(df, schema)
    df = apply_candidate_rules(df, schema)

    asof_date = str(df["asof_date"].iloc[0])

    previous_state = load_state(state_path) if state_path is not None else pd.DataFrame(columns=STATE_COLUMNS)
    state = update_membership_state(df, previous_state, asof_date, schema)

    overrides = load_overrides(overrides_path, asof_date)
    overrides_applied = not overrides.empty
    state = apply_overrides(state, overrides, asof_date)

    lists = build_lists_from_state(state)

    return GenerationResult(
        features_df=df,
        previous_state=previous_state,
        state_df=state,
        lists=lists,
        asof_date=asof_date,
        universe_size=int(df["symbol"].nunique()),
        schema=schema,
        input_path=input_path,
        schema_path=schema_path,
        overrides_applied=overrides_applied,
    )
