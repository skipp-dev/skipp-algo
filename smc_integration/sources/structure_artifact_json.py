from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import SourceCapabilities, SourceDescriptor

REPO_ROOT = Path(__file__).resolve().parents[2]
STRUCTURE_ARTIFACT_JSON = REPO_ROOT / "reports" / "smc_structure_artifact.json"
STRUCTURE_ARTIFACTS_DIR = REPO_ROOT / "reports" / "smc_structure_artifacts"


def describe_source() -> SourceDescriptor:
    return SourceDescriptor(
        name="structure_artifact_json",
        path_hint="reports/smc_structure_artifacts/manifest_{timeframe}.json",
        capabilities=SourceCapabilities(
            has_structure=True,
            has_meta=False,
            structure_mode="partial",
            meta_mode="none",
        ),
        notes=[
            "Manifest-aware explicit structure artifacts generated from real workbook daily_bars using existing market_structure_features logic.",
            "Current mapping emits BOS/CHOCH events only; orderblocks/fvg/liquidity_sweeps remain empty.",
            "Falls back to legacy single-artifact source when batch artifact-set is unavailable.",
        ],
    )


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"structure artifact payload must be an object: {path}")
    return payload


def _load_payload() -> dict[str, Any]:
    if not STRUCTURE_ARTIFACT_JSON.exists():
        raise FileNotFoundError(f"structure artifact source not found: {STRUCTURE_ARTIFACT_JSON}")
    return _load_json(STRUCTURE_ARTIFACT_JSON)


def _manifest_path_for_timeframe(timeframe: str) -> Path:
    tf = str(timeframe).strip()
    return STRUCTURE_ARTIFACTS_DIR / f"manifest_{tf}.json"


def _artifact_path_for_symbol_timeframe(symbol: str, timeframe: str) -> Path:
    safe_symbol = symbol.strip().upper()
    safe_tf = str(timeframe).strip()
    return STRUCTURE_ARTIFACTS_DIR / f"{safe_symbol}_{safe_tf}.structure.json"


def _resolve_from_manifest(symbol: str, timeframe: str) -> Path | None:
    manifest_path = _manifest_path_for_timeframe(timeframe)
    if not manifest_path.exists():
        return None

    payload = _load_json(manifest_path)
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        return None

    wanted_symbol = symbol.strip().upper()
    wanted_tf = str(timeframe).strip()
    for row in artifacts:
        if not isinstance(row, dict):
            continue
        row_symbol = str(row.get("symbol", "")).strip().upper()
        row_tf = str(row.get("timeframe", "")).strip()
        if row_symbol != wanted_symbol or row_tf != wanted_tf:
            continue
        raw_path = str(row.get("artifact_path", "")).strip()
        if not raw_path:
            continue
        path = (REPO_ROOT / raw_path).resolve()
        if path.exists():
            return path
    return None


def _resolve_artifact_file(symbol: str, timeframe: str) -> Path | None:
    from_manifest = _resolve_from_manifest(symbol, timeframe)
    if from_manifest is not None:
        return from_manifest

    deterministic = _artifact_path_for_symbol_timeframe(symbol, timeframe)
    if deterministic.exists():
        return deterministic
    return None


def has_artifact_for_symbol_timeframe(symbol: str, timeframe: str) -> bool:
    return _resolve_artifact_file(symbol, timeframe) is not None


def has_any_structure_artifact() -> bool:
    if STRUCTURE_ARTIFACT_JSON.exists():
        return True
    if not STRUCTURE_ARTIFACTS_DIR.exists():
        return False
    if any(STRUCTURE_ARTIFACTS_DIR.glob("manifest_*.json")):
        return True
    if any(STRUCTURE_ARTIFACTS_DIR.glob("*.structure.json")):
        return True
    return False


def _entry_matches_timeframe(entry: dict[str, Any], timeframe: str) -> bool:
    return str(entry.get("timeframe", "")).strip().upper() == str(timeframe).strip().upper()


def _select_symbol_entry(payload: dict[str, Any], symbol: str, timeframe: str) -> dict[str, Any]:
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("structure artifact payload has no entries list")

    wanted_symbol = symbol.strip().upper()
    if not wanted_symbol:
        raise ValueError("symbol must not be empty")

    symbol_entries = [
        entry
        for entry in entries
        if isinstance(entry, dict)
        and str(entry.get("symbol", "")).strip().upper() == wanted_symbol
    ]
    if not symbol_entries:
        raise ValueError(f"symbol {wanted_symbol} not present in structure artifact source")

    exact = [entry for entry in symbol_entries if _entry_matches_timeframe(entry, timeframe)]
    if exact:
        return exact[0]

    return symbol_entries[0]


def load_raw_structure_input(symbol: str, timeframe: str) -> dict[str, Any]:
    artifact_file = _resolve_artifact_file(symbol, timeframe)
    if artifact_file is not None:
        artifact_payload = _load_json(artifact_file)
        structure = artifact_payload.get("structure")
        if not isinstance(structure, dict):
            raise ValueError(f"structure artifact file missing structure object: {artifact_file}")
        return {
            "bos": list(structure.get("bos", [])),
            "orderblocks": list(structure.get("orderblocks", [])),
            "fvg": list(structure.get("fvg", [])),
            "liquidity_sweeps": list(structure.get("liquidity_sweeps", [])),
        }

    # Backward-compatibility: legacy single artifact with entries array.
    payload = _load_payload()
    entry = _select_symbol_entry(payload, symbol, timeframe)

    structure = entry.get("structure")
    if not isinstance(structure, dict):
        raise ValueError("structure artifact entry is missing structure object")

    return {
        "bos": list(structure.get("bos", [])),
        "orderblocks": list(structure.get("orderblocks", [])),
        "fvg": list(structure.get("fvg", [])),
        "liquidity_sweeps": list(structure.get("liquidity_sweeps", [])),
    }


def load_raw_meta_input(symbol: str, timeframe: str) -> dict[str, Any]:
    del symbol, timeframe
    raise ValueError("structure_artifact_json does not provide raw meta input")
