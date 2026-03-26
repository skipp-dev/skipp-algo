from __future__ import annotations

"""Shared Databento production workbook builder.

Canonical upstream artifact policy:
- Canonical artifact: Databento production export bundle (manifest + parquet frames).
- Derived artifact: production workbook (.xlsx) generated from canonical frames.

This module centralizes workbook generation so daily/base production paths and UI paths
use the same producer logic.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.utils import get_column_letter
from pandas.api.types import is_datetime64_any_dtype

from scripts.load_databento_export_bundle import load_export_bundle

DEFAULT_PRODUCTION_EXPORT_DIR = Path("artifacts") / "smc_microstructure_exports"
CANONICAL_PRODUCTION_WORKBOOK_NAME = "databento_volatility_production_workbook.xlsx"
LEGACY_WORKBOOK_GLOB = "databento_volatility_production_*.xlsx"


@dataclass(frozen=True)
class WorkbookWriteResult:
    output_path: Path
    generated_at: str
    row_counts: dict[str, int]
    sheet_names: list[str]
    canonical_upstream_artifact: str


def canonical_production_workbook_path(*, export_dir: Path | None = None) -> Path:
    root = export_dir if export_dir is not None else DEFAULT_PRODUCTION_EXPORT_DIR
    return root / CANONICAL_PRODUCTION_WORKBOOK_NAME


def resolve_production_workbook_path(
    workbook: str | Path | None = None,
    *,
    export_dir: Path | None = None,
    repo_root: Path | None = None,
) -> Path:
    """Resolve workbook path with canonical-first fallback order.

    Freshness model:
    - Canonical deterministic workbook path is per daily export run and overwritten.
    - Timestamped workbook exports are still supported as fallback.
    """

    base_dir = export_dir if export_dir is not None else DEFAULT_PRODUCTION_EXPORT_DIR
    root = repo_root if repo_root is not None else Path.cwd()

    if workbook is not None:
        explicit = Path(workbook).expanduser()
        if explicit.exists():
            return explicit
        raise FileNotFoundError(f"workbook not found: {explicit}")

    canonical = canonical_production_workbook_path(export_dir=base_dir)
    if canonical.exists():
        return canonical

    timestamped = sorted(base_dir.glob(LEGACY_WORKBOOK_GLOB), key=lambda path: path.stat().st_mtime, reverse=True)
    if timestamped:
        return timestamped[0]

    legacy_root = sorted(root.glob(LEGACY_WORKBOOK_GLOB), key=lambda path: path.stat().st_mtime, reverse=True)
    if legacy_root:
        return legacy_root[0]

    raise FileNotFoundError(
        "No Databento production workbook found. Expected canonical path "
        f"{canonical} or timestamped exports matching {LEGACY_WORKBOOK_GLOB}."
    )


def prepare_frame_for_excel(frame: pd.DataFrame) -> pd.DataFrame:
    sanitized = frame.copy()
    for column in sanitized.columns:
        series = sanitized[column]
        if isinstance(series.dtype, pd.DatetimeTZDtype):
            sanitized[column] = series.dt.tz_localize(None)
        elif is_datetime64_any_dtype(series):
            continue
        elif series.dtype == object:
            sanitized[column] = series.map(
                lambda value: (
                    value.tz_localize(None)
                    if isinstance(value, pd.Timestamp) and value.tzinfo is not None
                    else value.replace(tzinfo=None)
                    if isinstance(value, datetime) and value.tzinfo is not None
                    else value
                )
            )
    return sanitized


def create_excel_workbook_bytes(
    summary: pd.DataFrame,
    *,
    minute_detail: pd.DataFrame | None = None,
    second_detail: pd.DataFrame | None = None,
    additional_sheets: dict[str, pd.DataFrame] | None = None,
) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        prepare_frame_for_excel(summary).to_excel(writer, sheet_name="summary", index=False)
        if additional_sheets:
            for sheet_name, frame in additional_sheets.items():
                if frame is None or frame.empty:
                    continue
                safe_sheet_name = str(sheet_name)[:31]
                prepare_frame_for_excel(frame).to_excel(writer, sheet_name=safe_sheet_name, index=False)
        if minute_detail is not None and not minute_detail.empty:
            prepare_frame_for_excel(minute_detail).to_excel(writer, sheet_name="minute_detail", index=False)
        if second_detail is not None and not second_detail.empty:
            prepare_frame_for_excel(second_detail).to_excel(writer, sheet_name="second_detail", index=False)

        workbook = writer.book
        for worksheet in workbook.worksheets:
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions
            header_fill = PatternFill(fill_type="solid", fgColor="1F4E78")
            header_font = Font(color="FFFFFF", bold=True)
            for cell in worksheet[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center")
            for column_cells in worksheet.columns:
                max_length = max(len(str(cell.value or "")) for cell in column_cells)
                worksheet.column_dimensions[get_column_letter(column_cells[0].column)].width = min(max(max_length + 2, 12), 28)

        summary_sheet = workbook["summary"]
        headers = {cell.value: idx + 1 for idx, cell in enumerate(summary_sheet[1])}
        heat_columns = [
            "window_range_pct",
            "realized_vol_pct",
            "window_return_pct",
            "prev_close_to_premarket_pct",
            "premarket_to_open_pct",
            "open_to_current_pct",
        ]
        for col_name in heat_columns:
            col_idx = headers.get(col_name)
            if col_idx is None or summary_sheet.max_row < 2:
                continue
            letter = get_column_letter(col_idx)
            summary_sheet.conditional_formatting.add(
                f"{letter}2:{letter}{summary_sheet.max_row}",
                ColorScaleRule(
                    start_type="num",
                    start_value=-10,
                    start_color="C00000",
                    mid_type="num",
                    mid_value=0,
                    mid_color="FFF2CC",
                    end_type="num",
                    end_value=10,
                    end_color="63BE7B",
                ),
            )
    return output.getvalue()


def write_databento_production_workbook_from_frames(
    *,
    summary: pd.DataFrame,
    output_path: str | Path,
    generated_at: float | None = None,
    minute_detail: pd.DataFrame | None = None,
    second_detail: pd.DataFrame | None = None,
    additional_sheets: dict[str, pd.DataFrame] | None = None,
) -> WorkbookWriteResult:
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = create_excel_workbook_bytes(
        summary,
        minute_detail=minute_detail,
        second_detail=second_detail,
        additional_sheets=additional_sheets,
    )
    path.write_bytes(payload)

    rows = {"summary": int(len(summary))}
    if minute_detail is not None:
        rows["minute_detail"] = int(len(minute_detail))
    if second_detail is not None:
        rows["second_detail"] = int(len(second_detail))
    if additional_sheets:
        for name, frame in additional_sheets.items():
            if frame is None:
                continue
            rows[str(name)] = int(len(frame))

    return WorkbookWriteResult(
        output_path=path,
        generated_at=(
            datetime.fromtimestamp(float(generated_at), tz=UTC).isoformat(timespec="seconds")
            if generated_at is not None
            else datetime.now(UTC).isoformat(timespec="seconds")
        ),
        row_counts=rows,
        sheet_names=list(rows.keys()),
        canonical_upstream_artifact="databento_production_export_bundle",
    )


def write_databento_production_workbook(
    *,
    export_bundle_path: str | Path | None = None,
    output_path: str | Path,
    generated_at: float | None = None,
    include_sheets: list[str] | None = None,
) -> dict[str, Any]:
    """Write production workbook from canonical export bundle frames."""

    bundle_ref = export_bundle_path if export_bundle_path is not None else DEFAULT_PRODUCTION_EXPORT_DIR
    payload = load_export_bundle(bundle_ref, manifest_prefix="databento_volatility_production_")
    frames = payload["frames"]

    summary = frames.get("summary", pd.DataFrame())
    minute_detail = frames.get("minute_detail")
    second_detail = frames.get("second_detail")

    selected = set(include_sheets or [])
    additional_sheets: dict[str, pd.DataFrame] = {}
    for name in [
        "manifest",
        "universe",
        "daily_bars",
        "intraday",
        "ranked",
        "daily_symbol_features_full_universe",
        "premarket_window_features_full_universe",
        "premarket_features_full_universe",
        "symbol_day_diagnostics",
    ]:
        frame = frames.get(name)
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            continue
        if selected and name not in selected:
            continue
        additional_sheets[name] = frame

    result = write_databento_production_workbook_from_frames(
        summary=summary,
        output_path=output_path,
        generated_at=generated_at,
        minute_detail=minute_detail if isinstance(minute_detail, pd.DataFrame) else None,
        second_detail=second_detail if isinstance(second_detail, pd.DataFrame) else None,
        additional_sheets=additional_sheets,
    )

    return {
        "output_path": str(result.output_path),
        "generated_at": result.generated_at,
        "row_counts": result.row_counts,
        "sheet_names": result.sheet_names,
        "canonical_upstream_artifact": result.canonical_upstream_artifact,
        "bundle_manifest_path": str(payload["manifest_path"]),
    }
