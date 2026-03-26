from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

import databento_volatility_screener as dvs
import scripts.databento_production_export as export_mod
import scripts.databento_production_workbook as workbook_mod
from scripts.databento_production_workbook import WorkbookWriteResult, write_databento_production_workbook_from_frames


def test_shared_workbook_writer_is_deterministic_for_fixed_input(tmp_path: Path) -> None:
    summary = pd.DataFrame(
        [
            {
                "trade_date": "2026-03-06",
                "symbol": "AAPL",
                "window_range_pct": 2.1,
                "realized_vol_pct": 1.2,
                "window_return_pct": 0.5,
                "prev_close_to_premarket_pct": 1.1,
                "premarket_to_open_pct": 0.4,
                "open_to_current_pct": 0.2,
            }
        ]
    )
    additional = {"daily_bars": pd.DataFrame([{"trade_date": "2026-03-06", "symbol": "AAPL", "close": 180.0}])}

    left = write_databento_production_workbook_from_frames(
        summary=summary,
        output_path=tmp_path / "left.xlsx",
        generated_at=1_700_000_000.0,
        additional_sheets=additional,
    )
    right = write_databento_production_workbook_from_frames(
        summary=summary,
        output_path=tmp_path / "right.xlsx",
        generated_at=1_700_000_000.0,
        additional_sheets=additional,
    )

    assert left.generated_at == right.generated_at
    assert left.row_counts == right.row_counts
    assert left.output_path.read_bytes() == right.output_path.read_bytes()


def test_streamlit_create_excel_workbook_reuses_shared_helper(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def _fake_create_excel_workbook_bytes(
        summary: pd.DataFrame,
        *,
        minute_detail: pd.DataFrame | None = None,
        second_detail: pd.DataFrame | None = None,
        additional_sheets: dict[str, pd.DataFrame] | None = None,
    ) -> bytes:
        calls.append(
            {
                "summary_rows": len(summary),
                "minute_rows": 0 if minute_detail is None else len(minute_detail),
                "second_rows": 0 if second_detail is None else len(second_detail),
                "sheet_count": 0 if additional_sheets is None else len(additional_sheets),
            }
        )
        return b"xlsx-bytes"

    monkeypatch.setattr(dvs, "create_excel_workbook_bytes", _fake_create_excel_workbook_bytes)

    payload = dvs.create_excel_workbook(pd.DataFrame([{"symbol": "AAPL"}]))
    assert payload == b"xlsx-bytes"
    assert len(calls) == 1
    assert calls[0]["summary_rows"] == 1


def test_create_excel_workbook_bytes_splits_oversized_sheets(monkeypatch) -> None:
    monkeypatch.setattr(workbook_mod, "EXCEL_MAX_ROWS_PER_SHEET", 3)

    summary = pd.DataFrame(
        [
            {
                "trade_date": "2026-03-06",
                "symbol": f"SYM{idx}",
                "window_range_pct": 1.0,
                "realized_vol_pct": 1.0,
                "window_return_pct": 1.0,
                "prev_close_to_premarket_pct": 1.0,
                "premarket_to_open_pct": 1.0,
                "open_to_current_pct": 1.0,
            }
            for idx in range(4)
        ]
    )
    second_detail = pd.DataFrame({"symbol": ["A", "B", "C", "D", "E"], "value": [1, 2, 3, 4, 5]})
    payload = workbook_mod.create_excel_workbook_bytes(summary=summary, second_detail=second_detail)

    workbook = load_workbook(filename=BytesIO(payload))
    assert "summary" in workbook.sheetnames
    assert "summary_002" in workbook.sheetnames
    assert "second_detail" in workbook.sheetnames
    assert "second_detail_002" in workbook.sheetnames


def test_production_pipeline_canonical_workbook_helper_invokes_shared_writer(monkeypatch, tmp_path: Path) -> None:
    recorded: dict[str, object] = {}

    def _fake_writer(**kwargs):
        recorded.update(kwargs)
        out_path = Path(kwargs["output_path"])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"ok")
        return WorkbookWriteResult(
            output_path=out_path,
            generated_at="2026-03-26T00:00:00+00:00",
            row_counts={"summary": len(kwargs["summary"])},
            sheet_names=["summary"],
            canonical_upstream_artifact="databento_production_export_bundle",
        )

    monkeypatch.setattr(export_mod, "write_databento_production_workbook_from_frames", _fake_writer)

    path = export_mod._write_canonical_production_workbook(
        export_dir=tmp_path,
        summary=pd.DataFrame([{"symbol": "AAPL"}]),
        minute_detail=pd.DataFrame(),
        second_detail=pd.DataFrame(),
        manifest={"dataset": "DBEQ.BASIC"},
        raw_universe=pd.DataFrame(),
        daily_bars=pd.DataFrame(),
        intraday=pd.DataFrame(),
        ranked=pd.DataFrame(),
        daily_symbol_features_full_universe=pd.DataFrame(),
        full_universe_second_detail_open=pd.DataFrame(),
        full_universe_second_detail_close=pd.DataFrame(),
        full_universe_close_trade_detail=pd.DataFrame(),
        full_universe_close_outcome_minute=pd.DataFrame(),
        close_imbalance_features_full_universe=pd.DataFrame(),
        close_imbalance_outcomes_full_universe=pd.DataFrame(),
        premarket_features_full_universe=pd.DataFrame(),
        premarket_window_features_full_universe=pd.DataFrame(),
        symbol_day_diagnostics=pd.DataFrame(),
        research_event_flags_full_universe=pd.DataFrame(),
        research_event_flag_coverage=pd.DataFrame(),
        research_event_flag_trade_date_distribution=pd.DataFrame(),
        research_event_flag_outcome_slices=pd.DataFrame(),
        research_news_flags_full_universe=pd.DataFrame(),
        research_news_flag_coverage=pd.DataFrame(),
        research_news_flag_trade_date_distribution=pd.DataFrame(),
        research_news_flag_outcome_slices=pd.DataFrame(),
        core_vs_benzinga_news_side_by_side=pd.DataFrame(),
        core_vs_benzinga_news_overlap_stats=pd.DataFrame(),
        quality_window_status=pd.DataFrame(),
        batl_debug={},
        output_summary={},
    )

    assert path.exists()
    assert recorded["output_path"] == tmp_path / "databento_volatility_production_workbook.xlsx"
