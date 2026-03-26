from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

import pandas as pd

from smc_core.ids import bos_id
from scripts.market_structure_features import build_market_structure_feature_frame

SCHEMA_VERSION = "1.0.0"
DEFAULT_WORKBOOK = Path("databento_volatility_production_20260307_114724.xlsx")
DEFAULT_OUTPUT_DIR = Path("reports") / "smc_structure_artifacts"


@dataclass(frozen=True)
class StructureArtifactRow:
    symbol: str
    timeframe: str
    artifact_path: str
    coverage_mode: str
    has_bos: bool
    has_orderblocks: bool
    has_fvg: bool
    has_liquidity_sweeps: bool


def _normalize_symbol(value: Any) -> str:
    if isinstance(value, tuple) and value:
        value = value[0]
    symbol = str(value).strip().upper()
    if symbol.startswith("(") and symbol.endswith(")") and "," in symbol:
        symbol = symbol.strip("() ").split(",", 1)[0].strip().strip("'").strip('"')
    if not symbol:
        raise ValueError("symbol must not be empty")
    return symbol


def _normalize_symbols(symbols: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        symbol = _normalize_symbol(raw)
        if symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return out


def _daily_asof_ts(value: Any) -> float:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"invalid trade_date: {value}")
    date_value = parsed.date()
    return datetime(date_value.year, date_value.month, date_value.day, tzinfo=UTC).timestamp()


def _event_from_last_event(*, symbol: str, timeframe: str, last_event: str, asof_ts: float, close_price: float) -> list[dict[str, Any]]:
    normalized = str(last_event).strip().lower()
    if normalized not in {"bos_up", "bos_down", "choch_up", "choch_down"}:
        return []

    kind = cast(Literal["BOS", "CHOCH"], "BOS" if normalized.startswith("bos") else "CHOCH")
    direction = cast(Literal["UP", "DOWN"], "UP" if normalized.endswith("up") else "DOWN")
    price = float(close_price)

    return [
        {
            "id": bos_id(
                symbol=symbol,
                timeframe=timeframe,
                anchor_ts=asof_ts,
                kind=kind,
                dir=direction,
                price=price,
            ),
            "time": asof_ts,
            "price": price,
            "kind": kind,
            "dir": direction,
        }
    ]


def _coverage_from_structure(structure: dict[str, Any], *, mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "has_bos": bool(structure.get("bos")),
        "has_orderblocks": bool(structure.get("orderblocks")),
        "has_fvg": bool(structure.get("fvg")),
        "has_liquidity_sweeps": bool(structure.get("liquidity_sweeps")),
    }


def _artifact_file_name(symbol: str, timeframe: str) -> str:
    return f"{symbol}_{timeframe}.structure.json"


def _manifest_file_name(timeframe: str) -> str:
    return f"manifest_{timeframe}.json"


def _relative_repo_path(path: Path) -> str:
    repo_root = Path(__file__).resolve().parents[1]
    try:
        return str(path.resolve().relative_to(repo_root.resolve()).as_posix())
    except ValueError:
        return str(path.as_posix())


def _derive_symbols_from_workbook(daily_bars: pd.DataFrame) -> list[str]:
    if "symbol" not in daily_bars.columns:
        raise ValueError("daily_bars sheet is missing symbol column")
    symbols = [str(item).strip().upper() for item in daily_bars["symbol"].dropna().tolist() if str(item).strip()]
    resolved = _normalize_symbols(symbols)
    if not resolved:
        raise ValueError("no symbols found in workbook daily_bars")
    return resolved


def _build_latest_rows(daily_bars: pd.DataFrame) -> pd.DataFrame:
    bars = daily_bars.copy()
    bars["trade_date"] = pd.to_datetime(bars.get("trade_date"), errors="coerce")
    bars["timestamp"] = pd.to_datetime(bars.get("trade_date"), errors="coerce")
    bars["symbol"] = bars.get("symbol", "").astype(str).str.strip().str.upper()
    bars["close"] = pd.to_numeric(bars.get("close"), errors="coerce")
    bars = bars.dropna(subset=["trade_date", "timestamp", "symbol", "close"]).copy()
    if bars.empty:
        raise ValueError("daily_bars sheet has no usable rows")
    latest_rows = bars.sort_values(["symbol", "trade_date"]).groupby("symbol", as_index=False).tail(1)
    return bars, latest_rows


def _structure_features(daily_bars: pd.DataFrame) -> pd.DataFrame:
    features = build_market_structure_feature_frame(
        daily_bars,
        group_keys=["symbol"],
        prefix="structure",
    )
    if features.empty:
        raise ValueError("no structure features could be computed from daily_bars")
    return features


