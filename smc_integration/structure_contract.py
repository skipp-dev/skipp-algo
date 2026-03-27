from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CANONICAL_KEYS = ("bos", "orderblocks", "fvg", "liquidity_sweeps")
AUXILIARY_KEYS = (
    "liquidity_lines",
    "session_ranges",
    "session_pivots",
    "ipda_range",
    "htf_fvg_bias",
    "broken_fractal_signals",
)
DEFAULT_STRUCTURE_PROFILE = "hybrid_default"
DEFAULT_EVENT_LOGIC_VERSION = "v2"


@dataclass(frozen=True)
class NormalizedStructureContract:
    symbol: str
    timeframe: str
    canonical_structure: dict[str, list[dict[str, Any]]]
    structure_context: dict[str, Any]
    coverage: dict[str, Any]
    counts: dict[str, int]
    structure_profile_used: str
    event_logic_version: str
    warnings: list[str]
    auxiliary: dict[str, Any]
    diagnostics_present: bool
    auxiliary_present: bool


@dataclass(frozen=True)
class StructureContractSummary:
    mapped_structure_categories: dict[str, bool]
    mapped_auxiliary_categories: dict[str, bool]
    structure_profile_supported: bool
    diagnostics_available: bool
    auxiliary_available: bool
    structure_profiles_seen: list[str]
    event_logic_versions_seen: list[str]


