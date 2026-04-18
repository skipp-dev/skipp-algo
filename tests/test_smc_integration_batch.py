from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import smc_integration.batch as batch


def _bundle(symbol: str, timeframe: str) -> dict:
    return {
        "source": {"name": "databento_watchlist_csv", "path_hint": "reports/databento_watchlist_top5_pre1530.csv", "capabilities": {}, "notes": []},
        "snapshot": {
            "symbol": symbol,
            "timeframe": timeframe,
            "structure": {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []},
            "meta": {"symbol": symbol, "timeframe": timeframe},
        },
        "dashboard_payload": {"symbol": symbol, "timeframe": timeframe},
        "pine_payload": {"symbol": symbol, "timeframe": timeframe},
    }


def test_build_snapshot_bundles_for_symbols_keeps_deterministic_order(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake(symbol: str, timeframe: str, *, source: str = "auto", generated_at: float | None = None) -> dict:
        del source, generated_at
        return _bundle(symbol, timeframe)

    monkeypatch.setattr(batch, "build_snapshot_bundle_for_symbol_timeframe", _fake)

    out = batch.build_snapshot_bundles_for_symbols(["nvda", "aapl", "msft"], "15m")
    assert [row["snapshot"]["symbol"] for row in out] == ["NVDA", "AAPL", "MSFT"]


def test_build_snapshot_bundles_for_symbols_deduplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _fake(symbol: str, timeframe: str, *, source: str = "auto", generated_at: float | None = None) -> dict:
        del source, generated_at
        calls.append(symbol)
        return _bundle(symbol, timeframe)

    monkeypatch.setattr(batch, "build_snapshot_bundle_for_symbol_timeframe", _fake)

    out = batch.build_snapshot_bundles_for_symbols(["AAPL", "aapl", "MSFT", "MSFT"], "15m")
    assert [row["snapshot"]["symbol"] for row in out] == ["AAPL", "MSFT"]
    assert calls == ["AAPL", "MSFT"]


def test_build_snapshot_bundles_for_symbols_is_deterministic_with_fixed_generated_at(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake(symbol: str, timeframe: str, *, source: str = "auto", generated_at: float | None = None) -> dict:
        payload = _bundle(symbol, timeframe)
        payload["snapshot"]["generated_at"] = generated_at
        return payload

    monkeypatch.setattr(batch, "build_snapshot_bundle_for_symbol_timeframe", _fake)

    one = batch.build_snapshot_bundles_for_symbols(["AAPL", "MSFT"], "15m", generated_at=1709254000.0)
    two = batch.build_snapshot_bundles_for_symbols(["AAPL", "MSFT"], "15m", generated_at=1709254000.0)
    assert one == two


def test_build_snapshot_bundles_for_symbols_bundle_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(batch, "build_snapshot_bundle_for_symbol_timeframe", lambda symbol, timeframe, **kwargs: _bundle(symbol, timeframe))
    out = batch.build_snapshot_bundles_for_symbols(["AAPL"], "15m")
    assert set(["source", "snapshot", "dashboard_payload", "pine_payload"]).issubset(set(out[0].keys()))


def test_write_snapshot_bundles_for_symbols_surfaces_failures(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def _fake(symbol: str, timeframe: str, *, source: str = "auto", generated_at: float | None = None) -> dict:
        del source, generated_at
        if symbol == "BAD":
            raise ValueError("bad symbol")
        return _bundle(symbol, timeframe)

    monkeypatch.setattr(batch, "build_snapshot_bundle_for_symbol_timeframe", _fake)

    manifest = batch.write_snapshot_bundles_for_symbols(["AAPL", "BAD"], "15m", output_dir=tmp_path, generated_at=1709254000.0)
    assert manifest["counts"]["symbols_requested"] == 2
    assert manifest["counts"]["symbols_built"] == 1
    assert manifest["counts"]["errors"] == 1
    assert manifest["errors"][0]["symbol"] == "BAD"


def test_write_snapshot_bundles_for_symbols_auto_keeps_composite_resolution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen_sources: list[str] = []

    def _fake(symbol: str, timeframe: str, *, source: str = "auto", generated_at: float | None = None) -> dict:
        del generated_at
        seen_sources.append(source)
        return _bundle(symbol, timeframe)

    monkeypatch.setattr(batch, "build_snapshot_bundle_for_symbol_timeframe", _fake)

    manifest = batch.write_snapshot_bundles_for_symbols(
        ["AAPL"],
        "15m",
        source="auto",
        output_dir=tmp_path,
        generated_at=1709254000.0,
    )

    assert seen_sources == ["auto"]
    assert manifest["source"]["selected"] == "structure_artifact_json"


def test_load_symbols_from_json_watchlist_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source_path = tmp_path / "fmp_watchlist_snapshot.json"
    source_path.write_text(
        json.dumps(
            {
                "symbols": [
                    {"symbol": "AAPL"},
                    {"symbol": "msft"},
                    {"symbol": "AAPL"},
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(batch, "_descriptor_for_source_name", lambda name: SimpleNamespace(path_hint=str(source_path)))

    symbols = batch.load_symbols_from_watchlist_source(source="fmp_watchlist_json")
    assert symbols == ["AAPL", "MSFT"]


# ── pure helper coverage ─────────────────────────────────────────


class TestNormalizeSymbols:
    def test_deduplicates_and_uppercases(self) -> None:
        assert batch._normalize_symbols(["aapl", "AAPL", "msft"]) == ["AAPL", "MSFT"]

    def test_strips_whitespace(self) -> None:
        assert batch._normalize_symbols(["  AAPL  ", " msft"]) == ["AAPL", "MSFT"]

    def test_empty_strings_dropped(self) -> None:
        assert batch._normalize_symbols(["", "  ", "AAPL"]) == ["AAPL"]

    def test_empty_list(self) -> None:
        assert batch._normalize_symbols([]) == []


class TestBundleFileName:
    def test_format(self) -> None:
        assert batch._bundle_file_name("aapl", "15m") == "AAPL_15m.bundle.json"

    def test_strips(self) -> None:
        assert batch._bundle_file_name("  MSFT ", " 1D ") == "MSFT_1D.bundle.json"


class TestManifestFileName:
    def test_format(self) -> None:
        assert batch._manifest_file_name("15m") == "manifest_15m.json"

    def test_strips(self) -> None:
        assert batch._manifest_file_name("  1D ") == "manifest_1D.json"


class TestHasStructure:
    def test_true_when_bos_present(self) -> None:
        assert batch._has_structure({"structure": {"bos": [{"dir": "up"}], "orderblocks": [], "fvg": [], "liquidity_sweeps": []}})

    def test_false_when_all_empty(self) -> None:
        assert not batch._has_structure({"structure": {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []}})

    def test_false_when_no_structure_key(self) -> None:
        assert not batch._has_structure({})

    def test_false_when_structure_is_not_dict(self) -> None:
        assert not batch._has_structure({"structure": "invalid"})


class TestHasMeta:
    def test_true_when_meta_is_dict(self) -> None:
        assert batch._has_meta({"meta": {"symbol": "AAPL"}})

    def test_false_when_meta_absent(self) -> None:
        assert not batch._has_meta({})

    def test_false_when_meta_is_not_dict(self) -> None:
        assert not batch._has_meta({"meta": "invalid"})


class TestCategoryFlags:
    def test_from_dashboard_payload(self) -> None:
        bundle = {
            "dashboard_payload": {
                "structure_coverage": {
                    "has_bos": True,
                    "has_orderblocks": False,
                    "has_fvg": True,
                    "has_liquidity_sweeps": False,
                }
            }
        }
        flags = batch._category_flags(bundle)
        assert flags["has_bos"] is True
        assert flags["has_orderblocks"] is False
        assert flags["has_fvg"] is True

    def test_from_snapshot_fallback(self) -> None:
        bundle = {
            "snapshot": {
                "structure": {
                    "bos": [{"dir": "up"}],
                    "orderblocks": [],
                    "fvg": [],
                    "liquidity_sweeps": [],
                }
            }
        }
        flags = batch._category_flags(bundle)
        assert flags["has_bos"] is True
        assert flags["has_orderblocks"] is False

    def test_empty_bundle_returns_all_false(self) -> None:
        flags = batch._category_flags({})
        assert all(v is False for v in flags.values())


class TestBuildSnapshotManifest:
    def test_manifest_shape(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(batch, "build_snapshot_bundle_for_symbol_timeframe", lambda *a, **kw: _bundle("AAPL", "15m"))

        bundles = [_bundle("AAPL", "15m")]
        manifest = batch.build_snapshot_manifest(
            symbols_requested=["AAPL"],
            symbols_built=["AAPL"],
            timeframe="15m",
            source_name="structure_artifact_json",
            generated_at=1709254000.0,
            output_dir=tmp_path,
            bundles=bundles,
            errors=[],
        )
        assert manifest["timeframe"] == "15m"
        assert manifest["counts"]["symbols_requested"] == 1
        assert manifest["counts"]["symbols_built"] == 1
        assert manifest["counts"]["errors"] == 0
        assert isinstance(manifest["bundles"], list)
        assert manifest["bundles"][0]["symbol"] == "AAPL"


class TestBuildSnapshotBundlesRejectsEmpty:
    def test_raises_on_empty(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            batch.build_snapshot_bundles_for_symbols([], "15m")

    def test_raises_on_whitespace_only(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            batch.build_snapshot_bundles_for_symbols(["  ", ""], "15m")


class TestLoadSymbolsFromSource:
    def test_alias(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        source_path = tmp_path / "fmp_watchlist_snapshot.json"
        source_path.write_text(
            json.dumps({"symbols": [{"symbol": "TSLA"}]}),
            encoding="utf-8",
        )
        monkeypatch.setattr(batch, "_descriptor_for_source_name", lambda name: SimpleNamespace(path_hint=str(source_path)))
        assert batch.load_symbols_from_source("fmp_watchlist_json") == ["TSLA"]


class TestResolveStructureSourceName:
    def test_auto_resolves(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(batch, "select_best_source", lambda: SimpleNamespace(name="structure_artifact_json"))
        assert batch._resolve_structure_source_name("auto") == "structure_artifact_json"

    def test_explicit_passthrough(self) -> None:
        assert batch._resolve_structure_source_name("fmp_watchlist_json") == "fmp_watchlist_json"


class TestResolveWatchlistSourceName:
    def test_auto_resolves(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(batch, "select_best_volume_source", lambda: SimpleNamespace(name="databento_watchlist_csv"))
        assert batch._resolve_watchlist_source_name("auto") == "databento_watchlist_csv"

    def test_explicit_passthrough(self) -> None:
        assert batch._resolve_watchlist_source_name("tradingview_watchlist_json") == "tradingview_watchlist_json"


class TestDescriptorForSourceName:
    def test_unknown_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(batch, "discover_repo_sources", lambda: [SimpleNamespace(name="src_a")])
        with pytest.raises(ValueError, match="unknown source"):
            batch._descriptor_for_source_name("nonexistent")


class TestLoadSymbolsFromWatchlistCsv:
    def test_csv_source_missing_file_raises(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(batch, "_resolve_watchlist_source_name", lambda s: "databento_watchlist_csv")
        monkeypatch.setattr(batch, "_descriptor_for_source_name", lambda n: SimpleNamespace(path_hint="nonexistent.csv"))
        with pytest.raises(FileNotFoundError, match="watchlist source not found"):
            batch.load_symbols_from_watchlist_source(source="databento_watchlist_csv")

    def test_unsupported_source_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(batch, "_resolve_watchlist_source_name", lambda s: "unknown_source")
        monkeypatch.setattr(batch, "_descriptor_for_source_name", lambda n: SimpleNamespace(path_hint="x.txt"))
        with pytest.raises(NotImplementedError, match="does not support"):
            batch.load_symbols_from_watchlist_source(source="unknown_source")
