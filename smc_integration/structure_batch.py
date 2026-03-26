from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.explicit_structure_from_bars import build_full_structure_from_bars
from scripts.load_databento_export_bundle import load_export_bundle
from smc_integration.artifact_resolution import resolve_structure_artifact_inputs

SCHEMA_VERSION = "1.0.0"
DEFAULT_WORKBOOK = Path("artifacts/smc_microstructure_exports/databento_volatility_production_workbook.xlsx")
DEFAULT_OUTPUT_DIR = Path("reports") / "smc_structure_artifacts"
DEFAULT_EXPORT_DIR = Path("artifacts") / "smc_microstructure_exports"

def _load_symbol_bars_from_canonical_exports(symbol: str, timeframe: str, export_dir: Path | None) -> pd.DataFrame | None:
    if export_dir is None:
        return None
    try:
        bundle = load_export_bundle(export_dir, manifest_prefix="databento_volatility_production_")
    except Exception:
        return None

    frames = bundle.get("frames", {})
    symbol_name = str(symbol).strip().upper()
    canonical_tf = str(timeframe).strip()

    if canonical_tf == "1D":
        daily = frames.get("daily_bars")
        if isinstance(daily, pd.DataFrame) and not daily.empty:
            bars = daily.copy()
            bars["symbol"] = bars.get("symbol", "").astype(str).str.strip().str.upper()
            bars = bars.loc[bars["symbol"].eq(symbol_name)].copy()
            if bars.empty:
                return None
            bars["timestamp"] = pd.to_datetime(bars.get("trade_date"), errors="coerce", utc=True)
            for column in ("open", "high", "low", "close"):
                bars[column] = pd.to_numeric(bars.get(column), errors="coerce")
            return bars[["symbol", "timestamp", "open", "high", "low", "close"]].dropna().reset_index(drop=True)
        return None

    intraday = frames.get("full_universe_second_detail_open")
    if isinstance(intraday, pd.DataFrame) and not intraday.empty:
        bars = intraday.copy()
        bars["symbol"] = bars.get("symbol", "").astype(str).str.strip().str.upper()
        bars = bars.loc[bars["symbol"].eq(symbol_name)].copy()
        if bars.empty:
            return None
        bars["timestamp"] = pd.to_datetime(bars.get("timestamp"), errors="coerce", utc=True)
        for column in ("open", "high", "low", "close"):
            bars[column] = pd.to_numeric(bars.get(column), errors="coerce")
        if "volume" in bars.columns:
            bars["volume"] = pd.to_numeric(bars.get("volume"), errors="coerce").fillna(0.0)
            return bars[["symbol", "timestamp", "open", "high", "low", "close", "volume"]].dropna().reset_index(drop=True)
        return bars[["symbol", "timestamp", "open", "high", "low", "close"]].dropna().reset_index(drop=True)
    return None


def _load_symbol_bars_from_workbook(workbook: Path, symbol: str) -> pd.DataFrame:
    daily_bars = pd.read_excel(workbook, sheet_name="daily_bars")
    bars = daily_bars.copy()
    bars["symbol"] = bars.get("symbol", "").astype(str).str.strip().str.upper()
    bars = bars.loc[bars["symbol"].eq(str(symbol).strip().upper())].copy()
    if bars.empty:
        raise ValueError(f"symbol {symbol} not present in workbook daily_bars")
    bars["timestamp"] = pd.to_datetime(bars.get("trade_date"), errors="coerce", utc=True)
    for column in ("open", "high", "low", "close"):
        bars[column] = pd.to_numeric(bars.get(column), errors="coerce")
    if "volume" in bars.columns:
        bars["volume"] = pd.to_numeric(bars.get("volume"), errors="coerce").fillna(0.0)
        cols = ["symbol", "timestamp", "open", "high", "low", "close", "volume"]
    else:
        cols = ["symbol", "timestamp", "open", "high", "low", "close"]
    bars = bars[cols].dropna(subset=["timestamp", "open", "high", "low", "close"]).reset_index(drop=True)
    if bars.empty:
        raise ValueError(f"symbol {symbol} has no usable OHLC rows in workbook daily_bars")
    return bars


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


