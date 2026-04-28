from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from smc_integration import structure_batch as structure_batch_module
from smc_integration.structure_batch import write_structure_artifacts_from_workbook
from tests.helpers.smc_test_artifacts import make_minimal_workbook

ROOT = Path(__file__).resolve().parents[1]


def _sample_symbols(workbook: Path, limit: int = 2) -> list[str]:
    daily = pd.read_excel(workbook, sheet_name="daily_bars")
    symbols = sorted({str(item).strip().upper() for item in daily["symbol"].dropna().tolist() if str(item).strip()})
    if len(symbols) < limit:
        raise AssertionError("workbook daily_bars must contain enough symbols")
    return symbols[:limit]


def _write_synthetic_export_bundle(bundle_dir: Path, *, symbol: str) -> Path:
    return _write_bundle_frames(
        bundle_dir,
        prefix="databento_volatility_production_20990101_000000",
        frames={
            "full_universe_second_detail_open": pd.DataFrame(
                {
                    "symbol": [symbol] * 6,
                    "timestamp": pd.date_range("2026-03-06 14:30:00+00:00", periods=6, freq="15min"),
                    "open": [100.0] * 6,
                    "high": [100.0] * 6,
                    "low": [100.0] * 6,
                    "close": [100.0] * 6,
                    "volume": [1.0] * 6,
                }
            ),
        },
    )


def _write_bundle_frames(bundle_dir: Path, *, prefix: str, frames: dict[str, pd.DataFrame]) -> Path:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = bundle_dir / f"{prefix}_manifest.json"
    manifest_path.write_text("{}\n", encoding="utf-8")
    for name, frame in frames.items():
        frame.to_parquet(bundle_dir / f"{prefix}__{name}.parquet", index=False)
    return manifest_path


def test_structure_batch_writes_one_artifact_per_symbol(tmp_path: Path) -> None:
    workbook = make_minimal_workbook(tmp_path)
    symbols = _sample_symbols(workbook, limit=2)
    output_dir = tmp_path / "output"

    manifest = write_structure_artifacts_from_workbook(
        workbook=workbook,
        timeframe="1D",
        symbols=symbols,
        output_dir=output_dir,
        generated_at=1709254000.0,
    )

    assert manifest["counts"]["symbols_requested"] == 2
    assert manifest["counts"]["artifacts_written"] == 2
    assert manifest["counts"]["errors"] == 0

    for symbol in symbols:
        path = output_dir / f"{symbol}_1D.structure.json"
        assert path.exists()


def test_structure_batch_file_naming_is_deterministic(tmp_path: Path) -> None:
    workbook = make_minimal_workbook(tmp_path)
    symbols = _sample_symbols(workbook, limit=2)
    output_dir = tmp_path / "output"

    write_structure_artifacts_from_workbook(
        workbook=workbook,
        timeframe="1D",
        symbols=symbols,
        output_dir=output_dir,
        generated_at=1709254000.0,
    )

    names = sorted(item.name for item in output_dir.glob("*.structure.json"))
    assert names == sorted([f"{symbols[0]}_1D.structure.json", f"{symbols[1]}_1D.structure.json"])


def test_structure_batch_is_stable_for_fixed_generated_at(tmp_path: Path) -> None:
    workbook = make_minimal_workbook(tmp_path)
    symbols = _sample_symbols(workbook, limit=1)

    out_one = tmp_path / "stable_one"
    out_two = tmp_path / "stable_two"

    write_structure_artifacts_from_workbook(
        workbook=workbook,
        timeframe="1D",
        symbols=symbols,
        output_dir=out_one,
        generated_at=1709254000.0,
    )
    write_structure_artifacts_from_workbook(
        workbook=workbook,
        timeframe="1D",
        symbols=symbols,
        output_dir=out_two,
        generated_at=1709254000.0,
    )

    one_payload = json.loads((out_one / f"{symbols[0]}_1D.structure.json").read_text(encoding="utf-8"))
    two_payload = json.loads((out_two / f"{symbols[0]}_1D.structure.json").read_text(encoding="utf-8"))
    assert one_payload == two_payload


