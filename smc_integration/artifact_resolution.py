from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.databento_production_workbook import (
    DEFAULT_PRODUCTION_EXPORT_DIR,
    canonical_production_workbook_path,
    resolve_production_workbook_path as resolve_lineage_workbook_path,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STRUCTURE_ARTIFACTS_DIR = Path("reports") / "smc_structure_artifacts"
DEFAULT_SINGLE_STRUCTURE_ARTIFACT_PATH = Path("reports") / "smc_structure_artifact.json"
DEFAULT_SYMBOLS_SOURCE_PATH = Path("reports") / "databento_watchlist_top5_pre1530.csv"


def _to_existing_path(raw: str | Path | None) -> Path | None:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.exists() else None


def _repo_absolute(path: Path) -> Path:
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def _mode(explicit_hit: bool, canonical_hit: bool) -> str:
    if explicit_hit:
        return "explicit"
    if canonical_hit:
        return "canonical"
    return "missing"


def resolve_production_workbook_path(explicit_path: str | None = None) -> Path | None:
    explicit = _to_existing_path(explicit_path)
    if explicit is not None:
        return explicit

    canonical = _repo_absolute(canonical_production_workbook_path(export_dir=_repo_absolute(DEFAULT_PRODUCTION_EXPORT_DIR)))
    if canonical.exists():
        return canonical

    try:
        return resolve_lineage_workbook_path(
            workbook=None,
            export_dir=_repo_absolute(DEFAULT_PRODUCTION_EXPORT_DIR),
            repo_root=REPO_ROOT,
        )
    except FileNotFoundError:
        return None


def resolve_export_bundle_root(explicit_path: str | None = None) -> Path | None:
    explicit = _to_existing_path(explicit_path)
    if explicit is not None and explicit.is_dir():
        return explicit

    canonical = _repo_absolute(DEFAULT_PRODUCTION_EXPORT_DIR)
    if canonical.exists() and canonical.is_dir():
        return canonical

    return None


def resolve_structure_artifact_inputs(
    *,
    explicit_workbook_path: str | None = None,
    explicit_export_bundle_root: str | None = None,
    explicit_structure_artifacts_dir: str | None = None,
    explicit_single_structure_artifact_path: str | None = None,
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    explicit_workbook = _to_existing_path(explicit_workbook_path)
    workbook = resolve_production_workbook_path(explicit_workbook_path)
    workbook_mode = _mode(explicit_workbook is not None, workbook is not None and explicit_workbook is None)
    if workbook is None:
        errors.append({
            "code": "WORKBOOK_NOT_FOUND",
            "message": "No production workbook could be resolved.",
        })

    explicit_bundle = _to_existing_path(explicit_export_bundle_root)
    bundle_root = resolve_export_bundle_root(explicit_export_bundle_root)
    bundle_mode = _mode(explicit_bundle is not None, bundle_root is not None and explicit_bundle is None)
    if bundle_root is None:
        warnings.append({
            "code": "EXPORT_BUNDLE_ROOT_NOT_FOUND",
            "message": "No export bundle root could be resolved.",
        })

    artifacts_dir: Path
    if explicit_structure_artifacts_dir is not None and str(explicit_structure_artifacts_dir).strip():
        artifacts_dir = Path(str(explicit_structure_artifacts_dir)).expanduser()
    else:
        artifacts_dir = _repo_absolute(DEFAULT_STRUCTURE_ARTIFACTS_DIR)

    single_artifact = _to_existing_path(explicit_single_structure_artifact_path)
    if single_artifact is None:
        candidate = _repo_absolute(DEFAULT_SINGLE_STRUCTURE_ARTIFACT_PATH)
        single_artifact = candidate if candidate.exists() else None

    resolution_mode = "explicit" if (explicit_workbook is not None or explicit_bundle is not None) else "canonical"
    if workbook is None and bundle_root is None:
        resolution_mode = "missing"

    return {
        "workbook_path": workbook,
        "export_bundle_root": bundle_root,
        "structure_artifacts_dir": artifacts_dir,
        "single_structure_artifact_path": single_artifact,
        "resolution_mode": resolution_mode,
        "errors": errors,
        "warnings": warnings,
        "resolution_detail": {
            "workbook": workbook_mode,
            "export_bundle_root": bundle_mode,
        },
    }


def resolve_watchlist_export_inputs(
    *,
    explicit_symbols_source_path: str | None = None,
    explicit_workbook_path: str | None = None,
    explicit_export_bundle_root: str | None = None,
    explicit_structure_artifacts_dir: str | None = None,
) -> dict[str, Any]:
    resolved = resolve_structure_artifact_inputs(
        explicit_workbook_path=explicit_workbook_path,
        explicit_export_bundle_root=explicit_export_bundle_root,
        explicit_structure_artifacts_dir=explicit_structure_artifacts_dir,
    )

    errors = list(resolved["errors"])
    warnings = list(resolved["warnings"])

    explicit_symbols = _to_existing_path(explicit_symbols_source_path)
    symbols_source_path = explicit_symbols
    symbol_source_mode = "explicit" if explicit_symbols is not None else "missing"
    if symbols_source_path is None:
        candidate = _repo_absolute(DEFAULT_SYMBOLS_SOURCE_PATH)
        if candidate.exists():
            symbols_source_path = candidate
            symbol_source_mode = "canonical"

    if symbols_source_path is None:
        warnings.append(
            {
                "code": "SYMBOLS_SOURCE_NOT_FOUND",
                "message": "No symbols source file was resolved; caller must provide symbols explicitly.",
            }
        )

    resolution_mode = resolved["resolution_mode"]
    if symbol_source_mode == "explicit" and resolution_mode != "missing":
        resolution_mode = "explicit"

    return {
        "symbols_source_path": symbols_source_path,
        "workbook_path": resolved["workbook_path"],
        "export_bundle_root": resolved["export_bundle_root"],
        "structure_artifacts_dir": resolved["structure_artifacts_dir"],
        "resolution_mode": resolution_mode,
        "errors": errors,
        "warnings": warnings,
        "resolution_detail": {
            **resolved.get("resolution_detail", {}),
            "symbols_source": symbol_source_mode,
        },
    }
