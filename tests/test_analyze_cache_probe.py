"""Tests for scripts/analyze_cache_probe.py.

Covers:
- fam() path classifier (the existing public surface)
- collect_paths() per-run path set
- overlap_report() pairwise intersection output
- main() CLI dispatch for --overlap vs. legacy positional mode
"""
from __future__ import annotations

import json
import pathlib

import pytest

from scripts import analyze_cache_probe as acp


def _write_shard(run_dir: pathlib.Path, shard_id: int, records: list[dict]) -> None:
    shard_dir = run_dir / f"cache-probe-shard-{shard_id}-of-6"
    shard_dir.mkdir(parents=True, exist_ok=True)
    shard_file = shard_dir / f"cache_probe_shard_{shard_id}.jsonl"
    shard_file.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n",
        encoding="utf-8",
    )


def test_fam_extracts_family_segment() -> None:
    p = "/home/runner/work/x/artifacts/databento_volatility_cache/daily_bars/XNAS_ITCH/foo.parquet"
    assert acp.fam(p) == "daily_bars"


def test_fam_returns_unknown_for_unrelated_path() -> None:
    assert acp.fam("/tmp/random.parquet") == "unknown"


def test_fam_handles_windows_separators() -> None:
    p = r"C:\work\artifacts\databento_volatility_cache\intraday_summary\XNAS_ITCH\foo.parquet"
    assert acp.fam(p) == "intraday_summary"


def test_collect_paths_unions_across_shards(tmp_path: pathlib.Path) -> None:
    run = tmp_path / "26179953028"
    _write_shard(run, 1, [
        {"path": "/cache/a.parquet", "hit": False},
        {"path": "/cache/b.parquet", "hit": True},
    ])
    _write_shard(run, 2, [
        {"path": "/cache/b.parquet", "hit": False},
        {"path": "/cache/c.parquet", "hit": False},
    ])
    assert acp.collect_paths(run) == {"/cache/a.parquet", "/cache/b.parquet", "/cache/c.parquet"}


def test_collect_paths_empty_for_run_without_shards(tmp_path: pathlib.Path) -> None:
    run = tmp_path / "empty"
    run.mkdir()
    assert acp.collect_paths(run) == set()


