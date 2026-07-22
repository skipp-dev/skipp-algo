from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify_smc_micro_publish_contract import verify_publish_contract


def _manifest_payload(
    import_path: str,
    *,
    publish_ready: bool = True,
    blocking_reasons: list[str] | None = None,
    fixture_input_detected: bool = False,
    default_event_risk_detected: bool = False,
    placeholder_symbols: list[str] | None = None,
    input_path: str = "data/output/microstructure_features_2026-03-24.csv",
    universe_size: int = 240,
    event_risk_source: str = "smc_event_risk_builder",
) -> dict[str, object]:
    return {
        "recommended_import_path": import_path,
        "core_import_snippet": "pine/generated/smc_micro_profiles_core_import_snippet.pine",
        "pine_library": "pine/generated/smc_micro_profiles_generated.pine",
        "input_path": input_path,
        "universe_size": universe_size,
        "event_risk_source": event_risk_source,
        "deprecated_field_policy": {
            "mode": "compatibility_only",
            "preferred_field_version": "v8.0a",
            "extension_allowed": False,
            "deprecated_groups": ["event_risk_v5"],
        },
        "productivity_gate": {
            "publish_ready": publish_ready,
            "blocking_reasons": blocking_reasons or [],
            "fixture_input_detected": fixture_input_detected,
            "default_event_risk_detected": default_event_risk_detected,
            "placeholder_symbols": placeholder_symbols or [],
            # ADR-0029. These cases write a stub library carrying no payload
            # exports at all, so the honest measurement is "unknown".
            "payload_known": False,
            "universe_tickers_count": None,
            "list_total": None,
        },
    }


def test_verify_publish_contract_accepts_publish_ready_manifest(tmp_path: Path) -> None:
    pine_dir = tmp_path / "pine" / "generated"
    pine_dir.mkdir(parents=True)

    manifest_path = pine_dir / "smc_micro_profiles_generated.json"
    snippet_path = pine_dir / "smc_micro_profiles_core_import_snippet.pine"
    library_path = pine_dir / "smc_micro_profiles_generated.pine"
    core_path = tmp_path / "SMC_Long_Dip_Suite.pine"

    manifest_path.write_text(
        json.dumps(_manifest_payload("owner_a/smc_micro_profiles_generated/2")),
        encoding="utf-8",
    )
    snippet_path.write_text(
        "import owner_a/smc_micro_profiles_generated/2 as mp\n"
        "string clean_reclaim_tickers_effective = mp.CLEAN_RECLAIM_TICKERS\n",
        encoding="utf-8",
    )
    library_path.write_text("//@version=6\nlibrary(\"smc_micro_profiles_generated\")\n", encoding="utf-8")
    core_path.write_text(
        "//@version=6\n"
        "import owner_a/smc_micro_profiles_generated/2 as mp\n"
        "string clean_reclaim_tickers_effective = mp.CLEAN_RECLAIM_TICKERS\n",
        encoding="utf-8",
    )

    result = verify_publish_contract(manifest_path, core_path)

    assert result["recommended_import_path"] == "owner_a/smc_micro_profiles_generated/2"
    assert result["alias"] == "mp"
    assert result["deprecated_policy_mode"] == "compatibility_only"
    assert result["preferred_field_version"] == "v8.0a"
    assert result["publish_ready"] == "true"


