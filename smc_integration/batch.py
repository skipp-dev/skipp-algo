from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any

from .repo_sources import discover_repo_sources, select_best_source, select_best_volume_source
from .service import build_snapshot_bundle_for_symbol_timeframe


def _normalize_symbols(symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in symbols:
        symbol = str(raw).strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return out


def _descriptor_for_source_name(name: str) -> Any:
    by_name = {item.name: item for item in discover_repo_sources()}
    if name not in by_name:
        known = ", ".join(sorted(by_name))
        raise ValueError(f"unknown source {name}; expected one of: {known}")
    return by_name[name]


def _resolve_source_name(source: str) -> str:
    normalized = source.strip().lower()
    if normalized == "auto":
        return select_best_volume_source().name
    return normalized


def _bundle_file_name(symbol: str, timeframe: str) -> str:
    safe_symbol = symbol.strip().upper()
    safe_timeframe = timeframe.strip()
    return f"{safe_symbol}_{safe_timeframe}.bundle.json"


def _manifest_file_name(timeframe: str) -> str:
    safe_timeframe = timeframe.strip()
    return f"manifest_{safe_timeframe}.json"


def _has_structure(snapshot_payload: dict[str, Any]) -> bool:
    structure = snapshot_payload.get("structure", {})
    if not isinstance(structure, dict):
        return False
    for key in ("bos", "orderblocks", "fvg", "liquidity_sweeps"):
        value = structure.get(key, [])
        if isinstance(value, list) and len(value) > 0:
            return True
    return False


def _has_meta(snapshot_payload: dict[str, Any]) -> bool:
    return isinstance(snapshot_payload.get("meta"), dict)


def build_snapshot_bundles_for_symbols(
    symbols: list[str],
    timeframe: str,
    *,
    source: str = "auto",
    generated_at: float | None = None,
) -> list[dict]:
    normalized_symbols = _normalize_symbols(symbols)
    if not normalized_symbols:
        raise ValueError("symbols must contain at least one non-empty symbol")

    return [
        build_snapshot_bundle_for_symbol_timeframe(
            symbol,
            timeframe,
            source=source,
            generated_at=generated_at,
        )
        for symbol in normalized_symbols
    ]


def build_snapshot_manifest(
    *,
    symbols_requested: list[str],
    symbols_built: list[str],
    timeframe: str,
    source_name: str,
    generated_at: float,
    output_dir: Path,
    bundles: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> dict:
    source_descriptor = _descriptor_for_source_name(source_name)

    rows: list[dict[str, Any]] = []
    for symbol, bundle in zip(symbols_built, bundles):
        rows.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "bundle_path": str(output_dir / _bundle_file_name(symbol, timeframe)),
                "has_structure": _has_structure(bundle.get("snapshot", {})),
                "has_meta": _has_meta(bundle.get("snapshot", {})),
                "source": source_name,
            }
        )

    rows.sort(key=lambda item: (item["symbol"], item["timeframe"]))

    return {
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "timeframe": timeframe,
        "source": {
            "selected": source_name,
            "descriptor": source_descriptor.to_dict(),
        },
        "counts": {
            "symbols_requested": len(_normalize_symbols(symbols_requested)),
            "symbols_built": len(symbols_built),
            "errors": len(errors),
        },
        "bundles": rows,
        "errors": errors,
    }


def write_snapshot_bundles_for_symbols(
    symbols: list[str],
    timeframe: str,
    *,
    source: str = "auto",
    output_dir: str | Path = "reports/smc_snapshot_bundles",
    generated_at: float | None = None,
) -> dict:
    resolved_symbols = _normalize_symbols(symbols)
    if not resolved_symbols:
        raise ValueError("symbols must contain at least one non-empty symbol")

    out_dir = Path(output_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    resolved_source_name = _resolve_source_name(source)
    effective_generated_at = float(generated_at) if generated_at is not None else float(time.time())

    bundles: list[dict[str, Any]] = []
    built_symbols: list[str] = []
    errors: list[dict[str, Any]] = []

    for symbol in resolved_symbols:
        try:
            bundle = build_snapshot_bundle_for_symbol_timeframe(
                symbol,
                timeframe,
                source=resolved_source_name,
                generated_at=effective_generated_at,
            )
            bundle_path = out_dir / _bundle_file_name(symbol, timeframe)
            bundle_path.write_text(json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8")
            bundles.append(bundle)
            built_symbols.append(symbol)
        except Exception as exc:
            errors.append({"symbol": symbol, "message": str(exc)})

    manifest = build_snapshot_manifest(
        symbols_requested=resolved_symbols,
        symbols_built=built_symbols,
        timeframe=timeframe,
        source_name=resolved_source_name,
        generated_at=effective_generated_at,
        output_dir=out_dir,
        bundles=bundles,
        errors=errors,
    )

    manifest_path = out_dir / _manifest_file_name(timeframe)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def load_symbols_from_watchlist_source(*, source: str = "auto") -> list[str]:
    source_name = _resolve_source_name(source)
    descriptor = _descriptor_for_source_name(source_name)

    repo_root = Path(__file__).resolve().parents[1]
    source_path = repo_root / descriptor.path_hint

    if source_name == "databento_watchlist_csv":
        if not source_path.exists():
            raise FileNotFoundError(f"watchlist source not found: {source_path}")
        with source_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            symbols = [str(row.get("symbol", "")).strip().upper() for row in reader]
        resolved = _normalize_symbols(symbols)
        if not resolved:
            raise ValueError(f"watchlist source has no symbols: {source_path}")
        return resolved

    if source_name in {"tradingview_watchlist_json", "fmp_watchlist_json", "benzinga_watchlist_json"}:
        if not source_path.exists():
            raise FileNotFoundError(f"watchlist source not found: {source_path}")
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"watchlist source payload must be an object: {source_path}")

        rows: list[dict[str, Any]] = []
        for key in ("symbols", "watchlist", "items", "data"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                rows = [row for row in candidate if isinstance(row, dict)]
                if rows:
                    break

        symbols = [str(row.get("symbol", "")).strip().upper() for row in rows]
        resolved = _normalize_symbols(symbols)
        if not resolved:
            raise ValueError(f"watchlist source has no symbols: {source_path}")
        return resolved

    raise NotImplementedError(f"source {source_name} does not support watchlist symbol extraction")


def load_symbols_from_source(source: str = "auto") -> list[str]:
    return load_symbols_from_watchlist_source(source=source)