def build_single_symbol_structure_artifact(
    *,
    workbook: Path | None,
    export_bundle_root: Path | None,
    symbol: str,
    timeframe: str,
    generated_at: float,
    structure_profile: str = "hybrid_default",
) -> dict[str, Any]:
    resolved_symbol = _normalize_symbol(symbol)
    canonical_bars = _load_symbol_bars_from_canonical_exports(resolved_symbol, timeframe, export_bundle_root)
    source_mode = "canonical_export_bundle"
    if canonical_bars is None or canonical_bars.empty:
        if workbook is None:
            raise ValueError("missing structure input: neither export bundle root nor workbook is available")
        canonical_bars = _load_symbol_bars_from_workbook(workbook, resolved_symbol)
        source_mode = "workbook_fallback"

    structure_payload = build_full_structure_from_bars(
        canonical_bars,
        symbol=resolved_symbol,
        timeframe=timeframe,
        structure_profile=structure_profile,
    )
    latest_ts = pd.to_datetime(canonical_bars["timestamp"], errors="coerce", utc=True).dropna().max()
    latest_close = pd.to_numeric(canonical_bars["close"], errors="coerce").dropna().iloc[-1]
    asof_ts = float(pd.Timestamp(latest_ts).timestamp()) if pd.notna(latest_ts) else float(generated_at)

    last_event = "none"
    trend_state = 0
    if structure_payload["bos"]:
        last = structure_payload["bos"][-1]
        kind = str(last.get("kind", "BOS")).upper()
        direction = str(last.get("dir", "UP")).upper()
        trend_state = 1 if direction == "UP" else -1
        if kind == "CHOCH" and direction == "UP":
            last_event = "choch_up"
        elif kind == "CHOCH" and direction == "DOWN":
            last_event = "choch_down"
        elif direction == "UP":
            last_event = "bos_up"
        else:
            last_event = "bos_down"

    has_any = any(bool(structure_payload[key]) for key in ("bos", "orderblocks", "fvg", "liquidity_sweeps"))
    has_all = all(bool(structure_payload[key]) for key in ("bos", "orderblocks", "fvg", "liquidity_sweeps"))
    coverage_mode = "full" if has_all else "partial" if has_any else "none"

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": float(generated_at),
        "symbol": resolved_symbol,
        "timeframe": timeframe,
        "producer": {
            "name": "smc_price_action_engine_v2",
            "primary_reference": "super_orderblock_fvg_bos_tools",
            "version": "2.0.0",
        },
        "source": {
            "workbook_path": str(workbook.as_posix()) if workbook is not None else None,
            "canonical_upstream": source_mode,
            "sheet": "daily_bars",
            "event_logic": "scripts.explicit_structure_from_bars.build_full_structure_from_bars",
            "structure_profile": str(structure_profile),
        },
        "coverage_mode": coverage_mode,
        "coverage": _coverage_from_structure(structure_payload, mode=coverage_mode),
        "event_evidence": {
            "last_event": last_event if last_event else "none",
            "trend_state": trend_state,
            "reference_close": float(latest_close),
        },
        "structure": structure_payload,
    }


def build_structure_artifact_manifest(
    *,
    timeframe: str,
    generated_at: float,
    workbook: Path | None,
    export_bundle_root: Path | None,
    artifacts: list[StructureArtifactRow],
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    resolution_mode: str,
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
            "name": "smc_price_action_engine_v2",
            "primary_reference": "super_orderblock_fvg_bos_tools",
            "version": "2.0.0",
            "upstream": str(workbook.as_posix()) if workbook is not None else None,
        },
        "resolution_mode": resolution_mode,
        "resolved_inputs": {
            "workbook_path": str(workbook.as_posix()) if workbook is not None else None,
            "export_bundle_root": str(export_bundle_root.as_posix()) if export_bundle_root is not None else None,
        },
        "counts": {
            "symbols_requested": len(_normalize_symbols(symbols_requested)),
            "artifacts_written": len(artifacts_rows),
            "errors": len(errors),
        },
        "artifacts": artifacts_rows,
        "errors": list(errors),
        "warnings": list(warnings),
    }


def _row_from_existing_artifact(path: Path, symbol: str, timeframe: str) -> StructureArtifactRow | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None

    coverage = payload.get("coverage", {}) if isinstance(payload.get("coverage"), dict) else {}
    mode = str(payload.get("coverage_mode", "none"))
    structure = payload.get("structure", {}) if isinstance(payload.get("structure"), dict) else {}

    return StructureArtifactRow(
        symbol=symbol,
        timeframe=timeframe,
        artifact_path=_relative_repo_path(path),
        coverage_mode=mode,
        has_bos=bool(coverage.get("has_bos", bool(structure.get("bos")))),
        has_orderblocks=bool(coverage.get("has_orderblocks", bool(structure.get("orderblocks")))),
        has_fvg=bool(coverage.get("has_fvg", bool(structure.get("fvg")))),
        has_liquidity_sweeps=bool(coverage.get("has_liquidity_sweeps", bool(structure.get("liquidity_sweeps")))),
    )


def _existing_artifact_rows(output_dir: Path, symbols: list[str], timeframe: str) -> list[StructureArtifactRow]:
    rows: list[StructureArtifactRow] = []
    for symbol in symbols:
        candidate = output_dir / _artifact_file_name(symbol, timeframe)
        if not candidate.exists():
            continue
        row = _row_from_existing_artifact(candidate, symbol, timeframe)
        if row is not None:
            rows.append(row)
    return rows


