from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import SourceCapabilities, SourceDescriptor
from smc_integration.structure_contract import (
    contract_to_dict,
    normalize_structure_contract,
    normalize_structure_contracts_with_diagnostics,
    summarize_structure_contracts,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
STRUCTURE_ARTIFACT_JSON = REPO_ROOT / "reports" / "smc_structure_artifact.json"
STRUCTURE_ARTIFACTS_DIR = REPO_ROOT / "reports" / "smc_structure_artifacts"


def _health_issue(code: str, message: str, *, path: Path | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "code": str(code),
        "message": str(message),
    }
    if path is not None:
        out["path"] = str(path.as_posix())
    return out


def _validate_contract_identity(contract_payload: dict[str, Any], *, symbol: str, timeframe: str, path: Path) -> None:
    expected_symbol = str(symbol).strip().upper()
    expected_timeframe = str(timeframe).strip().upper()
    actual_symbol = str(contract_payload.get("symbol", "")).strip().upper()
    actual_timeframe = str(contract_payload.get("timeframe", "")).strip().upper()

    if actual_symbol != expected_symbol:
        raise ValueError(
            f"artifact symbol mismatch for {path}: expected={expected_symbol} actual={actual_symbol or '<empty>'}"
        )
    if actual_timeframe != expected_timeframe:
        raise ValueError(
            f"artifact timeframe mismatch for {path}: expected={expected_timeframe} actual={actual_timeframe or '<empty>'}"
        )


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
            "Manifest-aware explicit structure artifacts generated from canonical Databento bars with workbook fallback.",
            "Current mapping emits deterministic BOS/CHOCH/orderblocks/FVG/liquidity-sweeps when detectable from available bars.",
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
        raise ValueError(f"manifest artifacts must be a list: {manifest_path}")

    wanted_symbol = symbol.strip().upper()
    wanted_tf = str(timeframe).strip()
    saw_symbol_timeframe_row = False
    for row in artifacts:
        if not isinstance(row, dict):
            continue
        row_symbol = str(row.get("symbol", "")).strip().upper()
        row_tf = str(row.get("timeframe", "")).strip()
        if row_symbol != wanted_symbol or row_tf != wanted_tf:
            continue
        saw_symbol_timeframe_row = True
        raw_path = str(row.get("artifact_path", "")).strip()
        if not raw_path:
            raise ValueError(
                f"manifest row is missing artifact_path for symbol={wanted_symbol} timeframe={wanted_tf}: {manifest_path}"
            )
        path = (REPO_ROOT / raw_path).resolve()
        if path.exists():
            return path
        raise ValueError(
            f"manifest artifact_path does not exist for symbol={wanted_symbol} timeframe={wanted_tf}: {raw_path}"
        )
    if saw_symbol_timeframe_row:
        raise ValueError(
            f"manifest row for symbol/timeframe could not resolve an artifact file: symbol={wanted_symbol} timeframe={wanted_tf}"
        )
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
    if _resolve_artifact_file(symbol, timeframe) is not None:
        return True
    # Legacy single-artifact fallback: verify the symbol is actually present.
    if STRUCTURE_ARTIFACT_JSON.exists():
        return _legacy_artifact_has_symbol(symbol)
    return False


def _legacy_artifact_has_symbol(symbol: str) -> bool:
    """Check if the legacy single artifact contains entries for the given symbol."""
    try:
        payload = _load_json(STRUCTURE_ARTIFACT_JSON)
        entries = payload.get("entries")
        if not isinstance(entries, list):
            return False
        wanted = symbol.strip().upper()
        return any(
            str(e.get("symbol", "")).strip().upper() == wanted
            for e in entries
            if isinstance(e, dict)
        )
    except (json.JSONDecodeError, OSError):
        return False


def resolve_artifact_mode(symbol: str, timeframe: str) -> str:
    """Return the resolution mode that the loader would use.

    Possible values:
    - ``"manifest"`` — resolved via a timeframe manifest file
    - ``"deterministic"`` — resolved via ``SYMBOL_TIMEFRAME.structure.json``
    - ``"legacy_single"`` — resolved via the legacy single-file artifact
    - ``"none"`` — no artifact available
    """
    from_manifest = _resolve_from_manifest(symbol, timeframe)
    if from_manifest is not None:
        return "manifest"
    deterministic = _artifact_path_for_symbol_timeframe(symbol, timeframe)
    if deterministic.exists():
        return "deterministic"
    if STRUCTURE_ARTIFACT_JSON.exists() and _legacy_artifact_has_symbol(symbol):
        return "legacy_single"
    return "none"


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


def _iter_manifest_artifacts() -> tuple[list[Path], list[dict[str, Any]]]:
    if not STRUCTURE_ARTIFACTS_DIR.exists():
        return [], []

    artifacts: list[Path] = []
    issues: list[dict[str, Any]] = []
    for manifest_path in sorted(STRUCTURE_ARTIFACTS_DIR.glob("manifest_*.json")):
        try:
            payload = _load_json(manifest_path)
        except Exception as exc:
            issues.append(
                _health_issue(
                    "INVALID_MANIFEST_JSON",
                    f"failed to parse manifest JSON: {exc}",
                    path=manifest_path,
                )
            )
            continue
        rows = payload.get("artifacts")
        if not isinstance(rows, list):
            issues.append(
                _health_issue(
                    "INVALID_MANIFEST_SHAPE",
                    "manifest is missing a list-valued artifacts field",
                    path=manifest_path,
                )
            )
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw_path = str(row.get("artifact_path", "")).strip()
            if not raw_path:
                continue
            resolved = (REPO_ROOT / raw_path).resolve()
            if resolved.exists() and resolved not in artifacts:
                artifacts.append(resolved)
            elif not resolved.exists():
                issues.append(
                    _health_issue(
                        "MISSING_ARTIFACT_PATH",
                        f"manifest artifact_path does not exist: {raw_path}",
                        path=manifest_path,
                    )
                )

    if artifacts:
        return artifacts, issues

    # Fallback for deterministic artifact naming when manifest rows are missing.
    return sorted(STRUCTURE_ARTIFACTS_DIR.glob("*.structure.json")), issues


def _iter_normalized_contracts() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    contracts: list[dict[str, Any]] = []
    health_issues: list[dict[str, Any]] = []

    artifact_paths, manifest_issues = _iter_manifest_artifacts()
    health_issues.extend(manifest_issues)

    for artifact_path in artifact_paths:
        try:
            payload = _load_json(artifact_path)
            normalized_contract = normalize_structure_contract(payload)
        except Exception as exc:
            health_issues.append(
                _health_issue(
                    "INVALID_STRUCTURE_ARTIFACT",
                    f"failed to normalize structure artifact: {exc}",
                    path=artifact_path,
                )
            )
            continue
        contracts.append(contract_to_dict(normalized_contract))

    if contracts:
        return contracts, health_issues

    if STRUCTURE_ARTIFACT_JSON.exists():
        try:
            legacy = _load_payload()
            normalized_contracts, diagnostics = normalize_structure_contracts_with_diagnostics(legacy)
            if diagnostics.get("entries_dropped", 0) > 0:
                health_issues.append(
                    _health_issue(
                        "LEGACY_ENTRIES_DROPPED",
                        "legacy entries payload contained rows that could not be normalized",
                        path=STRUCTURE_ARTIFACT_JSON,
                    )
                )
            for contract in normalized_contracts:
                contracts.append(contract_to_dict(contract))
        except Exception as exc:
            health_issues.append(
                _health_issue(
                    "INVALID_LEGACY_STRUCTURE_ARTIFACT",
                    f"failed to normalize legacy structure artifact payload: {exc}",
                    path=STRUCTURE_ARTIFACT_JSON,
                )
            )

    return contracts, health_issues


def discover_normalized_contract_summary() -> dict[str, Any]:
    contracts, health_issues = _iter_normalized_contracts()
    if not contracts:
        return {
            "mapped_structure_categories": {
                "bos": False,
                "choch": False,
                "orderblocks": False,
                "fvg": False,
                "liquidity_sweeps": False,
            },
            "mapped_auxiliary_categories": {
                "liquidity_lines": False,
                "session_ranges": False,
                "session_pivots": False,
                "ipda_range": False,
                "htf_fvg_bias": False,
                "broken_fractal_signals": False,
            },
            "structure_profile_supported": False,
            "diagnostics_available": False,
            "auxiliary_available": False,
            "structure_profiles_seen": [],
            "event_logic_versions_seen": [],
            "health": {
                "issue_count": len(health_issues),
                "issues": health_issues,
                "contracts_loaded": 0,
            },
        }

    summary = summarize_structure_contracts(
        [
            normalize_structure_contract(
                {
                    "symbol": contract.get("symbol"),
                    "timeframe": contract.get("timeframe"),
                    "structure": contract.get("canonical_structure", {}),
                    "auxiliary": contract.get("auxiliary", {}),
                    "diagnostics": {
                        "structure_profile_used": contract.get("structure_profile_used"),
                        "event_logic_version": contract.get("event_logic_version"),
                        "warnings": contract.get("warnings", []),
                    },
                }
            )
            for contract in contracts
        ]
    )

    return {
        "mapped_structure_categories": dict(summary.mapped_structure_categories),
        "mapped_auxiliary_categories": summary.mapped_auxiliary_categories,
        "structure_profile_supported": summary.structure_profile_supported,
        "diagnostics_available": summary.diagnostics_available,
        "auxiliary_available": summary.auxiliary_available,
        "structure_profiles_seen": summary.structure_profiles_seen,
        "event_logic_versions_seen": summary.event_logic_versions_seen,
        "health": {
            "issue_count": len(health_issues),
            "issues": health_issues,
            "contracts_loaded": len(contracts),
        },
    }


def discover_contract_capabilities() -> dict[str, Any]:
    return discover_normalized_contract_summary()


def discover_contract_health() -> dict[str, Any]:
    summary = discover_normalized_contract_summary()
    health = summary.get("health", {})
    return dict(health) if isinstance(health, dict) else {"issue_count": 0, "issues": [], "contracts_loaded": 0}


def load_structure_context_input(symbol: str, timeframe: str) -> dict[str, Any] | None:
    normalized = load_normalized_structure_contract_input(symbol, timeframe)
    if normalized is None:
        return None
    return dict(normalized.get("structure_context", {}))


def load_normalized_structure_contract_input(symbol: str, timeframe: str) -> dict[str, Any] | None:
    artifact_file = _resolve_artifact_file(symbol, timeframe)
    if artifact_file is not None:
        payload = _load_json(artifact_file)
        contract = normalize_structure_contract(payload)
        contract_payload = contract_to_dict(contract)
        _validate_contract_identity(contract_payload, symbol=symbol, timeframe=timeframe, path=artifact_file)
        return contract_payload

    if STRUCTURE_ARTIFACT_JSON.exists():
        payload = _load_payload()
        contract = normalize_structure_contract(payload, symbol=symbol, timeframe=timeframe)
        contract_payload = contract_to_dict(contract)
        _validate_contract_identity(contract_payload, symbol=symbol, timeframe=timeframe, path=STRUCTURE_ARTIFACT_JSON)
        return contract_payload

    return None


def discover_category_coverage() -> dict[str, bool]:
    summary = discover_normalized_contract_summary()
    return dict(summary.get("mapped_structure_categories", {}))


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
    normalized = load_normalized_structure_contract_input(symbol, timeframe)
    if normalized is None:
        raise FileNotFoundError("no structure artifact available for requested symbol/timeframe")

    canonical = normalized.get("canonical_structure", {})
    return {
        "bos": list(canonical.get("bos", [])),
        "orderblocks": list(canonical.get("orderblocks", [])),
        "fvg": list(canonical.get("fvg", [])),
        "liquidity_sweeps": list(canonical.get("liquidity_sweeps", [])),
    }


def load_raw_meta_input(symbol: str, timeframe: str) -> dict[str, Any]:
    del symbol, timeframe
    raise ValueError("structure_artifact_json does not provide raw meta input")