def _make_populated_daily_workbook(
    tmp_path: Path, *, symbol: str = "AAPL", num_bars: int = 25
) -> Path:
    """Produce a workbook whose ``daily_bars`` sheet contains an oscillating
    price path + explicit BULL-FVG gap bars, such that
    ``build_explicit_structure_from_bars(timeframe="1D")`` yields at least
    one non-empty category (bos and/or fvg). Reuses the canonical gap pattern
    from ``test_explicit_structure_from_bars.py`` (bar1.high=100, bar3.low=103)
    anchored inside a 25-day oscillation to also produce swings/BOS.
    """
    assert num_bars >= 20, "populated fixture needs >= 20 bars to produce structures"
    rows: list[dict] = []
    # Oscillating baseline to create swing highs/lows (BOS candidates).
    for idx in range(num_bars):
        ts = pd.Timestamp("2026-03-01", tz="UTC") + pd.Timedelta(days=idx)
        phase = idx % 6
        # Zig-zag in 6-bar waves around a rising mean -> swing structure.
        base = 100.0 + idx * 0.3
        if phase in (0, 1):
            high = base + 2.0
            low = base - 0.5
            close = base + 1.5
            open_ = base + 0.1
        elif phase in (2, 3):
            high = base + 0.5
            low = base - 2.0
            close = base - 1.5
            open_ = base - 0.1
        else:
            high = base + 1.2
            low = base - 1.2
            close = base + 0.8
            open_ = base - 0.2
        rows.append(
            {
                "trade_date": ts.strftime("%Y-%m-%d"),
                "symbol": symbol,
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": 1000.0 + idx,
            }
        )
    # Inject a canonical 3-bar BULL-FVG (bar[n-3].high < bar[n-1].low) near the
    # end to guarantee fvg detection regardless of zig-zag edge cases.
    fvg_anchor = pd.Timestamp("2026-03-01", tz="UTC") + pd.Timedelta(days=num_bars - 3)
    rows[-3] = {
        "trade_date": fvg_anchor.strftime("%Y-%m-%d"),
        "symbol": symbol,
        "open": 97.0, "high": 100.0, "low": 95.0, "close": 99.0,
        "volume": 1500.0,
    }
    rows[-2] = {
        "trade_date": (fvg_anchor + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
        "symbol": symbol,
        "open": 100.0, "high": 101.0, "low": 98.0, "close": 100.5,
        "volume": 1600.0,
    }
    rows[-1] = {
        "trade_date": (fvg_anchor + pd.Timedelta(days=2)).strftime("%Y-%m-%d"),
        "symbol": symbol,
        "open": 104.0, "high": 108.0, "low": 103.0, "close": 107.0,
        "volume": 1700.0,
    }

    workbook = (
        tmp_path
        / "artifacts"
        / "smc_microstructure_exports"
        / "databento_volatility_production_workbook.xlsx"
    )
    workbook.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="daily_bars", index=False)
    return workbook


def _assert_coverage_invariants(payload: dict) -> None:
    """Shared invariant: coverage flags + diagnostic counts mirror the actual
    structure lists. Holds regardless of whether structures are empty or not.
    """
    structure = payload["structure"]
    diagnostics = payload["diagnostics"]
    auxiliary = payload["auxiliary"]
    coverage = payload["coverage"]

    assert set(structure.keys()) == {"bos", "orderblocks", "fvg", "liquidity_sweeps"}
    assert payload["coverage_mode"] in {"full", "partial", "none"}
    assert coverage["has_bos"] == bool(structure["bos"])
    assert coverage["has_orderblocks"] == bool(structure["orderblocks"])
    assert coverage["has_fvg"] == bool(structure["fvg"])
    assert coverage["has_liquidity_sweeps"] == bool(structure["liquidity_sweeps"])
    assert diagnostics["counts"]["bos"] == len(structure["bos"])
    assert diagnostics["counts"]["liquidity_lines"] == len(auxiliary.get("liquidity_lines", []))
    assert diagnostics["structure_profile_used"] == "hybrid_default"
    assert diagnostics["event_logic_version"] == "v2"


def test_structure_batch_keeps_categories_honest_when_empty(tmp_path: Path) -> None:
    """Empty-structure case: 2-bar minimal workbook cannot produce BOS/FVG,
    so all structure lists remain empty. The invariant ``has_X == bool(X)``
    must still hold — this guards against coverage flags drifting to True
    when lists are empty (e.g. stale defaults, copy-paste bugs).
    """
    workbook = make_minimal_workbook(tmp_path)
    symbols = _sample_symbols(workbook, limit=1)
    output_dir = tmp_path / "output"

    write_structure_artifacts_from_workbook(
        workbook=workbook,
        timeframe="1D",
        symbols=symbols,
        output_dir=output_dir,
        generated_at=1709254000.0,
    )

    payload = json.loads((output_dir / f"{symbols[0]}_1D.structure.json").read_text(encoding="utf-8"))
    _assert_coverage_invariants(payload)
    # Pin the empty-case expectation explicitly: 2 bars cannot yield structures.
    assert payload["structure"]["bos"] == []
    assert payload["structure"]["fvg"] == []
    assert payload["coverage"]["has_bos"] is False
    assert payload["coverage"]["has_fvg"] is False