def build_single_symbol_structure_artifact(
    *,
    workbook: Path,
    symbol: str,
    timeframe: str,
    generated_at: float,
) -> dict[str, Any]:
    if not workbook.exists():
        raise FileNotFoundError(f"workbook not found: {workbook}")

    daily_bars = pd.read_excel(workbook, sheet_name="daily_bars")
    bars, latest_rows = _build_latest_rows(daily_bars)
    features = _structure_features(bars)

    resolved_symbol = _normalize_symbol(symbol)
    latest_by_symbol = {
        str(row.symbol).strip().upper(): row
        for row in latest_rows[["symbol", "trade_date", "close"]].itertuples(index=False)
    }
    feature_by_symbol = {
        _normalize_symbol(getattr(row, "symbol", "")): row
        for row in features.itertuples(index=False)
    }

    if resolved_symbol not in latest_by_symbol or resolved_symbol not in feature_by_symbol:
        raise ValueError(f"symbol {resolved_symbol} not present in workbook daily_bars")

    latest = latest_by_symbol[resolved_symbol]
    feat = feature_by_symbol[resolved_symbol]

    asof_ts = _daily_asof_ts(latest.trade_date)
    last_event = str(getattr(feat, "structure_last_event", "none") or "none").strip().lower()
    trend_state_raw = int(getattr(feat, "structure_trend_state", 0) or 0)
    trend_state = 1 if trend_state_raw > 0 else -1 if trend_state_raw < 0 else 0

    bos_events = _event_from_last_event(
        symbol=resolved_symbol,
        timeframe=timeframe,
        last_event=last_event,
        asof_ts=asof_ts,
        close_price=float(latest.close),
    )
    coverage_mode = "partial" if bos_events else "none"
    structure_payload = {
        "bos": bos_events,
        "orderblocks": [],
        "fvg": [],
        "liquidity_sweeps": [],
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": float(generated_at),
        "symbol": resolved_symbol,
        "timeframe": timeframe,
        "source": {
            "workbook_path": str(workbook.as_posix()),
            "sheet": "daily_bars",
            "event_logic": "scripts.market_structure_features.build_market_structure_feature_frame",
        },
        "coverage_mode": coverage_mode,
        "coverage": _coverage_from_structure(structure_payload, mode=coverage_mode),
        "event_evidence": {
            "last_event": last_event if last_event else "none",
            "trend_state": trend_state,
        },
        "structure": structure_payload,
    }


def build_structure_artifact_manifest(
    *,
    timeframe: str,
    generated_at: float,
    workbook: Path,
    artifacts: list[StructureArtifactRow],
    errors: list[dict[str, Any]],
    symbols_requested: list[str],
) -> dict[str, Any]:
    artifacts_rows = [
        {
            "symbol": row.symbol,
            "timeframe": row.timeframe,
            "artifact_path": row.artifact_path,
            "coverage_mode": row.coverage_mode,
            "has_bos": row.has_bos,
            "has_orderblocks": row.has_orderblocks,
            "has_fvg": row.has_fvg,
            "has_liquidity_sweeps": row.has_liquidity_sweeps,
        }
        for row in sorted(artifacts, key=lambda item: (item.symbol, item.timeframe))
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": float(generated_at),
        "timeframe": timeframe,
        "producer": {
            "name": "export_smc_structure_artifacts_from_workbook",
            "upstream": str(workbook.as_posix()),
        },
        "counts": {
            "symbols_requested": len(_normalize_symbols(symbols_requested)),
            "artifacts_written": len(artifacts_rows),
            "errors": len(errors),
        },
        "artifacts": artifacts_rows,
        "errors": list(errors),
    }


def write_structure_artifacts_from_workbook(
    *,
    workbook: Path,
    timeframe: str,
    symbols: list[str] | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at: float | None = None,
) -> dict[str, Any]:
    if not workbook.exists():
        raise FileNotFoundError(f"workbook not found: {workbook}")

    effective_generated_at = float(generated_at) if generated_at is not None else float(time.time())
    resolved_timeframe = str(timeframe).strip()
    if not resolved_timeframe:
        raise ValueError("timeframe must not be empty")

    daily_bars = pd.read_excel(workbook, sheet_name="daily_bars")
    requested_symbols = _normalize_symbols(symbols) if symbols else _derive_symbols_from_workbook(daily_bars)

    output_dir.mkdir(parents=True, exist_ok=True)

    artifact_rows: list[StructureArtifactRow] = []
    errors: list[dict[str, Any]] = []

    for symbol in requested_symbols:
        artifact_path = output_dir / _artifact_file_name(symbol, resolved_timeframe)
        try:
            payload = build_single_symbol_structure_artifact(
                workbook=workbook,
                symbol=symbol,
                timeframe=resolved_timeframe,
                generated_at=effective_generated_at,
            )
            artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            structure = payload["structure"]
            artifact_rows.append(
                StructureArtifactRow(
                    symbol=symbol,
                    timeframe=resolved_timeframe,
                    artifact_path=_relative_repo_path(artifact_path),
                    coverage_mode=str(payload.get("coverage_mode", "none")),
                    has_bos=bool(payload.get("coverage", {}).get("has_bos", bool(structure.get("bos")))),
                    has_orderblocks=bool(payload.get("coverage", {}).get("has_orderblocks", bool(structure.get("orderblocks")))),
                    has_fvg=bool(payload.get("coverage", {}).get("has_fvg", bool(structure.get("fvg")))),
                    has_liquidity_sweeps=bool(payload.get("coverage", {}).get("has_liquidity_sweeps", bool(structure.get("liquidity_sweeps")))),
                )
            )
        except Exception as exc:
            errors.append({
                "symbol": symbol,
                "timeframe": resolved_timeframe,
                "error": str(exc),
            })

    manifest = build_structure_artifact_manifest(
        timeframe=resolved_timeframe,
        generated_at=effective_generated_at,
        workbook=workbook,
        artifacts=artifact_rows,
        errors=errors,
        symbols_requested=requested_symbols,
    )

    manifest_path = output_dir / _manifest_file_name(resolved_timeframe)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest["manifest_path"] = _relative_repo_path(manifest_path)
    return manifest
