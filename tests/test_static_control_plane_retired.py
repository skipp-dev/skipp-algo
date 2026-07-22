"""`static_control_plane` is gone from the codebase (ADR-0029, decision 3).

Operator decision 2026-07-22: no flip back to `--static-only`. #3902 blocked
the mode at the publish gate; this pins that the plumbing itself is removed, so
the name cannot promise a capability the repo no longer has.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from scripts import (
    generate_smc_micro_base_from_databento as base_gen,
)
from scripts.generate_smc_micro_profiles import run_generation, write_manifest
from scripts.smc_micro_publisher import publish_generation_result

_PRODUCTION_MODULES = (
    "scripts/generate_smc_micro_base_from_databento.py",
    "scripts/generate_smc_micro_profiles.py",
    "scripts/smc_micro_publisher.py",
    "scripts/smc_microstructure_base_runtime.py",
)


def test_cli_no_longer_accepts_static_only() -> None:
    parser = base_gen.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["dummy.xlsx", "--static-only"])


@pytest.mark.parametrize(
    "func", [run_generation, write_manifest, publish_generation_result]
)
def test_no_public_entry_point_takes_the_mode(func) -> None:
    assert "static_control_plane" not in inspect.signature(func).parameters


@pytest.mark.parametrize("module_path", _PRODUCTION_MODULES)
def test_no_production_module_mentions_the_mode(module_path: str) -> None:
    """Catches leftovers the signature checks cannot see (locals, branches)."""
    source = Path(module_path).read_text(encoding="utf-8")

    assert "static_control_plane" not in source
    assert "static_only" not in source


def test_generation_mode_is_recorded_as_provider_enriched(tmp_path: Path) -> None:
    """The provenance field survives as a constant — publishing is enriched-only."""
    import json

    from tests.test_generate_smc_micro_profiles import SCHEMA_PATH

    outputs = run_generation(
        schema_path=Path(SCHEMA_PATH),
        input_path=Path("data/input/microstructure_base_snapshot_2026-03-23.csv"),
        output_root=tmp_path,
    )
    manifest = json.loads(outputs["manifest_path"].read_text(encoding="utf-8"))

    assert manifest["generation_mode"] == "provider_enriched"