def _canonical_structure(raw: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(raw, dict):
        return {key: [] for key in CANONICAL_KEYS}

    out: dict[str, list[dict[str, Any]]] = {}
    for key in CANONICAL_KEYS:
        value = raw.get(key)
        out[key] = list(value) if isinstance(value, list) else []
    return out


def _auxiliary(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}

    ipda_value = raw.get("ipda_range")
    if not isinstance(ipda_value, dict):
        ipda_value = raw.get("ipda_operating_range") if isinstance(raw.get("ipda_operating_range"), dict) else {}

    return {
        "liquidity_lines": list(raw.get("liquidity_lines", [])) if isinstance(raw.get("liquidity_lines"), list) else [],
        "session_ranges": list(raw.get("session_ranges", [])) if isinstance(raw.get("session_ranges"), list) else [],
        "session_pivots": list(raw.get("session_pivots", [])) if isinstance(raw.get("session_pivots"), list) else [],
        "ipda_range": dict(ipda_value),
        "htf_fvg_bias": dict(raw.get("htf_fvg_bias", {})) if isinstance(raw.get("htf_fvg_bias"), dict) else {},
        "broken_fractal_signals": list(raw.get("broken_fractal_signals", [])) if isinstance(raw.get("broken_fractal_signals"), list) else [],
    }


def _coverage(canonical_structure: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    has_bos = bool(canonical_structure["bos"])
    has_orderblocks = bool(canonical_structure["orderblocks"])
    has_fvg = bool(canonical_structure["fvg"])
    has_liquidity_sweeps = bool(canonical_structure["liquidity_sweeps"])

    has_any = has_bos or has_orderblocks or has_fvg or has_liquidity_sweeps
    has_all = has_bos and has_orderblocks and has_fvg and has_liquidity_sweeps
    mode = "full" if has_all else "partial" if has_any else "none"

    return {
        "mode": mode,
        "has_bos": has_bos,
        "has_orderblocks": has_orderblocks,
        "has_fvg": has_fvg,
        "has_liquidity_sweeps": has_liquidity_sweeps,
    }


def _counts(canonical_structure: dict[str, list[dict[str, Any]]], auxiliary: dict[str, Any]) -> dict[str, int]:
    return {
        "bos": len(canonical_structure["bos"]),
        "orderblocks": len(canonical_structure["orderblocks"]),
        "fvg": len(canonical_structure["fvg"]),
        "liquidity_sweeps": len(canonical_structure["liquidity_sweeps"]),
        "liquidity_lines": len(auxiliary["liquidity_lines"]),
        "session_ranges": len(auxiliary["session_ranges"]),
        "session_pivots": len(auxiliary["session_pivots"]),
        "broken_fractal_signals": len(auxiliary["broken_fractal_signals"]),
    }


def _coerce_symbol(value: Any) -> str:
    text = str(value).strip().upper()
    if not text:
        raise ValueError("structure contract symbol must not be empty")
    return text


def _coerce_timeframe(value: Any) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError("structure contract timeframe must not be empty")
    return text


def _diagnostics(raw: Any) -> tuple[dict[str, Any], bool]:
    if isinstance(raw, dict):
        return raw, bool(raw)
    return {}, False


def _normalize_single(
    payload: dict[str, Any],
    *,
    symbol: str | None = None,
    timeframe: str | None = None,
    inherited_source: dict[str, Any] | None = None,
) -> NormalizedStructureContract:
    source = payload.get("source", {}) if isinstance(payload.get("source"), dict) else {}
    if inherited_source:
        merged_source = dict(source)
        for key, value in inherited_source.items():
            merged_source.setdefault(key, value)
        source = merged_source

    contract_symbol = _coerce_symbol(symbol if symbol is not None else payload.get("symbol", ""))
    contract_timeframe = _coerce_timeframe(timeframe if timeframe is not None else payload.get("timeframe", ""))

    canonical_structure = _canonical_structure(payload.get("structure", payload))
    auxiliary = _auxiliary(payload.get("auxiliary", {}))
    diagnostics, diagnostics_present = _diagnostics(payload.get("diagnostics", {}))

    coverage = _coverage(canonical_structure)
    counts = _counts(canonical_structure, auxiliary)

    structure_profile_used = str(
        diagnostics.get("structure_profile_used", source.get("structure_profile", DEFAULT_STRUCTURE_PROFILE))
    ).strip() or DEFAULT_STRUCTURE_PROFILE

    event_logic_version = str(
        diagnostics.get("event_logic_version", source.get("event_logic_version", DEFAULT_EVENT_LOGIC_VERSION))
    ).strip() or DEFAULT_EVENT_LOGIC_VERSION

    warnings_raw = diagnostics.get("warnings", [])
    warnings = [str(item) for item in warnings_raw] if isinstance(warnings_raw, list) else []

    structure_context = {
        "structure_profile_used": structure_profile_used,
        "event_logic_version": event_logic_version,
        "coverage": {
            "has_bos": coverage["has_bos"],
            "has_orderblocks": coverage["has_orderblocks"],
            "has_fvg": coverage["has_fvg"],
            "has_liquidity_sweeps": coverage["has_liquidity_sweeps"],
        },
        "counts": {
            "bos": counts["bos"],
            "orderblocks": counts["orderblocks"],
            "fvg": counts["fvg"],
            "liquidity_sweeps": counts["liquidity_sweeps"],
        },
    }
    if warnings:
        structure_context["warnings"] = warnings

    return NormalizedStructureContract(
        symbol=contract_symbol,
        timeframe=contract_timeframe,
        canonical_structure=canonical_structure,
        structure_context=structure_context,
        coverage=coverage,
        counts=counts,
        structure_profile_used=structure_profile_used,
        event_logic_version=event_logic_version,
        warnings=warnings,
        auxiliary=auxiliary,
        diagnostics_present=diagnostics_present,
        auxiliary_present=bool(payload.get("auxiliary")) and isinstance(payload.get("auxiliary"), dict),
    )


def _select_legacy_entry(entries: list[dict[str, Any]], *, symbol: str, timeframe: str) -> dict[str, Any]:
    wanted_symbol = _coerce_symbol(symbol)
    wanted_tf = _coerce_timeframe(timeframe).upper()

    symbol_entries = [
        row
        for row in entries
        if isinstance(row, dict) and _coerce_symbol(row.get("symbol", "")) == wanted_symbol
    ]
    if not symbol_entries:
        raise ValueError(f"symbol {wanted_symbol} not present in legacy structure artifact entries")

    exact = [
        row
        for row in symbol_entries
        if str(row.get("timeframe", "")).strip().upper() == wanted_tf
    ]
    return exact[0] if exact else symbol_entries[0]


def normalize_structure_contract(payload: dict[str, Any], *, symbol: str | None = None, timeframe: str | None = None) -> NormalizedStructureContract:
    if not isinstance(payload, dict):
        raise ValueError("structure contract payload must be an object")

    entries = payload.get("entries")
    if isinstance(entries, list):
        if symbol is None:
            raise ValueError("symbol is required when normalizing legacy entries payload")
        entry = _select_legacy_entry(entries, symbol=symbol, timeframe=timeframe or "")
        return _normalize_single(
            entry,
            symbol=_coerce_symbol(symbol),
            timeframe=(timeframe or str(entry.get("timeframe", "")).strip()),
            inherited_source=payload.get("source", {}) if isinstance(payload.get("source"), dict) else None,
        )

    return _normalize_single(payload, symbol=symbol, timeframe=timeframe)


def normalize_structure_contracts_with_diagnostics(
    payload: dict[str, Any],
) -> tuple[list[NormalizedStructureContract], dict[str, int]]:
    if not isinstance(payload, dict):
        raise ValueError("structure contract payload must be an object")

    entries = payload.get("entries")
    if isinstance(entries, list):
        source = payload.get("source", {}) if isinstance(payload.get("source"), dict) else None
        out: list[NormalizedStructureContract] = []
        dropped_non_dict = 0
        dropped_value_error = 0
        for row in entries:
            if not isinstance(row, dict):
                dropped_non_dict += 1
                continue
            try:
                out.append(_normalize_single(row, inherited_source=source))
            except ValueError:
                dropped_value_error += 1
                continue
        diagnostics = {
            "entries_total": len(entries),
            "entries_normalized": len(out),
            "entries_dropped": dropped_non_dict + dropped_value_error,
            "entries_dropped_non_dict": dropped_non_dict,
            "entries_dropped_value_error": dropped_value_error,
        }
        return out, diagnostics

    single = normalize_structure_contract(payload)
    diagnostics = {
        "entries_total": 1,
        "entries_normalized": 1,
        "entries_dropped": 0,
        "entries_dropped_non_dict": 0,
        "entries_dropped_value_error": 0,
    }
    return [single], diagnostics


def normalize_structure_contracts(payload: dict[str, Any]) -> list[NormalizedStructureContract]:
    contracts, _ = normalize_structure_contracts_with_diagnostics(payload)
    return contracts


def summarize_structure_contracts(contracts: list[NormalizedStructureContract]) -> StructureContractSummary:
    structure_categories = {
        "bos": False,
        "choch": False,
        "orderblocks": False,
        "fvg": False,
        "liquidity_sweeps": False,
    }
    auxiliary_categories = {key: False for key in AUXILIARY_KEYS}

    profiles_seen: set[str] = set()
    versions_seen: set[str] = set()

    diagnostics_available = False
    auxiliary_available = False

    for contract in contracts:
        if contract.canonical_structure["bos"]:
            structure_categories["bos"] = True
            if any(
                str(item.get("kind", "")).upper() == "CHOCH"
                for item in contract.canonical_structure["bos"]
                if isinstance(item, dict)
            ):
                structure_categories["choch"] = True

        if contract.canonical_structure["orderblocks"]:
            structure_categories["orderblocks"] = True
        if contract.canonical_structure["fvg"]:
            structure_categories["fvg"] = True
        if contract.canonical_structure["liquidity_sweeps"]:
            structure_categories["liquidity_sweeps"] = True

        for key in AUXILIARY_KEYS:
            value = contract.auxiliary.get(key)
            if isinstance(value, list) and value:
                auxiliary_categories[key] = True
            elif isinstance(value, dict) and value:
                auxiliary_categories[key] = True

        if contract.structure_profile_used:
            profiles_seen.add(contract.structure_profile_used)
        if contract.event_logic_version:
            versions_seen.add(contract.event_logic_version)
        diagnostics_available = diagnostics_available or contract.diagnostics_present
        auxiliary_available = auxiliary_available or contract.auxiliary_present

    if structure_categories["bos"] and not structure_categories["choch"]:
        # BOS event family can carry CHOCH via `kind`; keep conservative default for compatibility.
        structure_categories["choch"] = True

    return StructureContractSummary(
        mapped_structure_categories=structure_categories,
        mapped_auxiliary_categories=auxiliary_categories,
        structure_profile_supported=bool(profiles_seen),
        diagnostics_available=diagnostics_available,
        auxiliary_available=auxiliary_available,
        structure_profiles_seen=sorted(profiles_seen),
        event_logic_versions_seen=sorted(versions_seen),
    )


def contract_to_dict(contract: NormalizedStructureContract) -> dict[str, Any]:
    return {
        "symbol": contract.symbol,
        "timeframe": contract.timeframe,
        "canonical_structure": contract.canonical_structure,
        "structure_context": contract.structure_context,
        "coverage": contract.coverage,
        "counts": contract.counts,
        "structure_profile_used": contract.structure_profile_used,
        "event_logic_version": contract.event_logic_version,
        "warnings": list(contract.warnings),
        "auxiliary": contract.auxiliary,
    }
