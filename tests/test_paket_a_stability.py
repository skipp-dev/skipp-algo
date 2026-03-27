"""Paket A – Stabilität: acceptance tests covering A1-A3.

A1: Schema path unification via central resolver.
A2: Meta domain visibility (present/missing/diagnostics).
A3: Plan-loader harmonization (structure_resolution_mode).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# A1 – Schema resolver
# ---------------------------------------------------------------------------
from scripts.smc_schema_resolver import resolve_microstructure_schema_path


class TestA1SchemaResolver:
    def test_resolver_returns_existing_path(self) -> None:
        path = resolve_microstructure_schema_path()
        assert path.exists(), f"canonical schema not found at {path}"

    def test_schema_is_valid_json(self) -> None:
        path = resolve_microstructure_schema_path()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "required_columns" in data
        assert "scoring" in data
        assert "eligibility" in data

    def test_resolver_raises_when_file_missing(self, tmp_path: Path) -> None:
        fake_path = tmp_path / "does_not_exist.json"
        with patch("scripts.smc_schema_resolver._CANONICAL_PATH", fake_path):
            with pytest.raises(FileNotFoundError, match="canonical location"):
                resolve_microstructure_schema_path()


# ---------------------------------------------------------------------------
# A2 – Meta domain visibility
# ---------------------------------------------------------------------------
from smc_integration.meta_merge import merge_raw_meta_domains


def _volume_meta() -> dict:
    return {
        "symbol": "AAPL",
        "timeframe": "15m",
        "asof_ts": 1709253600.0,
        "volume": {
            "value": {"regime": "NORMAL", "thin_fraction": 0.1},
            "asof_ts": 1709253600.0,
            "stale": False,
        },
        "provenance": ["volume:src"],
    }


def _technical_meta() -> dict:
    return {
        "symbol": "AAPL",
        "timeframe": "15m",
        "asof_ts": 1709253601.0,
        "technical": {
            "value": {"strength": 0.8, "bias": "BULLISH"},
            "asof_ts": 1709253601.0,
            "stale": False,
        },
        "provenance": ["tech:src"],
    }


def _news_meta() -> dict:
    return {
        "symbol": "AAPL",
        "timeframe": "15m",
        "asof_ts": 1709253602.0,
        "news": {
            "value": {"strength": 0.3, "bias": "BEARISH"},
            "asof_ts": 1709253602.0,
            "stale": True,
        },
        "provenance": ["news:src"],
    }


_DOMAIN_SOURCES = {
    "structure": "structure_artifact_json",
    "volume": "databento_watchlist_csv",
    "technical": "fmp_watchlist_json",
    "news": "benzinga_watchlist_json",
}


class TestA2MetaDomainVisibility:
    def test_all_domains_present(self) -> None:
        merged = merge_raw_meta_domains(
            volume_meta=_volume_meta(),
            technical_meta=_technical_meta(),
            news_meta=_news_meta(),
            domain_sources=_DOMAIN_SOURCES,
        )
        assert merged["meta_domains_present"] == ["volume", "technical", "news"]
        assert merged["meta_domains_missing"] == []

    def test_technical_missing(self) -> None:
        merged = merge_raw_meta_domains(
            volume_meta=_volume_meta(),
            technical_meta=None,
            news_meta=_news_meta(),
            domain_sources=_DOMAIN_SOURCES,
        )
        assert "technical" not in merged["meta_domains_present"]
        assert "technical" in merged["meta_domains_missing"]
        assert "volume" in merged["meta_domains_present"]
        assert "news" in merged["meta_domains_present"]

    def test_news_missing(self) -> None:
        merged = merge_raw_meta_domains(
            volume_meta=_volume_meta(),
            technical_meta=_technical_meta(),
            news_meta=None,
            domain_sources=_DOMAIN_SOURCES,
        )
        assert "news" not in merged["meta_domains_present"]
        assert "news" in merged["meta_domains_missing"]

    def test_both_optional_domains_missing(self) -> None:
        merged = merge_raw_meta_domains(
            volume_meta=_volume_meta(),
            technical_meta=None,
            news_meta=None,
            domain_sources=_DOMAIN_SOURCES,
        )
        assert merged["meta_domains_present"] == ["volume"]
        assert set(merged["meta_domains_missing"]) == {"technical", "news"}


# ---------------------------------------------------------------------------
# A3 – Plan-loader harmonization / structure_resolution_mode
# ---------------------------------------------------------------------------
from smc_integration.sources import structure_artifact_json


class TestA3StructureResolutionMode:
    def test_resolve_mode_none_when_no_artifacts(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACT_JSON", tmp_path / "nonexistent.json")
        monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", tmp_path / "empty_dir")

        mode = structure_artifact_json.resolve_artifact_mode("AAPL", "15m")
        assert mode == "none"

    def test_resolve_mode_manifest(self, monkeypatch, tmp_path: Path) -> None:
        artifact_dir = tmp_path / "reports" / "smc_structure_artifacts"
        artifact_dir.mkdir(parents=True)

        from smc_integration.structure_batch import write_structure_artifacts_from_workbook

        workbook = Path(__file__).resolve().parents[1] / "databento_volatility_production_20260307_114724.xlsx"
        write_structure_artifacts_from_workbook(
            workbook=workbook,
            timeframe="15m",
            symbols=["AAPL"],
            output_dir=artifact_dir,
            generated_at=1709253600.0,
        )

        monkeypatch.setattr(structure_artifact_json, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", artifact_dir)
        monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACT_JSON", tmp_path / "nonexistent.json")

        mode = structure_artifact_json.resolve_artifact_mode("AAPL", "15m")
        assert mode == "manifest"

    def test_resolve_mode_legacy_single(self, monkeypatch, tmp_path: Path) -> None:
        legacy_artifact = tmp_path / "smc_structure_artifact.json"
        legacy_artifact.write_text(json.dumps({
            "generated_at": 1709253600.0,
            "entries": [
                {
                    "symbol": "AAPL",
                    "timeframe": "15m",
                    "structure": {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []},
                }
            ],
        }), encoding="utf-8")

        monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACT_JSON", legacy_artifact)
        monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", tmp_path / "empty_manifests")

        mode = structure_artifact_json.resolve_artifact_mode("AAPL", "15m")
        assert mode == "legacy_single"

    def test_legacy_check_is_symbol_aware(self, monkeypatch, tmp_path: Path) -> None:
        """Legacy check must return 'none' for a symbol NOT in the legacy artifact."""
        legacy_artifact = tmp_path / "smc_structure_artifact.json"
        legacy_artifact.write_text(json.dumps({
            "generated_at": 1709253600.0,
            "entries": [
                {
                    "symbol": "AAPL",
                    "timeframe": "15m",
                    "structure": {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []},
                }
            ],
        }), encoding="utf-8")

        monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACT_JSON", legacy_artifact)
        monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", tmp_path / "empty_manifests")

        assert structure_artifact_json.resolve_artifact_mode("AAPL", "15m") == "legacy_single"
        assert structure_artifact_json.resolve_artifact_mode("USAR", "15m") == "none"

    def test_source_plan_contains_resolution_mode(self) -> None:
        from smc_integration.repo_sources import discover_composite_source_plan

        plan = discover_composite_source_plan(source="auto", symbol="AAPL", timeframe="15m")
        assert "structure_resolution_mode" in plan
        assert plan["structure_resolution_mode"] in {"manifest", "deterministic", "legacy_single", "none", "n/a"}