def test_structure_batch_keeps_categories_honest_when_populated(tmp_path: Path) -> None:
    """Populated-structure case: 25-bar workbook with oscillating swings and
    an explicit BULL-FVG triplet must yield at least one non-empty category.
    Without this test, the invariant test is a tautology (empty list == empty
    list trivially). This pins ``has_X == bool(X)`` against the TRUE branch
    of the bool, which the empty fixture cannot exercise.
    """
    symbol = "AAPL"
    workbook = _make_populated_daily_workbook(tmp_path, symbol=symbol, num_bars=25)
    output_dir = tmp_path / "output"

    write_structure_artifacts_from_workbook(
        workbook=workbook,
        timeframe="1D",
        symbols=[symbol],
        output_dir=output_dir,
        generated_at=1709254000.0,
    )

    payload = json.loads((output_dir / f"{symbol}_1D.structure.json").read_text(encoding="utf-8"))
    _assert_coverage_invariants(payload)

    # Guarantee the populated branch actually fires — otherwise this test
    # would regress silently to a tautology identical to the _when_empty case.
    structure = payload["structure"]
    any_populated = any(
        bool(structure[key]) for key in ("bos", "orderblocks", "fvg", "liquidity_sweeps")
    )
    assert any_populated, (
        "populated fixture produced zero structures — fixture drift suspected. "
        "Bars were designed to trigger BULL-FVG at tail and swing BOS mid-series. "
        f"Structure payload: {structure}"
    )


def test_structure_batch_records_selected_profile_in_source(tmp_path: Path) -> None:
    workbook = make_minimal_workbook(tmp_path)
    symbols = _sample_symbols(workbook, limit=1)
    output_dir = tmp_path / "output"

    write_structure_artifacts_from_workbook(
        workbook=workbook,
        timeframe="1D",
        symbols=symbols,
        output_dir=output_dir,
        generated_at=1709254000.0,
        structure_profile="conservative",
    )

    payload = json.loads((output_dir / f"{symbols[0]}_1D.structure.json").read_text(encoding="utf-8"))
    assert payload["source"]["structure_profile"] == "conservative"
    assert payload["diagnostics"]["structure_profile_used"] == "conservative"


def test_structure_batch_explicit_workbook_ignores_autoresolved_bundle(monkeypatch, tmp_path: Path) -> None:
    workbook = make_minimal_workbook(tmp_path)
    symbol = _sample_symbols(workbook, limit=1)[0]
    baseline_dir = tmp_path / "baseline"
    controlled_dir = tmp_path / "controlled"
    synthetic_bundle = tmp_path / "bundle"

    _write_synthetic_export_bundle(synthetic_bundle, symbol=symbol)

    write_structure_artifacts_from_workbook(
        workbook=workbook,
        timeframe="1D",
        symbols=[symbol],
        output_dir=baseline_dir,
        generated_at=1709254000.0,
    )

    def _resolved_inputs(**_: object) -> dict[str, object]:
        return {
            "workbook_path": workbook,
            "export_bundle_root": synthetic_bundle,
            "structure_artifacts_dir": controlled_dir,
            "single_structure_artifact_path": None,
            "resolution_mode": "explicit",
            "errors": [],
            "warnings": [],
            "resolution_detail": {
                "workbook": "explicit",
                "export_bundle_root": "canonical",
            },
        }

    monkeypatch.setattr(structure_batch_module, "resolve_structure_artifact_inputs", _resolved_inputs)

    write_structure_artifacts_from_workbook(
        workbook=workbook,
        timeframe="1D",
        symbols=[symbol],
        output_dir=controlled_dir,
        generated_at=1709254000.0,
    )

    baseline_payload = json.loads((baseline_dir / f"{symbol}_1D.structure.json").read_text(encoding="utf-8"))
    controlled_payload = json.loads((controlled_dir / f"{symbol}_1D.structure.json").read_text(encoding="utf-8"))

    assert controlled_payload == baseline_payload
    assert controlled_payload["source"]["canonical_upstream"] == "workbook_fallback"


def test_structure_batch_explicit_bundle_keeps_bundle_precedence(tmp_path: Path) -> None:
    workbook = make_minimal_workbook(tmp_path)
    symbol = _sample_symbols(workbook, limit=1)[0]
    output_dir = tmp_path / "bundle_precedence"
    synthetic_bundle = tmp_path / "bundle"

    _write_synthetic_export_bundle(synthetic_bundle, symbol=symbol)

    write_structure_artifacts_from_workbook(
        workbook=workbook,
        export_bundle_root=synthetic_bundle,
        timeframe="15m",
        symbols=[symbol],
        output_dir=output_dir,
        generated_at=1709254000.0,
    )

    payload = json.loads((output_dir / f"{symbol}_15m.structure.json").read_text(encoding="utf-8"))

    assert payload["source"]["canonical_upstream"] == "canonical_export_bundle"
    assert payload["coverage"]["has_bos"] is False
    assert payload["coverage"]["has_orderblocks"] is False
    assert payload["coverage"]["has_fvg"] is False
    assert payload["coverage"]["has_liquidity_sweeps"] is False