def test_verify_publish_contract_rejects_non_productive_manifest(tmp_path: Path) -> None:
    pine_dir = tmp_path / "pine" / "generated"
    pine_dir.mkdir(parents=True)

    manifest_path = pine_dir / "smc_micro_profiles_generated.json"
    snippet_path = pine_dir / "smc_micro_profiles_core_import_snippet.pine"
    library_path = pine_dir / "smc_micro_profiles_generated.pine"
    core_path = tmp_path / "SMC_Long_Dip_Suite.pine"

    manifest_path.write_text(
        json.dumps(
            _manifest_payload(
                "owner_a/smc_micro_profiles_generated/2",
                publish_ready=False,
                blocking_reasons=["fixture_input", "default_event_risk", "placeholder_symbols"],
                fixture_input_detected=True,
                default_event_risk_detected=True,
                placeholder_symbols=["AAA", "BBB", "CCC"],
                input_path="tests/fixtures/seed_base_snapshot.csv",
                universe_size=3,
                event_risk_source="defaults",
            )
        ),
        encoding="utf-8",
    )
    snippet_path.write_text(
        "import owner_a/smc_micro_profiles_generated/2 as mp\n"
        "string clean_reclaim_tickers_effective = mp.CLEAN_RECLAIM_TICKERS\n",
        encoding="utf-8",
    )
    library_path.write_text("//@version=6\nlibrary(\"smc_micro_profiles_generated\")\n", encoding="utf-8")
    core_path.write_text(
        "//@version=6\n"
        "import owner_a/smc_micro_profiles_generated/2 as mp\n"
        "string clean_reclaim_tickers_effective = mp.CLEAN_RECLAIM_TICKERS\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="not publish-ready: fixture_input, default_event_risk, placeholder_symbols"):
        verify_publish_contract(manifest_path, core_path)


def test_verify_publish_contract_rejects_manifest_core_mismatch(tmp_path: Path) -> None:
    pine_dir = tmp_path / "pine" / "generated"
    pine_dir.mkdir(parents=True)

    manifest_path = pine_dir / "smc_micro_profiles_generated.json"
    snippet_path = pine_dir / "smc_micro_profiles_core_import_snippet.pine"
    library_path = pine_dir / "smc_micro_profiles_generated.pine"
    core_path = tmp_path / "SMC_Long_Dip_Suite.pine"

    manifest_path.write_text(
        json.dumps(
            _manifest_payload("owner_a/smc_micro_profiles_generated/2")
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

    with pytest.raises(RuntimeError, match="Core import library identity mismatch"):
        verify_publish_contract(manifest_path, core_path)


def test_verify_publish_contract_accepts_newer_published_core_pin(tmp_path: Path) -> None:
    pine_dir = tmp_path / "pine" / "generated"
    pine_dir.mkdir(parents=True)
    manifest_path = pine_dir / "smc_micro_profiles_generated.json"
    manifest_path.write_text(json.dumps(_manifest_payload("owner_a/smc_micro_profiles_generated/1")), encoding="utf-8")
    (pine_dir / "smc_micro_profiles_core_import_snippet.pine").write_text(
        "import owner_a/smc_micro_profiles_generated/1 as mp\nstring value = mp.VALUE\n", encoding="utf-8"
    )
    (pine_dir / "smc_micro_profiles_generated.pine").write_text(
        "//@version=6\nlibrary(\"smc_micro_profiles_generated\")\n", encoding="utf-8"
    )
    core_path = tmp_path / "SMC_Long_Dip_Suite.pine"
    core_path.write_text(
        "//@version=6\nimport owner_a/smc_micro_profiles_generated/152 as mp\nstring value = mp.VALUE\n", encoding="utf-8"
    )
    result = verify_publish_contract(manifest_path, core_path)
    assert result["core_import_path"] == "owner_a/smc_micro_profiles_generated/152"


def test_verify_publish_contract_rejects_missing_exact_code_block(tmp_path: Path) -> None:
    pine_dir = tmp_path / "pine" / "generated"
    pine_dir.mkdir(parents=True)

    manifest_path = pine_dir / "smc_micro_profiles_generated.json"
    snippet_path = pine_dir / "smc_micro_profiles_core_import_snippet.pine"
    library_path = pine_dir / "smc_micro_profiles_generated.pine"
    core_path = tmp_path / "SMC_Long_Dip_Suite.pine"

    manifest_path.write_text(
        json.dumps(
            _manifest_payload("owner_a/smc_micro_profiles_generated/2")
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
    core_path = tmp_path / "SMC_Long_Dip_Suite.pine"

    manifest_path.write_text(
        json.dumps(
            _manifest_payload("owner_a/smc_micro_profiles_generated/2")
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


def test_verify_publish_contract_rejects_duplicate_real_alias_block(tmp_path: Path) -> None:
    pine_dir = tmp_path / "pine" / "generated"
    pine_dir.mkdir(parents=True)

    manifest_path = pine_dir / "smc_micro_profiles_generated.json"
    snippet_path = pine_dir / "smc_micro_profiles_core_import_snippet.pine"
    library_path = pine_dir / "smc_micro_profiles_generated.pine"
    core_path = tmp_path / "SMC_Long_Dip_Suite.pine"

    manifest_path.write_text(
        json.dumps(
            _manifest_payload("owner_a/smc_micro_profiles_generated/2")
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
        "string open_reclaim_tickers_effective = mp.OPEN_RECLAIM_TICKERS\n"
        "string spacer = \"ok\"\n"
        "string clean_reclaim_tickers_effective = mp.CLEAN_RECLAIM_TICKERS\n"
        "string open_reclaim_tickers_effective = mp.OPEN_RECLAIM_TICKERS\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="exactly once"):
        verify_publish_contract(manifest_path, core_path)


def test_verify_publish_contract_accepts_alias_block_with_inline_comments(tmp_path: Path) -> None:
    pine_dir = tmp_path / "pine" / "generated"
    pine_dir.mkdir(parents=True)

    manifest_path = pine_dir / "smc_micro_profiles_generated.json"
    snippet_path = pine_dir / "smc_micro_profiles_core_import_snippet.pine"
    library_path = pine_dir / "smc_micro_profiles_generated.pine"
    core_path = tmp_path / "SMC_Long_Dip_Suite.pine"

    manifest_path.write_text(
        json.dumps(
            _manifest_payload("owner_a/smc_micro_profiles_generated/2")
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
        "string clean_reclaim_tickers_effective = mp.CLEAN_RECLAIM_TICKERS // keep generated alias\n"
        "string open_reclaim_tickers_effective = mp.OPEN_RECLAIM_TICKERS // keep generated alias\n",
        encoding="utf-8",
    )

    result = verify_publish_contract(manifest_path, core_path)

    assert result["alias"] == "mp"


# ── ADR-0029: the verifier must check the library, not just the manifest ──

HEALTHY_LIBRARY = (
    '//@version=6\nlibrary("smc_micro_profiles_generated")\n'
    "export const int UNIVERSE_SIZE = 3\n"
    'export const string UNIVERSE_TICKERS = "AAPL,MSFT,NVDA"\n'
    'export const string CLEAN_RECLAIM_TICKERS = "AAPL"\n'
)

INCIDENT_LIBRARY = (
    '//@version=6\nlibrary("smc_micro_profiles_generated")\n'
    "export const int UNIVERSE_SIZE = 6929\n"
    'export const string UNIVERSE_TICKERS = ""\n'
    'export const string CLEAN_RECLAIM_TICKERS = ""\n'
)


def _build_scenario(
    tmp_path: Path,
    *,
    library_text: str,
    gate_overrides: dict[str, object],
) -> tuple[Path, Path]:
    pine_dir = tmp_path / "pine" / "generated"
    pine_dir.mkdir(parents=True)

    manifest_path = pine_dir / "smc_micro_profiles_generated.json"
    snippet_path = pine_dir / "smc_micro_profiles_core_import_snippet.pine"
    library_path = pine_dir / "smc_micro_profiles_generated.pine"
    core_path = tmp_path / "SMC_Long_Dip_Suite.pine"

    payload = _manifest_payload("owner_a/smc_micro_profiles_generated/2")
    payload["productivity_gate"].update(gate_overrides)  # type: ignore[union-attr]
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    snippet_path.write_text(
        "import owner_a/smc_micro_profiles_generated/2 as mp\n"
        "string clean_reclaim_tickers_effective = mp.CLEAN_RECLAIM_TICKERS\n",
        encoding="utf-8",
    )
    library_path.write_text(library_text, encoding="utf-8")
    core_path.write_text(
        "//@version=6\n"
        "import owner_a/smc_micro_profiles_generated/2 as mp\n"
        "string clean_reclaim_tickers_effective = mp.CLEAN_RECLAIM_TICKERS\n",
        encoding="utf-8",
    )
    return manifest_path, core_path


def test_rejects_an_empty_library_even_when_the_manifest_says_publish_ready(
    tmp_path: Path,
) -> None:
    """A manifest cannot vouch for a library it contradicts."""
    manifest_path, core_path = _build_scenario(
        tmp_path,
        library_text=INCIDENT_LIBRARY,
        gate_overrides={
            "payload_known": True,
            "universe_tickers_count": 0,
            "list_total": 0,
        },
    )

    with pytest.raises(RuntimeError, match="empty_universe_tickers"):
        verify_publish_contract(manifest_path, core_path)


def test_rejects_a_manifest_whose_counts_diverge_from_the_library(
    tmp_path: Path,
) -> None:
    """The manifest claims a payload the shipped library does not carry."""
    manifest_path, core_path = _build_scenario(
        tmp_path,
        library_text=INCIDENT_LIBRARY,
        gate_overrides={
            "payload_known": True,
            "universe_tickers_count": 6929,
            "list_total": 412,
        },
    )

    with pytest.raises(RuntimeError, match="does not match"):
        verify_publish_contract(manifest_path, core_path)


def test_accepts_a_library_consistent_with_its_manifest(tmp_path: Path) -> None:
    manifest_path, core_path = _build_scenario(
        tmp_path,
        library_text=HEALTHY_LIBRARY,
        gate_overrides={
            "payload_known": True,
            "universe_tickers_count": 3,
            "list_total": 1,
        },
    )

    result = verify_publish_contract(manifest_path, core_path)

    assert result["universe_tickers_count"] == "3"
    assert result["list_total"] == "1"
