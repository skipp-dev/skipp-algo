"""SMC microstructure profile publisher — all file I/O and TradingView push.

Takes a ``GenerationResult`` from the generator module and writes every
output artifact.  No computation or validation logic lives here — the
publisher trusts that the result has already been generated and validated.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from scripts.generate_smc_micro_profiles import (
    render_output_path,
    write_core_import_snippet,
    write_diff_report,
    write_lists_csv,
    write_manifest,
    write_pine_library,
    write_readiness_report,
)
from scripts.smc_enrichment_types import EnrichmentDict
from scripts.smc_micro_generator import GenerationResult


def publish_generation_result(
    result: GenerationResult,
    *,
    output_root: Path,
    library_owner: str = "preuss_steffen",
    library_version: int = 1,
    enrichment: EnrichmentDict | None = None,
) -> dict[str, Path]:
    """Write all generator output artifacts to disk.

    Returns a dict mapping artifact names to their written paths,
    identical in shape to the legacy ``run_generation`` return value.
    """
    outputs = result.schema["generator_outputs"]

    state_path = output_root / outputs["state_csv"]
    features_path = render_output_path(output_root, outputs["features_csv"], result.asof_date)
    lists_path = render_output_path(output_root, outputs["lists_csv"], result.asof_date)
    diff_report_path = render_output_path(output_root, outputs["diff_report_md"], result.asof_date)
    pine_path = output_root / outputs["pine_library"]
    manifest_path = output_root / outputs["manifest_json"]
    core_import_snippet_path = output_root / outputs["core_import_snippet"]

    # Ensure directories exist
    features_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    # Write data artifacts
    result.features_df.to_csv(features_path, index=False)
    result.state_df.to_csv(state_path, index=False)
    write_lists_csv(lists_path, result.state_df, result.asof_date)
    write_diff_report(diff_report_path, result.previous_state, result.state_df, result.asof_date)

    # Write Pine artifacts
    write_pine_library(pine_path, result.lists, result.asof_date, result.universe_size, enrichment=enrichment)
    recommended_import_path = write_core_import_snippet(
        core_import_snippet_path,
        library_owner=library_owner,
        library_name="smc_micro_profiles_generated",
        library_version=library_version,
    )

    # Write manifest
    write_manifest(
        manifest_path,
        asof_date=result.asof_date,
        input_path=result.input_path,
        schema_path=result.schema_path,
        features_path=features_path,
        lists_path=lists_path,
        state_path=state_path,
        diff_report_path=diff_report_path,
        pine_path=pine_path,
        core_import_snippet_path=core_import_snippet_path,
        universe_size=result.universe_size,
        lists=result.lists,
        library_owner=library_owner,
        library_version=library_version,
        recommended_import_path=recommended_import_path,
    )

    return {
        "features_path": features_path,
        "lists_path": lists_path,
        "state_path": state_path,
        "diff_report_path": diff_report_path,
        "pine_path": pine_path,
        "manifest_path": manifest_path,
        "core_import_snippet_path": core_import_snippet_path,
    }


def publish_readiness_report(
    assessment: dict[str, Any],
    *,
    output_path: Path,
) -> None:
    """Write a schema-coverage markdown report."""
    write_readiness_report(output_path, assessment)
