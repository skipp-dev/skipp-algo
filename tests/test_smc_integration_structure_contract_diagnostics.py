from __future__ import annotations

import json
from pathlib import Path

from smc_integration.structure_contract import normalize_structure_contracts_with_diagnostics
from smc_integration.sources import structure_artifact_json


def test_normalize_structure_contracts_reports_dropped_legacy_entries() -> None:
    payload = {
        "entries": [
            {
                "symbol": "AAPL",
                "timeframe": "15m",
                "structure": {
                    "bos": [],
                    "orderblocks": [],
                    "fvg": [],
                    "liquidity_sweeps": [],
                },
            },
            {
                "symbol": "",
                "timeframe": "15m",
                "structure": {
                    "bos": [],
                    "orderblocks": [],
                    "fvg": [],
                    "liquidity_sweeps": [],
                },
            },
            "bad-entry",
        ]
    }

    contracts, diagnostics = normalize_structure_contracts_with_diagnostics(payload)

    assert len(contracts) == 1
    assert diagnostics["entries_total"] == 3
    assert diagnostics["entries_normalized"] == 1
    assert diagnostics["entries_dropped"] == 2
    assert diagnostics["entries_dropped_non_dict"] == 1
    assert diagnostics["entries_dropped_value_error"] == 1


def test_discover_summary_reports_legacy_drop_health_issue(monkeypatch, tmp_path: Path) -> None:
    legacy_path = tmp_path / "reports" / "smc_structure_artifact.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "symbol": "AAPL",
                        "timeframe": "15m",
                        "structure": {
                            "bos": [],
                            "orderblocks": [],
                            "fvg": [],
                            "liquidity_sweeps": [],
                        },
                    },
                    {
                        "symbol": "",
                        "timeframe": "15m",
                        "structure": {
                            "bos": [],
                            "orderblocks": [],
                            "fvg": [],
                            "liquidity_sweeps": [],
                        },
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(structure_artifact_json, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", tmp_path / "reports" / "smc_structure_artifacts")
    monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACT_JSON", legacy_path)

    summary = structure_artifact_json.discover_normalized_contract_summary()

    assert summary["health"]["issue_count"] >= 1
    codes = {str(item.get("code", "")) for item in summary["health"]["issues"]}
    assert "LEGACY_ENTRIES_DROPPED" in codes
