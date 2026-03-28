#!/usr/bin/env python3
"""Regenerate the canonical checked-in Pine library artifacts.

Usage
-----
    python -m scripts.refresh_generated_artifacts

What it does
~~~~~~~~~~~~
Runs the full ``run_generation()`` pipeline against the deterministic
seed fixture (``tests/fixtures/seed_base_snapshot.csv``) and writes the
three checked-in artifacts under ``pine/generated/``:

* ``smc_micro_profiles_generated.pine``  — the Pine v6 library
* ``smc_micro_profiles_generated.json``  — the manifest
* ``smc_micro_profiles_core_import_snippet.pine``  — the import snippet

All enrichment fields receive their safe neutral defaults
(``enrichment=None``) so the output is fully deterministic and
independent of external API keys.

Run this command after any change to the generator code
(``scripts/generate_smc_micro_profiles.py``,
``scripts/smc_micro_generator.py``, ``scripts/smc_micro_publisher.py``).
The anti-drift test ``tests/test_generated_artifact_drift.py`` will fail
if the checked-in artifacts are stale.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SEED_CSV = REPO_ROOT / "tests" / "fixtures" / "seed_base_snapshot.csv"
GENERATED_DIR = REPO_ROOT / "pine" / "generated"

ARTIFACTS = [
    "smc_micro_profiles_generated.pine",
    "smc_micro_profiles_generated.json",
    "smc_micro_profiles_core_import_snippet.pine",
]


def refresh(*, output_root: Path | None = None) -> dict[str, Path]:
    """Run the generator and return paths of the three checked-in artifacts."""
    from scripts.generate_smc_micro_profiles import run_generation
    from scripts.smc_schema_resolver import resolve_microstructure_schema_path

    target = output_root or REPO_ROOT
    schema_path = resolve_microstructure_schema_path()

    outputs = run_generation(
        schema_path=schema_path,
        input_path=SEED_CSV,
        output_root=target,
    )

    return {
        "pine_path": outputs["pine_path"],
        "manifest_path": outputs["manifest_path"],
        "core_import_snippet_path": outputs["core_import_snippet_path"],
    }


def main() -> None:
    if not SEED_CSV.exists():
        print(f"ERROR: seed fixture not found at {SEED_CSV}", file=sys.stderr)
        sys.exit(1)

    print(f"Regenerating from {SEED_CSV} ...")
    paths = refresh()
    print()
    for name, p in paths.items():
        print(f"  {name}: {p.relative_to(REPO_ROOT)}")
    print()
    print("Done. Commit the updated artifacts under pine/generated/.")


if __name__ == "__main__":
    main()
