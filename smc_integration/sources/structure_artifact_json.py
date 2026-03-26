from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import SourceCapabilities, SourceDescriptor

STRUCTURE_ARTIFACT_JSON = Path(__file__).resolve().parents[2] / "reports" / "smc_structure_artifact.json"


def describe_source() -> SourceDescriptor:
    return SourceDescriptor(
        name="structure_artifact_json",
        path_hint="reports/smc_structure_artifact.json",
        capabilities=SourceCapabilities(
            has_structure=True,
            has_meta=False,
            structure_mode="partial",
            meta_mode="none",
        ),
        notes=[
            "Explicit structure artifact generated from real workbook daily_bars using existing market_structure_features logic.",
            "Current mapping emits BOS/CHOCH events only; orderblocks/fvg/liquidity_sweeps remain empty.",
        ],
    )


def _load_payload() -> dict[str, Any]:
    if not STRUCTURE_ARTIFACT_JSON.exists():
        raise FileNotFoundError(f"structure artifact source not found: {STRUCTURE_ARTIFACT_JSON}")
    payload = json.loads(STRUCTURE_ARTIFACT_JSON.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"structure artifact payload must be an object: {STRUCTURE_ARTIFACT_JSON}")
    return payload


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