def test_overlap_report_pairwise_intersection(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_a = tmp_path / "run_a"
    run_b = tmp_path / "run_b"
    _write_shard(run_a, 1, [
        {"path": "/cache/x.parquet", "hit": False},
        {"path": "/cache/y.parquet", "hit": False},
        {"path": "/cache/z.parquet", "hit": False},
    ])
    _write_shard(run_b, 1, [
        {"path": "/cache/y.parquet", "hit": False},
        {"path": "/cache/z.parquet", "hit": False},
        {"path": "/cache/w.parquet", "hit": False},
    ])
    rc = acp.overlap_report([run_a, run_b])
    out = capsys.readouterr().out
    assert rc == 0
    # Intersection {y, z} -> 2 / |B|=3 = 66.67 %
    assert "inter=   2" in out
    assert "rate= 66.67%" in out
    assert "run_a & run_b" in out


def test_overlap_report_rejects_single_run(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = tmp_path / "only"
    _write_shard(run, 1, [{"path": "/cache/a.parquet", "hit": False}])
    rc = acp.overlap_report([run])
    err = capsys.readouterr().err
    assert rc == 2
    assert "at least two" in err


def test_overlap_report_rejects_empty_run(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_a = tmp_path / "run_a"
    run_b = tmp_path / "run_b"
    _write_shard(run_a, 1, [{"path": "/cache/a.parquet", "hit": False}])
    run_b.mkdir()
    rc = acp.overlap_report([run_a, run_b])
    err = capsys.readouterr().err
    assert rc == 2
    assert "no probe records" in err


def test_main_overlap_mode(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_a = tmp_path / "run_a"
    run_b = tmp_path / "run_b"
    _write_shard(run_a, 1, [{"path": "/cache/a.parquet", "hit": False}])
    _write_shard(run_b, 1, [{"path": "/cache/a.parquet", "hit": False}])
    rc = acp.main(["--overlap", str(run_a), str(run_b)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "rate=100.00%" in out


def test_main_legacy_mode_iterates_root(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_a = tmp_path / "run_a"
    _write_shard(run_a, 1, [
        {"path": "/cache/databento_volatility_cache/daily_bars/XNAS/a.parquet", "hit": True},
        {"path": "/cache/databento_volatility_cache/daily_bars/XNAS/b.parquet", "hit": False},
    ])
    rc = acp.main([str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "run_a" in out
    assert "rate=50.00%" in out
    assert "daily_bars" in out


# --- #2398 symbol-drift mode ------------------------------------------------

_SD_MIN = "databento_volatility_cache/symbol_detail_minute/XNAS_ITCH"
_SD_SEC = "databento_volatility_cache/symbol_detail_second/XNAS_ITCH"


def _sd_path(family_dir: str, date: str, sym: str) -> str:
    return f"/cache/{family_dir}/{date}__{sym}__Europe_Berlin__152000__abc.parquet"


def test_parse_symbol_date_extracts_symbol_and_date() -> None:
    parsed = acp.parse_symbol_date(_sd_path(_SD_MIN, "2026-04-24", "CHARR"))
    assert parsed == ("symbol_detail_minute", "CHARR", "2026-04-24")


def test_parse_symbol_date_handles_windows_separators() -> None:
    p = r"C:\cache\databento_volatility_cache\symbol_detail_second\XNAS\2026-05-01__UZX__tz__x.parquet"
    assert acp.parse_symbol_date(p) == ("symbol_detail_second", "UZX", "2026-05-01")


def test_parse_symbol_date_returns_none_for_universe_wide_path() -> None:
    # No `<date>__<symbol>__` prefix -> not a per-symbol path.
    p = "/cache/databento_volatility_cache/intraday_summary/XNAS/summary.parquet"
    assert acp.parse_symbol_date(p) is None


def test_parse_symbol_date_returns_none_for_unrelated_path() -> None:
    assert acp.parse_symbol_date("/tmp/2026-01-01__X__y.parquet") is None


def test_symbol_drift_report_quantifies_selection_drift(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run1 = tmp_path / "run1"
    run2 = tmp_path / "run2"
    # 3 symbols in run1, 1 stable (CHARR same date) + 2 dropped; run2 adds 2 new.
    _write_shard(run1, 1, [
        {"path": _sd_path(_SD_MIN, "2026-04-24", "CHARR"), "hit": False},
        {"path": _sd_path(_SD_MIN, "2026-04-30", "ORGNW"), "hit": False},
        {"path": _sd_path(_SD_MIN, "2026-05-05", "YMAT"), "hit": False},
    ])
    _write_shard(run2, 1, [
        {"path": _sd_path(_SD_MIN, "2026-04-24", "CHARR"), "hit": True},
        {"path": _sd_path(_SD_MIN, "2026-05-10", "BNCWZ"), "hit": False},
        {"path": _sd_path(_SD_MIN, "2026-05-12", "TLIH"), "hit": False},
    ])
    rc = acp.symbol_drift_report([run1, run2], "symbol_detail_")
    out = capsys.readouterr().out
    assert rc == 0
    assert "symbol_detail_minute" in out
    assert "stable=['CHARR']" in out
    assert "new=['BNCWZ', 'TLIH']" in out
    assert "dropped=['ORGNW', 'YMAT']" in out
    # symbol Jaccard = |{CHARR}| / |{CHARR,ORGNW,YMAT,BNCWZ,TLIH}| = 1/5 = 20%
    assert "symbol_jaccard= 20.00%" in out
    # (symbol,date) overlap = {(CHARR,2026-04-24)} / 3 = 33.33%
    assert "overlap=1/3 =  33.33%" in out


def test_symbol_drift_report_filters_by_prefix(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run1 = tmp_path / "run1"
    run2 = tmp_path / "run2"
    rows1 = [
        {"path": _sd_path(_SD_SEC, "2026-04-24", "CHARR"), "hit": False},
        {"path": "/cache/databento_volatility_cache/daily_bars/XNAS/d.parquet", "hit": True},
    ]
    rows2 = [
        {"path": _sd_path(_SD_SEC, "2026-04-24", "CHARR"), "hit": True},
    ]
    _write_shard(run1, 1, rows1)
    _write_shard(run2, 1, rows2)
    rc = acp.symbol_drift_report([run1, run2], "symbol_detail_")
    out = capsys.readouterr().out
    assert rc == 0
    # Only the symbol_detail_second family is reported; daily_bars is excluded.
    assert "symbol_detail_second" in out
    assert "daily_bars" not in out


def test_symbol_drift_report_rejects_single_run(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = tmp_path / "only"
    _write_shard(run, 1, [{"path": _sd_path(_SD_MIN, "2026-04-24", "CHARR"), "hit": False}])
    rc = acp.symbol_drift_report([run], "symbol_detail_")
    err = capsys.readouterr().err
    assert rc == 2
    assert "at least two" in err


def test_symbol_drift_report_rejects_no_matching_family(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run1 = tmp_path / "run1"
    run2 = tmp_path / "run2"
    _write_shard(run1, 1, [
        {"path": "/cache/databento_volatility_cache/daily_bars/XNAS/d.parquet", "hit": True},
    ])
    _write_shard(run2, 1, [
        {"path": "/cache/databento_volatility_cache/daily_bars/XNAS/d.parquet", "hit": True},
    ])
    rc = acp.symbol_drift_report([run1, run2], "symbol_detail_")
    err = capsys.readouterr().err
    assert rc == 2
    assert "no per-symbol records" in err


def test_main_symbol_drift_mode(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run1 = tmp_path / "run1"
    run2 = tmp_path / "run2"
    _write_shard(run1, 1, [{"path": _sd_path(_SD_MIN, "2026-04-24", "CHARR"), "hit": False}])
    _write_shard(run2, 1, [{"path": _sd_path(_SD_MIN, "2026-04-24", "CHARR"), "hit": True}])
    rc = acp.main(["--symbol-drift", str(run1), str(run2)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "overlap=1/1 = 100.00%" in out