def write_structure_artifacts_from_workbook(
    *,
    workbook: Path | None,
    timeframe: str,
    symbols: list[str] | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    export_bundle_root: Path | None = None,
    generated_at: float | None = None,
    allow_missing_inputs: bool = True,
    structure_profile: str = "hybrid_default",
) -> dict[str, Any]:
    resolved_inputs = resolve_structure_artifact_inputs(
        explicit_workbook_path=str(workbook) if workbook is not None else None,
        explicit_export_bundle_root=str(export_bundle_root) if export_bundle_root is not None else None,
        explicit_structure_artifacts_dir=str(output_dir),
    )

    resolved_workbook = resolved_inputs.get("workbook_path")
    if resolved_workbook is not None and not isinstance(resolved_workbook, Path):
        resolved_workbook = Path(str(resolved_workbook))
    resolved_bundle_root = resolved_inputs.get("export_bundle_root")
    if resolved_bundle_root is not None and not isinstance(resolved_bundle_root, Path):
        resolved_bundle_root = Path(str(resolved_bundle_root))
    warnings: list[dict[str, Any]] = list(resolved_inputs.get("warnings", []))
    resolver_errors: list[dict[str, Any]] = list(resolved_inputs.get("errors", []))

    effective_generated_at = float(generated_at) if generated_at is not None else float(time.time())
    resolved_timeframe = str(timeframe).strip()
    if not resolved_timeframe:
        raise ValueError("timeframe must not be empty")

    output_dir.mkdir(parents=True, exist_ok=True)

    requested_symbols = _normalize_symbols(symbols) if symbols else []
    if not requested_symbols and resolved_workbook is not None:
        daily_bars = pd.read_excel(resolved_workbook, sheet_name="daily_bars")
        requested_symbols = _derive_symbols_from_workbook(daily_bars)
    if not requested_symbols:
        raise ValueError("symbols must not be empty when workbook is unavailable")

    artifact_rows: list[StructureArtifactRow] = []
    errors: list[dict[str, Any]] = []

    if resolved_workbook is None and resolved_bundle_root is None:
        existing = _existing_artifact_rows(output_dir, requested_symbols, resolved_timeframe)
        if existing:
            warnings.append(
                {
                    "code": "USING_PREEXISTING_STRUCTURE_ARTIFACTS",
                    "message": "No workbook/export bundle found; reusing preexisting structure artifacts.",
                }
            )
            manifest = build_structure_artifact_manifest(
                timeframe=resolved_timeframe,
                generated_at=effective_generated_at,
                workbook=None,
                export_bundle_root=None,
                artifacts=existing,
                errors=[],
                warnings=warnings,
                resolution_mode="preexisting_artifacts",
                symbols_requested=requested_symbols,
            )
            manifest_path = output_dir / _manifest_file_name(resolved_timeframe)
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            manifest["manifest_path"] = _relative_repo_path(manifest_path)
            return manifest

        errors.extend(resolver_errors)
        errors.append(
            {
                "code": "MISSING_STRUCTURE_INPUTS",
                "message": "No workbook/export bundle available and no preexisting artifacts found.",
                "timeframe": resolved_timeframe,
            }
        )

        manifest = build_structure_artifact_manifest(
            timeframe=resolved_timeframe,
            generated_at=effective_generated_at,
            workbook=None,
            export_bundle_root=None,
            artifacts=[],
            errors=errors,
            warnings=warnings,
            resolution_mode=str(resolved_inputs.get("resolution_mode", "missing")),
            symbols_requested=requested_symbols,
        )
        manifest_path = output_dir / _manifest_file_name(resolved_timeframe)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest["manifest_path"] = _relative_repo_path(manifest_path)
        if not allow_missing_inputs:
            raise ValueError("missing structure inputs: workbook/export bundle and preexisting artifacts are unavailable")
        return manifest

    for symbol in requested_symbols:
        artifact_path = output_dir / _artifact_file_name(symbol, resolved_timeframe)
        try:
            payload = build_single_symbol_structure_artifact(
                workbook=resolved_workbook,
                export_bundle_root=resolved_bundle_root,
                symbol=symbol,
                timeframe=resolved_timeframe,
                generated_at=effective_generated_at,
                structure_profile=structure_profile,
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
                "code": "BUILD_SYMBOL_ARTIFACT_FAILED",
                "symbol": symbol,
                "timeframe": resolved_timeframe,
                "error": str(exc),
            })

    manifest = build_structure_artifact_manifest(
        timeframe=resolved_timeframe,
        generated_at=effective_generated_at,
        workbook=resolved_workbook,
        export_bundle_root=resolved_bundle_root,
        artifacts=artifact_rows,
        errors=errors,
        warnings=warnings,
        resolution_mode=str(resolved_inputs.get("resolution_mode", "canonical")),
        symbols_requested=requested_symbols,
    )

    manifest_path = output_dir / _manifest_file_name(resolved_timeframe)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest["manifest_path"] = _relative_repo_path(manifest_path)
    return manifest