def test_canonical_intraday_loader_requires_intraday_bundle_frame(tmp_path: Path) -> None:
    symbol = "AAPL"
    older_prefix = "databento_volatility_production_20260310_090000"
    newer_prefix = "databento_volatility_production_incremental_20260310_091000"

    _write_bundle_frames(
        tmp_path,
        prefix=older_prefix,
        frames={
            "full_universe_second_detail_open": pd.DataFrame(
                {
                    "symbol": [symbol],
                    "timestamp": ["2026-03-06T14:30:00Z"],
                    "open": [101.0],
                    "high": [102.0],
                    "low": [100.0],
                    "close": [101.5],
                    "volume": [2.0],
                }
            ),
        },
    )
    _write_bundle_frames(
        tmp_path,
        prefix=newer_prefix,
        frames={
            "daily_bars": pd.DataFrame(
                {
                    "trade_date": ["2026-03-06"],
                    "symbol": [symbol],
                    "open": [91.0],
                    "high": [92.0],
                    "low": [90.0],
                    "close": [91.5],
                }
            ),
        },
    )
    (tmp_path / f"{older_prefix}_manifest.json").touch()
    (tmp_path / f"{newer_prefix}_manifest.json").touch()

    bars = structure_batch_module._load_symbol_bars_from_canonical_exports(symbol, "5m", tmp_path)

    assert bars is not None
    assert len(bars) == 1
    assert float(bars.loc[0, "open"]) == 101.0
    assert float(bars.loc[0, "volume"]) == 2.0


# ── pure helper coverage ─────────────────────────────────────────

from smc_integration.structure_batch import (
    StructureArtifactRow,
    _artifact_file_name,
    _auxiliary_from_payload,
    _canonical_structure,
    _counts_from_payload,
    _coverage_from_structure,
    _manifest_file_name,
    _normalize_symbol,
    _normalize_symbols,
    _relative_repo_path,
    _row_from_existing_artifact,
    build_structure_artifact_manifest,
)


class TestNormalizeSymbol:
    def test_basic(self) -> None:
        assert _normalize_symbol("aapl") == "AAPL"

    def test_strips(self) -> None:
        assert _normalize_symbol("  msft  ") == "MSFT"

    def test_tuple_input(self) -> None:
        assert _normalize_symbol(("TSLA",)) == "TSLA"

    def test_parenthesized_tuple_string(self) -> None:
        assert _normalize_symbol("('NVDA', '15m')") == "NVDA"

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            _normalize_symbol("")


class TestNormalizeSymbols:
    def test_dedup_and_order(self) -> None:
        assert _normalize_symbols(["aapl", "AAPL", "msft"]) == ["AAPL", "MSFT"]

    def test_empty(self) -> None:
        assert _normalize_symbols([]) == []


class TestArtifactFileName:
    def test_format(self) -> None:
        assert _artifact_file_name("AAPL", "15m") == "AAPL_15m.structure.json"


class TestManifestFileName:
    def test_format(self) -> None:
        assert _manifest_file_name("15m") == "manifest_15m.json"


class TestCoverageFromStructure:
    def test_full(self) -> None:
        structure = {"bos": [1], "orderblocks": [2], "fvg": [3], "liquidity_sweeps": [4]}
        cov = _coverage_from_structure(structure, mode="full")
        assert cov["mode"] == "full"
        assert all(cov[f"has_{k}"] for k in ("bos", "orderblocks", "fvg", "liquidity_sweeps"))

    def test_empty(self) -> None:
        structure = {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []}
        cov = _coverage_from_structure(structure, mode="none")
        assert not any(cov[f"has_{k}"] for k in ("bos", "orderblocks", "fvg", "liquidity_sweeps"))


class TestCanonicalStructure:
    def test_extracts_keys(self) -> None:
        payload = {"bos": [1], "orderblocks": [2], "fvg": [3], "liquidity_sweeps": [4], "extra": "ignored"}
        result = _canonical_structure(payload)
        assert set(result.keys()) == {"bos", "orderblocks", "fvg", "liquidity_sweeps"}
        assert result["bos"] == [1]

    def test_defaults_empty(self) -> None:
        result = _canonical_structure({})
        assert all(v == [] for v in result.values())


class TestAuxiliaryFromPayload:
    def test_extracts_auxiliary(self) -> None:
        payload = {"auxiliary": {"liquidity_lines": [1], "session_ranges": [2]}}
        aux = _auxiliary_from_payload(payload)
        assert aux["liquidity_lines"] == [1]
        assert aux["session_ranges"] == [2]
        assert aux["session_pivots"] == []

    def test_missing_auxiliary(self) -> None:
        aux = _auxiliary_from_payload({})
        assert all(isinstance(v, (list, dict)) for v in aux.values())


class TestCountsFromPayload:
    def test_counts(self) -> None:
        structure = {"bos": [1, 2], "orderblocks": [], "fvg": [3], "liquidity_sweeps": []}
        auxiliary = {"liquidity_lines": [1], "session_ranges": [], "session_pivots": [], "broken_fractal_signals": []}
        counts = _counts_from_payload(structure, auxiliary)
        assert counts["bos"] == 2
        assert counts["fvg"] == 1
        assert counts["liquidity_lines"] == 1


