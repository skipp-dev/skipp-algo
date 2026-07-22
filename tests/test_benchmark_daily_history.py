"""Tests for the long-history 1D pipeline (ADR-0023 issue #3872 Option A).

The rolling bundle spans only ~21 trading days — shorter than 1D warmup +
label horizons (FVG=20 daily bars) — so the 1D slice yielded zero
FamilyEvents and the governed live-1D magnitude track starved. These tests
pin the three repair parts:

1. ``scripts/fetch_benchmark_daily_history.py`` writes a workbook whose
   ``daily_bars`` sheet round-trips through the SAME readers production uses;
2. ``measurement_evidence._load_source_bars`` honours the opt-in
   ``SMC_DAILY_BARS_WORKBOOK_OVERRIDE`` for daily bars only;
3. the rolling workflow wires fetch + exporter + harness + the daily anchor
   window together.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from scripts.fetch_benchmark_daily_history import build_daily_bars_sheet
from smc_integration.measurement_evidence import _load_source_bars
from smc_integration.structure_batch import _load_symbol_bars_from_workbook

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github" / "workflows"
    / "smc-measurement-benchmark-rolling.yml"
)


def _frame(symbols: list[str], rows_per_symbol: int) -> pd.DataFrame:
    records = []
    for symbol in symbols:
        for i in range(rows_per_symbol):
            records.append(
                {
                    "trade_date": (pd.Timestamp("2025-01-01") + pd.Timedelta(days=i)).date().isoformat(),
                    "symbol": symbol,
                    "open": 100.0 + i,
                    "high": 101.0 + i,
                    "low": 99.0 + i,
                    "close": 100.5 + i,
                    "volume": 1_000 + i,
                    "previous_close": 100.0 + i,
                }
            )
    return pd.DataFrame.from_records(records)


# --------------------------------------------------------------------------- #
# build_daily_bars_sheet
# --------------------------------------------------------------------------- #
def test_sheet_filters_symbols_sorts_and_dedups() -> None:
    frame = _frame(["AAPL", "MSFT", "TSLA"], 5)
    doubled = pd.concat([frame, frame.iloc[:3]], ignore_index=True)
    sheet = build_daily_bars_sheet(doubled, symbols=["aapl", "MSFT"], min_rows_per_symbol=5)
    assert sorted(sheet["symbol"].unique()) == ["AAPL", "MSFT"]
    assert len(sheet) == 10  # dedup removed the re-appended rows
    assert sheet.groupby("symbol")["trade_date"].apply(lambda s: list(s) == sorted(s)).all()


def test_sheet_fails_loud_on_short_history() -> None:
    # A silently short 1D frame would recreate the zero-capacity starvation
    # this pipeline exists to fix — the writer must refuse, the workflow's
    # fail-soft wrapper then degrades to the alarmed status quo.
    frame = _frame(["AAPL", "MSFT"], 5)
    with pytest.raises(ValueError, match="MSFT=5"):
        build_daily_bars_sheet(frame, symbols=["AAPL", "MSFT"], min_rows_per_symbol=6)


def test_sheet_fails_loud_on_missing_symbol_or_columns() -> None:
    frame = _frame(["AAPL"], 5)
    with pytest.raises(ValueError, match="NVDA=0"):
        build_daily_bars_sheet(frame, symbols=["AAPL", "NVDA"], min_rows_per_symbol=1)
    with pytest.raises(ValueError, match="lacks columns"):
        build_daily_bars_sheet(frame.drop(columns=["close"]), symbols=["AAPL"], min_rows_per_symbol=1)


def test_workbook_roundtrips_through_production_readers(tmp_path: Path) -> None:
    """The xlsx this script writes must be consumable by BOTH 1D consumers:
    the structure exporter (via _load_symbol_bars_from_workbook) and the
    measurement harness (via the override branch of _load_source_bars)."""
    sheet = build_daily_bars_sheet(_frame(["AAPL", "MSFT"], 30), symbols=["AAPL", "MSFT"], min_rows_per_symbol=30)
    workbook = tmp_path / "benchmark_daily_history.xlsx"
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        sheet.to_excel(writer, sheet_name="daily_bars", index=False)

    exporter_bars = _load_symbol_bars_from_workbook(workbook, "AAPL")
    assert len(exporter_bars) == 30
    assert list(exporter_bars.columns[:2]) == ["symbol", "timestamp"]


# --------------------------------------------------------------------------- #
# SMC_DAILY_BARS_WORKBOOK_OVERRIDE (measurement harness)
# --------------------------------------------------------------------------- #
def _override_workbook(tmp_path: Path) -> Path:
    sheet = build_daily_bars_sheet(_frame(["AAPL"], 40), symbols=["AAPL"], min_rows_per_symbol=40)
    workbook = tmp_path / "override.xlsx"
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        sheet.to_excel(writer, sheet_name="daily_bars", index=False)
    return workbook


def test_override_serves_daily_bars_before_bundle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SMC_DAILY_BARS_WORKBOOK_OVERRIDE", str(_override_workbook(tmp_path)))
    bars, mode = _load_source_bars("AAPL", "1D", resolved_inputs={})
    assert mode == "workbook_override"
    assert len(bars) == 40


def test_override_is_daily_only_and_fails_open(tmp_path: Path, monkeypatch) -> None:
    workbook = _override_workbook(tmp_path)
    monkeypatch.setenv("SMC_DAILY_BARS_WORKBOOK_OVERRIDE", str(workbook))
    # Intraday requests must NEVER see daily override bars.
    bars, mode = _load_source_bars("AAPL", "5m", resolved_inputs={})
    assert mode != "workbook_override"
    assert bars.empty
    # A symbol the override does not cover falls through to default resolution.
    bars, mode = _load_source_bars("NVDA", "1D", resolved_inputs={})
    assert mode != "workbook_override"
    # A missing override file falls through instead of raising.
    monkeypatch.setenv("SMC_DAILY_BARS_WORKBOOK_OVERRIDE", str(tmp_path / "absent.xlsx"))
    bars, mode = _load_source_bars("AAPL", "1D", resolved_inputs={})
    assert mode != "workbook_override"


# --------------------------------------------------------------------------- #
# rolling workflow wiring
# --------------------------------------------------------------------------- #
def _export_step() -> dict:
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for step in wf["jobs"]["rolling-benchmark"]["steps"]:
        if step.get("name", "").startswith("Export per-TF structure artifacts"):
            return step
    raise AssertionError("per-TF export step not found")


def test_workflow_fetches_long_history_and_feeds_both_1d_consumers() -> None:
    step = _export_step()
    run = step["run"]
    assert "scripts/fetch_benchmark_daily_history.py" in run
    # Fail-soft: a fetch outage must degrade to the alarmed status quo, not
    # kill the intraday benchmark.
    assert "::warning title=benchmark-daily-history::" in run
    # Structure exporter: 1D uses the workbook WITHOUT a bundle root (a
    # bundle root passed alongside would win and reintroduce the 21-day frame).
    assert '"${tf}" = "1D"' in run
    assert "--workbook" in run
    # No dynamic GITHUB_ENV write for the override (zizmor github-env
    # ratchet) — the benchmark step declares the FIXED path statically and
    # the harness falls through when the file is absent.
    assert "SMC_DAILY_BARS_WORKBOOK_OVERRIDE" not in run
    assert step["env"]["DATABENTO_API_KEY"] == "${{ secrets.DATABENTO_API_KEY }}"

    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    bench_step = next(
        s
        for s in wf["jobs"]["rolling-benchmark"]["steps"]
        if "run_smc_measurement_benchmark.py" in s.get("run", "")
    )
    assert (
        bench_step["env"]["SMC_DAILY_BARS_WORKBOOK_OVERRIDE"]
        == "artifacts/ci/benchmark_daily_history.xlsx"
    )


def test_workflow_widens_the_daily_anchor_window() -> None:
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    bench_runs = " ".join(
        s.get("run", "")
        for s in wf["jobs"]["rolling-benchmark"]["steps"]
        if "run_smc_measurement_benchmark.py" in s.get("run", "")
    )
    # 5-day intraday window stays; 1D gets a window wide enough for a
    # completed 20-bar label horizon plus slack.
    assert "--scoring-anchor-window-days 5" in bench_runs
    assert "--scoring-anchor-window-days-daily 40" in bench_runs
