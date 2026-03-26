from __future__ import annotations

from pathlib import Path
from typing import Any

from smc_adapters import (
    build_snapshot_from_raw,
    snapshot_to_dashboard_payload,
    snapshot_to_pine_payload,
)
from smc_core.types import SmcSnapshot

from .repo_sources import load_raw_meta_input, load_raw_structure_input


def _build_snapshot_from_loaded_raw(
    raw_structure: dict[str, Any],
    raw_meta: dict[str, Any],
    *,
    generated_at: float | None = None,
) -> SmcSnapshot:
    return build_snapshot_from_raw(raw_structure, raw_meta, generated_at=generated_at)


def build_snapshot_for_symbol_timeframe(
    symbol: str,
    timeframe: str,
    *,
    generated_at: float | None = None,
    repo_root: Path | str | None = None,
    source_csv_path: Path | str | None = None,
) -> SmcSnapshot:
    raw_structure = load_raw_structure_input(
        symbol,
        timeframe,
        repo_root=repo_root,
        source_csv_path=source_csv_path,
    )
    raw_meta = load_raw_meta_input(
        symbol,
        timeframe,
        repo_root=repo_root,
        source_csv_path=source_csv_path,
    )
    return _build_snapshot_from_loaded_raw(raw_structure, raw_meta, generated_at=generated_at)


def build_dashboard_payload_for_symbol_timeframe(
    symbol: str,
    timeframe: str,
    *,
    generated_at: float | None = None,
    repo_root: Path | str | None = None,
    source_csv_path: Path | str | None = None,
) -> dict:
    snapshot = build_snapshot_for_symbol_timeframe(
        symbol,
        timeframe,
        generated_at=generated_at,
        repo_root=repo_root,
        source_csv_path=source_csv_path,
    )
    return snapshot_to_dashboard_payload(snapshot)


def build_pine_payload_for_symbol_timeframe(
    symbol: str,
    timeframe: str,
    *,
    generated_at: float | None = None,
    repo_root: Path | str | None = None,
    source_csv_path: Path | str | None = None,
) -> dict:
    snapshot = build_snapshot_for_symbol_timeframe(
        symbol,
        timeframe,
        generated_at=generated_at,
        repo_root=repo_root,
        source_csv_path=source_csv_path,
    )
    return snapshot_to_pine_payload(snapshot)
