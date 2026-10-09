"""F-V8-cutover (2026-05-18) — payload-level reducer for the sharded producer.

Companion test to ``test_a9b_3_merge_shards.py`` (manifest-level reducer).
The cutover added a ``--payload-output-dir`` mode that concatenates the
per-shard frame parquets emitted alongside each shard manifest into a
single canonical merged bundle, so downstream consumers loading via
``load_export_bundle(required_frames=...)`` resolve a union-of-dates
bundle and not a single shard's date slice.

These tests pin:

* the discovery layer (``_discover_shard_parquets``) groups files by
  frame name and preserves manifest order so concat is deterministic;
* dedupe picks the first matching key candidate and is a no-op when no
  key columns are present (planner contract: shards are calendar-day-
  disjoint);
* the end-to-end merge produces a loadable bundle compatible with
  ``scripts.load_databento_export_bundle.load_export_bundle``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "databento_production_merge_shards.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "databento_production_merge_shards_payloads_test_load", _SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load_module()


def _make_shard(
    root: Path,
    shard_id: int,
    *,
    basename: str,
    dates: list[str],
    symbols: list[str],
) -> Path:
    """Create a fake shard artifact tree with manifest + two frames.

    Returns the shard directory (suitable as a ``--shard-dir`` argv).
    """
    shard_dir = root / f"a9b-2b-shard-{shard_id}-of-2"
    export_dir = shard_dir / "smc_microstructure_exports"
    export_dir.mkdir(parents=True)
    manifest = {
        "basename": basename,
        "trade_dates_covered": dates,
        "shard_id": shard_id,
    }
    manifest_path = export_dir / f"{basename}_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    daily_bars = pd.DataFrame(
        [
            {"symbol": sym, "trade_date": d, "close": 100.0 + i}
            for i, (sym, d) in enumerate(
                [(s, d) for d in dates for s in symbols]
            )
        ]
    )
    daily_bars.to_parquet(export_dir / f"{basename}__daily_bars.parquet", index=False)

    features = pd.DataFrame(
        [
            {"symbol": sym, "date": d, "feature_x": float(j)}
            for j, (sym, d) in enumerate(
                [(s, d) for d in dates for s in symbols]
            )
        ]
    )
    features.to_parquet(
        export_dir
        / f"{basename}__daily_symbol_features_full_universe.parquet",
        index=False,
    )

    return shard_dir


def test_discover_shard_parquets_groups_by_frame(mod, tmp_path):
    shard1 = _make_shard(
        tmp_path,
        1,
        basename="databento_volatility_production_20260420_000000",
        dates=["2026-04-20", "2026-04-21"],
        symbols=["AAPL", "MSFT"],
    )
    shard2 = _make_shard(
        tmp_path,
        2,
        basename="databento_volatility_production_20260422_000000",
        dates=["2026-04-22", "2026-04-23"],
        symbols=["AAPL", "MSFT"],
    )
    manifests = [
        next((shard1 / "smc_microstructure_exports").glob("*_manifest.json")),
        next((shard2 / "smc_microstructure_exports").glob("*_manifest.json")),
    ]
    by_frame = mod._discover_shard_parquets(manifests)
    assert set(by_frame) == {"daily_bars", "daily_symbol_features_full_universe"}
    for paths in by_frame.values():
        assert len(paths) == 2


def test_merge_shard_payloads_concats_by_frame(mod, tmp_path):
    shard1 = _make_shard(
        tmp_path,
        1,
        basename="databento_volatility_production_20260420_000000",
        dates=["2026-04-20", "2026-04-21"],
        symbols=["AAPL", "MSFT"],
    )
    shard2 = _make_shard(
        tmp_path,
        2,
        basename="databento_volatility_production_20260422_000000",
        dates=["2026-04-22", "2026-04-23"],
        symbols=["AAPL", "MSFT"],
    )
    manifests = [
        next((shard1 / "smc_microstructure_exports").glob("*_manifest.json")),
        next((shard2 / "smc_microstructure_exports").glob("*_manifest.json")),
    ]
    out_dir = tmp_path / "merged"
    summary = mod.merge_shard_payloads(manifests, out_dir)

    # 4 dates * 2 symbols = 8 rows per frame after union of date-disjoint shards.
    assert summary == {"daily_bars": 8, "daily_symbol_features_full_universe": 8}

    daily_bars = pd.read_parquet(
        out_dir / f"{mod.MERGED_BASENAME}__daily_bars.parquet"
    )
    assert set(daily_bars["trade_date"]) == {
        "2026-04-20",
        "2026-04-21",
        "2026-04-22",
        "2026-04-23",
    }
    assert set(daily_bars["symbol"]) == {"AAPL", "MSFT"}
    # Dedupe key is (symbol, trade_date) so sort_values orders by symbol
    # primary, then trade_date secondary — each symbol's slice is itself
    # date-sorted, which is what the loader (and humans diffing the bundle)
    # actually care about.
    for sym in ("AAPL", "MSFT"):
        sym_dates = daily_bars.loc[daily_bars["symbol"] == sym, "trade_date"].tolist()
        assert sym_dates == sorted(sym_dates), (
            f"per-symbol trade_date order must be ascending; got {sym_dates}"
        )


def test_merge_shard_payloads_drops_duplicates(mod, tmp_path):
    # Two shards intentionally re-emit the same (symbol, trade_date) row to
    # exercise the dedupe path. The planner would normally prevent this,
    # but the reducer should tolerate it (with a log line) rather than
    # silently double-count rows in the merged bundle.
    shard1 = _make_shard(
        tmp_path,
        1,
        basename="databento_volatility_production_20260420_000000",
        dates=["2026-04-20"],
        symbols=["AAPL"],
    )
    shard2 = _make_shard(
        tmp_path,
        2,
        basename="databento_volatility_production_20260421_000000",
        dates=["2026-04-20"],  # same date as shard1
        symbols=["AAPL"],
    )
    manifests = [
        next((shard1 / "smc_microstructure_exports").glob("*_manifest.json")),
        next((shard2 / "smc_microstructure_exports").glob("*_manifest.json")),
    ]
    out_dir = tmp_path / "merged"
    summary = mod.merge_shard_payloads(manifests, out_dir)
    assert summary["daily_bars"] == 1  # dedupe by (symbol, trade_date)


def test_merge_shard_payloads_empty_returns_empty_summary(mod, tmp_path):
    # Manifest with no sibling parquets: legitimate manifest-only edge case.
    export_dir = tmp_path / "shard-1" / "smc_microstructure_exports"
    export_dir.mkdir(parents=True)
    manifest_path = export_dir / "databento_volatility_production_x_manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    out_dir = tmp_path / "merged"
    summary = mod.merge_shard_payloads([manifest_path], out_dir)
    assert summary == {}


def test_merged_bundle_loadable_via_load_export_bundle(mod, tmp_path):
    """End-to-end: merged bundle resolves through the public loader."""
    from scripts.load_databento_export_bundle import load_export_bundle

    shard1 = _make_shard(
        tmp_path,
        1,
        basename="databento_volatility_production_20260420_000000",
        dates=["2026-04-20", "2026-04-21"],
        symbols=["AAPL", "MSFT"],
    )
    shard2 = _make_shard(
        tmp_path,
        2,
        basename="databento_volatility_production_20260422_000000",
        dates=["2026-04-22", "2026-04-23"],
        symbols=["AAPL", "MSFT"],
    )
    manifests = [
        next((shard1 / "smc_microstructure_exports").glob("*_manifest.json")),
        next((shard2 / "smc_microstructure_exports").glob("*_manifest.json")),
    ]
    out_dir = tmp_path / "merged"
    mod.merge_shard_payloads(manifests, out_dir)

    # Drop the merged manifest in alongside the parquets so the loader has
    # a complete bundle to resolve.
    merged_manifest = {"shard_count": 2, "trade_dates_covered": [
        "2026-04-20", "2026-04-21", "2026-04-22", "2026-04-23"]}
    (out_dir / f"{mod.MERGED_BASENAME}_manifest.json").write_text(
        json.dumps(merged_manifest), encoding="utf-8"
    )

    payload = load_export_bundle(
        out_dir,
        required_frames=("daily_bars", "daily_symbol_features_full_universe"),
        manifest_prefix="databento_volatility_production_",
    )
    assert set(payload["frames"]) >= {
        "daily_bars",
        "daily_symbol_features_full_universe",
    }
    assert len(payload["frames"]["daily_bars"]) == 8


def test_merge_shard_payloads_streaming_six_shards(mod, tmp_path):
    """WF-026 OOM fix — production-realistic 6-shard streaming merge.

    Exercises the PyArrow-dataset streaming path that replaced the
    ``[pd.read_parquet(p) for p in paths] + pd.concat(...)`` pattern.
    Verifies that:
    - All 6 × 3 = 18 rows (one date per shard, three symbols each) are
      preserved after the streaming concat + dedupe round-trip.
    - The merged parquet is readable and has the expected column set.
    - Schema is stable across shards with identical column layouts.
    """
    shards = []
    for i in range(1, 7):
        # Each shard covers a distinct calendar month to guarantee
        # date-disjoint shards (no cross-shard duplicates expected).
        date = f"2026-{i:02d}-01"
        ts = f"2026{i:02d}01_000000"
        shards.append(
            _make_shard(
                tmp_path,
                i,
                basename=f"databento_volatility_production_{ts}",
                dates=[date],
                symbols=["AAPL", "MSFT", "GOOGL"],
            )
        )

    manifests = [
        next((s / "smc_microstructure_exports").glob("*_manifest.json"))
        for s in shards
    ]
    out_dir = tmp_path / "merged"
    summary = mod.merge_shard_payloads(manifests, out_dir)

    # 6 shards × 1 date × 3 symbols = 18 rows per frame.
    assert summary == {
        "daily_bars": 18,
        "daily_symbol_features_full_universe": 18,
    }, f"unexpected summary: {summary}"

    merged = pd.read_parquet(out_dir / f"{mod.MERGED_BASENAME}__daily_bars.parquet")
    assert len(merged) == 18
    assert merged["trade_date"].nunique() == 6
    assert set(merged["symbol"]) == {"AAPL", "MSFT", "GOOGL"}
    assert set(merged.columns) >= {"symbol", "trade_date", "close"}


def test_merge_shard_payloads_single_shard_passthrough(mod, tmp_path):
    """Single-shard case — streaming path must not alter schema or row count."""
    shard = _make_shard(
        tmp_path,
        1,
        basename="databento_volatility_production_20260420_000000",
        dates=["2026-04-20", "2026-04-21"],
        symbols=["AAPL", "MSFT"],
    )
    manifests = [
        next((shard / "smc_microstructure_exports").glob("*_manifest.json"))
    ]
    out_dir = tmp_path / "merged"
    summary = mod.merge_shard_payloads(manifests, out_dir)

    # 2 dates × 2 symbols = 4 rows; no dedup expected (single shard).
    assert summary["daily_bars"] == 4
    merged = pd.read_parquet(out_dir / f"{mod.MERGED_BASENAME}__daily_bars.parquet")
    assert len(merged) == 4