class TestRelativeRepoPath:
    def test_inside_repo(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        path = repo / "reports" / "test.json"
        result = _relative_repo_path(path)
        assert result == "reports/test.json"

    def test_outside_repo_returns_posix(self, tmp_path: Path) -> None:
        result = _relative_repo_path(tmp_path / "foo.json")
        assert "foo.json" in result


class TestRowFromExistingArtifact:
    def test_valid_artifact(self, tmp_path: Path) -> None:
        artifact = {
            "coverage_mode": "full",
            "coverage": {"has_bos": True, "has_orderblocks": True, "has_fvg": True, "has_liquidity_sweeps": True},
            "structure": {"bos": [1], "orderblocks": [2], "fvg": [3], "liquidity_sweeps": [4]},
            "diagnostics": {
                "structure_profile_used": "hybrid_default",
                "event_logic_version": "v2",
                "counts": {"bos": 1, "orderblocks": 1, "fvg": 1, "liquidity_sweeps": 1},
                "warnings": [],
            },
        }
        path = tmp_path / "AAPL_15m.structure.json"
        path.write_text(json.dumps(artifact), encoding="utf-8")

        row = _row_from_existing_artifact(path, "AAPL", "15m")
        assert row is not None
        assert row.symbol == "AAPL"
        assert row.has_bos is True
        assert row.bos_count == 1
        assert row.coverage_mode == "full"

    def test_invalid_json_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("not json", encoding="utf-8")
        assert _row_from_existing_artifact(path, "X", "15m") is None

    def test_non_dict_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "list.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        assert _row_from_existing_artifact(path, "X", "15m") is None


class TestBuildStructureArtifactManifest:
    def test_manifest_shape(self) -> None:
        row = StructureArtifactRow(
            symbol="AAPL",
            timeframe="15m",
            artifact_path="reports/AAPL_15m.structure.json",
            structure_profile_used="hybrid_default",
            event_logic_version="v2",
            coverage_mode="full",
            has_bos=True,
            has_orderblocks=True,
            has_fvg=True,
            has_liquidity_sweeps=True,
            bos_count=5,
            orderblocks_count=3,
            fvg_count=2,
            liquidity_sweeps_count=1,
            warnings_count=0,
        )
        manifest = build_structure_artifact_manifest(
            timeframe="15m",
            generated_at=1709254000.0,
            workbook=None,
            export_bundle_root=None,
            artifacts=[row],
            errors=[],
            warnings=[],
            resolution_mode="canonical",
            symbols_requested=["AAPL"],
        )
        assert manifest["timeframe"] == "15m"
        assert manifest["counts"]["artifacts_written"] == 1
        assert manifest["coverage_summary"]["symbols_with_bos"] == 1
        assert manifest["profile_summary"]["hybrid_default"] == 1
        assert "v2" in manifest["event_logic_versions"]


class TestDeriveSymbolsFromWorkbook:
    def test_raises_when_no_symbol_column(self) -> None:
        from smc_integration.structure_batch import _derive_symbols_from_workbook

        df = pd.DataFrame({"other": ["x"]})
        with pytest.raises(ValueError, match="missing symbol column"):
            _derive_symbols_from_workbook(df)

    def test_raises_when_all_empty(self) -> None:
        from smc_integration.structure_batch import _derive_symbols_from_workbook

        df = pd.DataFrame({"symbol": ["", "  "]})
        with pytest.raises(ValueError, match="no symbols found"):
            _derive_symbols_from_workbook(df)

    def test_returns_deduplicated(self) -> None:
        from smc_integration.structure_batch import _derive_symbols_from_workbook

        df = pd.DataFrame({"symbol": ["aapl", "AAPL", "msft"]})
        assert _derive_symbols_from_workbook(df) == ["AAPL", "MSFT"]


class TestLoadSymbolBarsFromCanonicalExports:
    def test_none_export_dir_returns_none(self) -> None:
        from smc_integration.structure_batch import _load_symbol_bars_from_canonical_exports

        assert _load_symbol_bars_from_canonical_exports("AAPL", "15m", None) is None

    def test_load_bundle_exception_returns_none(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from smc_integration.structure_batch import _load_symbol_bars_from_canonical_exports

        monkeypatch.setattr(structure_batch_module, "load_export_bundle", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
        assert _load_symbol_bars_from_canonical_exports("AAPL", "15m", tmp_path) is None

    def test_daily_bars_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from smc_integration.structure_batch import _load_symbol_bars_from_canonical_exports

        df = pd.DataFrame({
            "symbol": ["AAPL", "AAPL"],
            "trade_date": ["2025-01-10", "2025-01-11"],
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
        })
        monkeypatch.setattr(
            structure_batch_module,
            "load_export_bundle",
            lambda *a, **kw: {"frames": {"daily_bars": df}},
        )
        result = _load_symbol_bars_from_canonical_exports("AAPL", "1D", tmp_path)
        assert result is not None
        assert len(result) == 2
        assert list(result.columns) == ["symbol", "timestamp", "open", "high", "low", "close"]

    def test_daily_bars_empty_symbol_returns_none(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from smc_integration.structure_batch import _load_symbol_bars_from_canonical_exports

        df = pd.DataFrame({
            "symbol": ["MSFT"],
            "trade_date": ["2025-01-10"],
            "open": [100.0],
            "high": [102.0],
            "low": [99.0],
            "close": [101.0],
        })
        monkeypatch.setattr(
            structure_batch_module,
            "load_export_bundle",
            lambda *a, **kw: {"frames": {"daily_bars": df}},
        )
        assert _load_symbol_bars_from_canonical_exports("AAPL", "1D", tmp_path) is None

    def test_daily_bars_empty_frame_returns_none(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from smc_integration.structure_batch import _load_symbol_bars_from_canonical_exports

        monkeypatch.setattr(
            structure_batch_module,
            "load_export_bundle",
            lambda *a, **kw: {"frames": {"daily_bars": pd.DataFrame()}},
        )
        assert _load_symbol_bars_from_canonical_exports("AAPL", "1D", tmp_path) is None

    def test_intraday_empty_symbol_returns_none(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from smc_integration.structure_batch import _load_symbol_bars_from_canonical_exports

        df = pd.DataFrame({
            "symbol": ["MSFT"],
            "timestamp": ["2025-01-10T14:30:00Z"],
            "open": [100.0],
            "high": [102.0],
            "low": [99.0],
            "close": [101.0],
            "volume": [500.0],
        })
        monkeypatch.setattr(
            structure_batch_module,
            "load_export_bundle",
            lambda *a, **kw: {"frames": {"full_universe_second_detail_open": df}},
        )
        assert _load_symbol_bars_from_canonical_exports("AAPL", "15m", tmp_path) is None

    def test_intraday_no_volume_column(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from smc_integration.structure_batch import _load_symbol_bars_from_canonical_exports

        df = pd.DataFrame({
            "symbol": ["AAPL"],
            "timestamp": ["2025-01-10T14:30:00Z"],
            "open": [100.0],
            "high": [102.0],
            "low": [99.0],
            "close": [101.0],
        })
        monkeypatch.setattr(
            structure_batch_module,
            "load_export_bundle",
            lambda *a, **kw: {"frames": {"full_universe_second_detail_open": df}},
        )
        result = _load_symbol_bars_from_canonical_exports("AAPL", "15m", tmp_path)
        assert result is not None
        assert "volume" not in result.columns


class TestExistingArtifactRows:
    def test_skips_missing_files(self, tmp_path: Path) -> None:
        from smc_integration.structure_batch import _existing_artifact_rows

        rows = _existing_artifact_rows(tmp_path, ["AAPL", "MSFT"], "15m")
        assert rows == []

    def test_collects_valid_artifacts(self, tmp_path: Path) -> None:
        from smc_integration.structure_batch import _existing_artifact_rows

        artifact = {
            "coverage_mode": "partial",
            "coverage": {"has_bos": True, "has_orderblocks": False, "has_fvg": False, "has_liquidity_sweeps": False},
            "structure": {"bos": [1]},
            "diagnostics": {"counts": {"bos": 1}, "warnings": []},
        }
        path = tmp_path / "AAPL_15m.structure.json"
        path.write_text(json.dumps(artifact), encoding="utf-8")
        rows = _existing_artifact_rows(tmp_path, ["AAPL", "MSFT"], "15m")
        assert len(rows) == 1
        assert rows[0].symbol == "AAPL"


class TestLoadSymbolBarsFromWorkbook:
    def test_missing_symbol_raises(self, tmp_path: Path) -> None:
        from smc_integration.structure_batch import _load_symbol_bars_from_workbook

        wb = make_minimal_workbook(tmp_path)
        with pytest.raises(ValueError, match="not present"):
            _load_symbol_bars_from_workbook(wb, "NONEXIST")

    def test_workbook_volume_column(self, tmp_path: Path) -> None:
        from smc_integration.structure_batch import _load_symbol_bars_from_workbook

        wb = make_minimal_workbook(tmp_path)
        symbols = _sample_symbols(wb, limit=1)
        result = _load_symbol_bars_from_workbook(wb, symbols[0])
        assert not result.empty
        assert "timestamp" in result.columns


class TestLoadSymbolBarsFromWorkbookNoVolume:
    def test_no_volume_column(self, tmp_path: Path) -> None:
        from smc_integration.structure_batch import _load_symbol_bars_from_workbook

        wb_path = tmp_path / "wb.xlsx"
        rows = [
            {"trade_date": "2026-03-05", "symbol": "AAPL", "open": 100, "high": 101, "low": 99, "close": 100.5},
            {"trade_date": "2026-03-06", "symbol": "AAPL", "open": 101, "high": 102, "low": 100, "close": 101.2},
        ]
        with pd.ExcelWriter(wb_path, engine="openpyxl") as writer:
            pd.DataFrame(rows).to_excel(writer, sheet_name="daily_bars", index=False)
        result = _load_symbol_bars_from_workbook(wb_path, "AAPL")
        assert not result.empty
        assert "volume" not in result.columns

    def test_no_usable_ohlc_raises(self, tmp_path: Path) -> None:
        from smc_integration.structure_batch import _load_symbol_bars_from_workbook

        wb_path = tmp_path / "wb.xlsx"
        rows = [{"trade_date": None, "symbol": "AAPL", "open": None, "high": None, "low": None, "close": None}]
        with pd.ExcelWriter(wb_path, engine="openpyxl") as writer:
            pd.DataFrame(rows).to_excel(writer, sheet_name="daily_bars", index=False)
        with pytest.raises(ValueError, match="no usable OHLC"):
            _load_symbol_bars_from_workbook(wb_path, "AAPL")


class TestLoadSymbolBarsFromCanonicalExportsReturnNone:
    def test_no_intraday_returns_none(self, monkeypatch) -> None:
        from smc_integration import structure_batch as mod

        monkeypatch.setattr(mod, "load_export_bundle", lambda *a, **kw: {"frames": {}})
        result = mod._load_symbol_bars_from_canonical_exports("AAPL", "15m", Path("/tmp/fake"))
        assert result is None


class TestBuildSingleSymbolStructureArtifactNoInput:
    def test_no_workbook_or_bundle_raises(self, monkeypatch) -> None:
        from smc_integration import structure_batch as mod

        monkeypatch.setattr(mod, "_load_symbol_bars_from_canonical_exports", lambda *a, **kw: None)
        with pytest.raises(ValueError, match="only supported for 1D"):
            mod.build_single_symbol_structure_artifact(
                workbook=None,
                export_bundle_root=Path("/tmp/fake"),
                symbol="AAPL",
                timeframe="15m",
                generated_at=1709253600.0,
            )

    def test_no_workbook_or_bundle_raises_for_daily(self, monkeypatch) -> None:
        from smc_integration import structure_batch as mod

        monkeypatch.setattr(mod, "_load_symbol_bars_from_canonical_exports", lambda *a, **kw: None)
        with pytest.raises(ValueError, match="missing structure input"):
            mod.build_single_symbol_structure_artifact(
                workbook=None,
                export_bundle_root=Path("/tmp/fake"),
                symbol="AAPL",
                timeframe="1D",
                generated_at=1709253600.0,
            )

    def test_intraday_with_workbook_only_raises(self, tmp_path: Path, monkeypatch) -> None:
        from smc_integration import structure_batch as mod

        monkeypatch.setattr(mod, "_load_symbol_bars_from_canonical_exports", lambda *a, **kw: None)
        wb = make_minimal_workbook(tmp_path)
        with pytest.raises(ValueError, match="only supported for 1D"):
            mod.build_single_symbol_structure_artifact(
                workbook=wb,
                export_bundle_root=None,
                symbol="AAPL",
                timeframe="15m",
                generated_at=1709253600.0,
            )


class TestWorkbookFallbackGate:
    """Regression guard: workbook fallback must refuse intraday timeframes.

    Prior bug: ``build_single_symbol_structure_artifact`` silently fed daily
    bars from the workbook into ``build_explicit_structure_from_bars(timeframe="15m")``,
    producing artifacts that claimed intraday provenance while containing daily
    OHLC. ``measurement_evidence._load_source_bars`` already had the 1D gate;
    this suite pins the same gate in ``structure_batch`` and guards the shared
    :func:`smc_integration.timeframes.is_daily_timeframe` helper against regressions
    (casing, whitespace, synonyms).
    """

    @pytest.mark.parametrize("intraday_tf", ["5m", "15m", "1H", "4H", "30m"])
    def test_workbook_fallback_rejects_intraday_timeframe(self, tmp_path: Path, monkeypatch, intraday_tf: str) -> None:
        from smc_integration import structure_batch as mod

        monkeypatch.setattr(mod, "_load_symbol_bars_from_canonical_exports", lambda *a, **kw: None)
        wb = make_minimal_workbook(tmp_path)
        with pytest.raises(ValueError, match="only supported for 1D"):
            mod.build_single_symbol_structure_artifact(
                workbook=wb,
                export_bundle_root=None,
                symbol="AAPL",
                timeframe=intraday_tf,
                generated_at=0.0,
            )

    @pytest.mark.parametrize("daily_tf", ["1D", "1d", " 1D ", "D", "daily", "DAILY", "1day"])
    def test_workbook_fallback_accepts_daily_synonyms(self, tmp_path: Path, monkeypatch, daily_tf: str) -> None:
        from smc_integration import structure_batch as mod

        # Daily synonyms must NOT trigger the intraday reject. Route canonical
        # loader to None so the code path reaches the workbook fallback branch.
        monkeypatch.setattr(mod, "_load_symbol_bars_from_canonical_exports", lambda *a, **kw: None)
        wb = make_minimal_workbook(tmp_path)
        # Must not raise ValueError with "only supported for 1D". It may still
        # succeed (workbook has the symbol) or raise an unrelated error; we
        # only assert the intraday gate is not tripped.
        try:
            mod.build_single_symbol_structure_artifact(
                workbook=wb,
                export_bundle_root=None,
                symbol="AAPL",
                timeframe=daily_tf,
                generated_at=0.0,
            )
        except ValueError as exc:
            assert "only supported for 1D" not in str(exc), (
                f"daily synonym {daily_tf!r} was wrongly rejected by intraday gate"
            )

    def test_is_daily_timeframe_helper_contract(self) -> None:
        from smc_integration.timeframes import is_daily_timeframe

        assert is_daily_timeframe("1D")
        assert is_daily_timeframe("1d")
        assert is_daily_timeframe(" 1D ")
        assert is_daily_timeframe("D")
        assert is_daily_timeframe("daily")
        assert is_daily_timeframe("DAILY")
        assert not is_daily_timeframe("15m")
        assert not is_daily_timeframe("1H")
        assert not is_daily_timeframe("")
        assert not is_daily_timeframe("1W")


class TestBuildStructureArtifactBatchEdges:
    def test_empty_timeframe_raises(self, tmp_path: Path, monkeypatch) -> None:
        from smc_integration import structure_batch as mod

        wb = make_minimal_workbook(tmp_path)
        monkeypatch.setattr(mod, "resolve_structure_artifact_inputs", lambda **kw: {
            "workbook_path": wb, "export_bundle_root": None, "warnings": [], "errors": [],
        })
        with pytest.raises(ValueError, match="timeframe must not be empty"):
            mod.write_structure_artifacts_from_workbook(
                workbook=wb,
                timeframe="  ",
                symbols=["AAPL"],
                output_dir=tmp_path / "out",
            )

    def test_empty_symbols_no_workbook_raises(self, tmp_path: Path, monkeypatch) -> None:
        from smc_integration import structure_batch as mod

        monkeypatch.setattr(mod, "resolve_structure_artifact_inputs", lambda **kw: {
            "workbook_path": None, "export_bundle_root": None, "warnings": [], "errors": [],
        })
        with pytest.raises(ValueError, match="symbols must not be empty"):
            mod.write_structure_artifacts_from_workbook(
                workbook=None,
                timeframe="15m",
                symbols=[],
                output_dir=tmp_path / "out",
            )

    def test_preexisting_artifacts_fallback(self, tmp_path: Path, monkeypatch) -> None:
        from smc_integration import structure_batch as mod

        monkeypatch.setattr(mod, "resolve_structure_artifact_inputs", lambda **kw: {
            "workbook_path": None, "export_bundle_root": None, "warnings": [], "errors": [],
        })

        out_dir = tmp_path / "artifacts"
        out_dir.mkdir(parents=True)
        artifact = {
            "schema_version": "1.0",
            "symbol": "AAPL",
            "timeframe": "15m",
            "coverage_mode": "partial",
            "coverage": {"has_bos": True, "has_orderblocks": False, "has_fvg": False, "has_liquidity_sweeps": False},
            "structure": {"bos": [{"kind": "BOS"}], "orderblocks": [], "fvg": [], "liquidity_sweeps": []},
            "diagnostics": {"counts": {"bos": 1, "orderblocks": 0, "fvg": 0, "liquidity_sweeps": 0}, "warnings": []},
        }
        (out_dir / "AAPL_15m.structure.json").write_text(json.dumps(artifact), encoding="utf-8")

        manifest = mod.write_structure_artifacts_from_workbook(
            workbook=None,
            timeframe="15m",
            symbols=["AAPL"],
            export_bundle_root=None,
            output_dir=out_dir,
        )
        assert manifest["resolution_mode"] == "preexisting_artifacts"
        assert manifest["counts"]["artifacts_written"] >= 1

    def test_build_error_captured(self, tmp_path: Path, monkeypatch) -> None:
        from smc_integration import structure_batch as mod

        wb = make_minimal_workbook(tmp_path)
        out_dir = tmp_path / "out"

        monkeypatch.setattr(mod, "resolve_structure_artifact_inputs", lambda **kw: {
            "workbook_path": wb, "export_bundle_root": None, "warnings": [], "errors": [],
        })

        orig_build = mod.build_single_symbol_structure_artifact

        def _boom(**kwargs):
            if kwargs.get("symbol") == "MSFT":
                raise RuntimeError("test boom")
            return orig_build(**kwargs)

        monkeypatch.setattr(mod, "build_single_symbol_structure_artifact", _boom)
        manifest = mod.write_structure_artifacts_from_workbook(
            workbook=wb,
            timeframe="1D",
            symbols=["AAPL", "MSFT"],
            output_dir=out_dir,
        )
        assert manifest["counts"]["errors"] >= 1
        assert any(e["symbol"] == "MSFT" for e in manifest["errors"])
