from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify_smc_micro_publish_contract import verify_publish_contract


def test_verify_publish_contract_passes_for_current_repo() -> None:
    result = verify_publish_contract(
        Path("pine/generated/smc_micro_profiles_generated.json"),
        Path("SMC_Core_Engine.pine"),
    )

    assert result["recommended_import_path"] == "preuss_steffen/smc_micro_profiles_generated/1"
    assert result["alias"] == "mp"


def test_verify_publish_contract_rejects_manifest_core_mismatch(tmp_path: Path) -> None:
    pine_dir = tmp_path / "pine" / "generated"
    pine_dir.mkdir(parents=True)

    manifest_path = pine_dir / "smc_micro_profiles_generated.json"
    snippet_path = pine_dir / "smc_micro_profiles_core_import_snippet.pine"
    library_path = pine_dir / "smc_micro_profiles_generated.pine"
    core_path = tmp_path / "SMC_Core_Engine.pine"

    manifest_path.write_text(
        json.dumps(
            {
                "recommended_import_path": "owner_a/smc_micro_profiles_generated/2",
                "core_import_snippet": "pine/generated/smc_micro_profiles_core_import_snippet.pine",
                "pine_library": "pine/generated/smc_micro_profiles_generated.pine",
            }
        ),
        encoding="utf-8",
    )
    snippet_path.write_text(
        "import owner_a/smc_micro_profiles_generated/2 as mp\nstring clean_reclaim_tickers_effective = mp.CLEAN_RECLAIM_TICKERS\n",
        encoding="utf-8",
    )
    library_path.write_text("//@version=6\nlibrary(\"smc_micro_profiles_generated\")\n", encoding="utf-8")
    core_path.write_text(
        "//@version=6\nimport owner_b/smc_micro_profiles_generated/2 as mp\nstring clean_reclaim_tickers_effective = mp.CLEAN_RECLAIM_TICKERS\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="Core import path mismatch"):
        verify_publish_contract(manifest_path, core_path)


def test_verify_publish_contract_rejects_missing_exact_code_block(tmp_path: Path) -> None:
    pine_dir = tmp_path / "pine" / "generated"
    pine_dir.mkdir(parents=True)

    manifest_path = pine_dir / "smc_micro_profiles_generated.json"
    snippet_path = pine_dir / "smc_micro_profiles_core_import_snippet.pine"
    library_path = pine_dir / "smc_micro_profiles_generated.pine"
    core_path = tmp_path / "SMC_Core_Engine.pine"

    manifest_path.write_text(
        json.dumps(
            {
                "recommended_import_path": "owner_a/smc_micro_profiles_generated/2",
                "core_import_snippet": "pine/generated/smc_micro_profiles_core_import_snippet.pine",
                "pine_library": "pine/generated/smc_micro_profiles_generated.pine",
            }
        ),
        encoding="utf-8",
    )
    snippet_path.write_text(
        "import owner_a/smc_micro_profiles_generated/2 as mp\nstring clean_reclaim_tickers_effective = mp.CLEAN_RECLAIM_TICKERS\n",
        encoding="utf-8",
    )
    library_path.write_text("//@version=6\nlibrary(\"smc_micro_profiles_generated\")\n", encoding="utf-8")
    core_path.write_text(
        "//@version=6\nimport owner_a/smc_micro_profiles_generated/2 as mp\n// string clean_reclaim_tickers_effective = mp.CLEAN_RECLAIM_TICKERS\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="contiguous alias block"):
        verify_publish_contract(manifest_path, core_path)


def test_verify_publish_contract_rejects_non_contiguous_anchored_block(tmp_path: Path) -> None:
    pine_dir = tmp_path / "pine" / "generated"
    pine_dir.mkdir(parents=True)

    manifest_path = pine_dir / "smc_micro_profiles_generated.json"
    snippet_path = pine_dir / "smc_micro_profiles_core_import_snippet.pine"
    library_path = pine_dir / "smc_micro_profiles_generated.pine"
    core_path = tmp_path / "SMC_Core_Engine.pine"

    manifest_path.write_text(
        json.dumps(
            {
                "recommended_import_path": "owner_a/smc_micro_profiles_generated/2",
                "core_import_snippet": "pine/generated/smc_micro_profiles_core_import_snippet.pine",
                "pine_library": "pine/generated/smc_micro_profiles_generated.pine",
            }
        ),
        encoding="utf-8",
    )
    snippet_path.write_text(
        "import owner_a/smc_micro_profiles_generated/2 as mp\n"
        "string clean_reclaim_tickers_effective = mp.CLEAN_RECLAIM_TICKERS\n"
        "string open_reclaim_tickers_effective = mp.OPEN_RECLAIM_TICKERS\n",
        encoding="utf-8",
    )
    library_path.write_text("//@version=6\nlibrary(\"smc_micro_profiles_generated\")\n", encoding="utf-8")
    core_path.write_text(
        "//@version=6\n"
        "import owner_a/smc_micro_profiles_generated/2 as mp\n"
        "string clean_reclaim_tickers_effective = mp.CLEAN_RECLAIM_TICKERS\n"
        "string unrelated = \"break\"\n"
        "string open_reclaim_tickers_effective = mp.OPEN_RECLAIM_TICKERS\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="contiguous alias block"):
        verify_publish_contract(manifest_path, core_path)