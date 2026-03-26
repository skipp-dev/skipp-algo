from __future__ import annotations

import re
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[1]

_TOKEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("bos", re.compile(r'"bos"|\bbos\b', re.IGNORECASE)),
    ("choch", re.compile(r'"choch"|\bchoch\b', re.IGNORECASE)),
    ("orderblocks", re.compile(r'"orderblocks"|\borderblock\b|\borderblocks\b', re.IGNORECASE)),
    ("fvg", re.compile(r'"fvg"|\bfvg\b|fair\s+value\s+gap', re.IGNORECASE)),
    ("liquidity_sweeps", re.compile(r'"liquidity_sweeps"|\bliquidity[_\s-]*sweeps?\b', re.IGNORECASE)),
    ("sweep", re.compile(r'\bsweep\b|\bsweeps\b', re.IGNORECASE)),
    ("reclaim", re.compile(r'\breclaim\b', re.IGNORECASE)),
    ("structure_", re.compile(r'\bstructure_[a-z0-9_]+\b', re.IGNORECASE)),
]

_EXPLICIT_STRUCTURE_KEYS = {"bos", "orderblocks", "fvg", "liquidity_sweeps"}
_CATEGORY_ORDER = ["bos", "choch", "orderblocks", "fvg", "liquidity_sweeps"]


def _kind_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix == ".csv":
        return "csv"
    if suffix == ".pine":
        return "pine"
    if suffix in {".py", ".ts"}:
        return "script"
    if "generated" in path.parts:
        return "generated"
    return "other"


def _read_text_safely(path: Path, max_chars: int = 300_000) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1")
    return text[:max_chars]


def _collect_evidence(path: Path) -> list[str]:
    text = _read_text_safely(path)
    found: list[str] = []
    for token, pattern in _TOKEN_PATTERNS:
        if pattern.search(text):
            found.append(token)
    return sorted(set(found))


def _confidence_for(path: Path, evidence: list[str]) -> str:
    evidence_set = set(evidence)
    if _EXPLICIT_STRUCTURE_KEYS.issubset(evidence_set):
        return "high"
    if evidence_set.intersection(_EXPLICIT_STRUCTURE_KEYS):
        return "medium"
    if len(evidence_set) >= 2:
        return "medium"
    return "low"


def _notes_for(path: Path, evidence: list[str]) -> list[str]:
    notes: list[str] = []
    rel = path.relative_to(_REPO_ROOT).as_posix()

    if rel.startswith("spec/examples/"):
        notes.append("Schema example snapshot; useful as mapping fixture but not a production upstream feed.")
    elif rel.startswith("reports/"):
        notes.append("Report artifact exists in repo checkout and can be audited reproducibly.")
    elif rel.startswith("scripts/"):
        notes.append("Code path candidate; requires concrete exported artifact for provider integration.")
    elif rel.endswith("SMC_Core_Engine.pine"):
        notes.append("Contains structure logic in Pine runtime, but not a repository JSON/CSV provider artifact.")

    if "structure_" in evidence and not set(evidence).intersection(_EXPLICIT_STRUCTURE_KEYS):
        notes.append("Contains structure-scored/meta fields, not explicit BOS/OB/FVG/sweep event arrays.")
    if "reclaim" in evidence and not set(evidence).intersection(_EXPLICIT_STRUCTURE_KEYS):
        notes.append("Reclaim terminology appears, but explicit structure event payloads are not present.")

    return notes


def _candidate_paths() -> list[Path]:
    explicit: list[Path] = [
        _REPO_ROOT / "SMC_Core_Engine.pine",
        _REPO_ROOT / "scripts" / "export_smc_structure_artifacts_from_workbook.py",
        _REPO_ROOT / "scripts" / "export_smc_structure_artifact.py",
        _REPO_ROOT / "scripts" / "market_structure_features.py",
        _REPO_ROOT / "scripts" / "smc_microstructure_base_runtime.py",
        _REPO_ROOT / "scripts" / "generate_smc_micro_profiles.py",
        _REPO_ROOT / "scripts" / "load_databento_export_bundle.py",
        _REPO_ROOT / "scripts" / "generate_databento_watchlist.py",
        _REPO_ROOT / "scripts" / "generate_bullish_quality_scanner.py",
        _REPO_ROOT / "reports" / "smc_structure_artifact.json",
        _REPO_ROOT / "reports" / "databento_volatility_production_20260307_114724_microstructure_mapping_2026-03-06.json",
    ]

    explicit.extend(sorted((_REPO_ROOT / "spec" / "examples").glob("smc_snapshot_*.json")))

    generated_dir = _REPO_ROOT / "pine" / "generated"
    if generated_dir.exists():
        explicit.extend(sorted(generated_dir.rglob("*.json")))
        explicit.extend(sorted(generated_dir.rglob("*.pine")))

    unique: list[Path] = []
    seen: set[Path] = set()
    for path in explicit:
        if path in seen:
            continue
        seen.add(path)
        if path.exists() and path.is_file():
            unique.append(path)
    return unique


def discover_structure_source_candidates() -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for path in _candidate_paths():
        evidence = _collect_evidence(path)
        if not evidence:
            continue
        rel = path.relative_to(_REPO_ROOT).as_posix()
        candidates.append(
            {
                "name": path.stem,
                "path": rel,
                "kind": _kind_for_path(path),
                "evidence": evidence,
                "confidence": _confidence_for(path, evidence),
                "notes": _notes_for(path, evidence),
            }
        )

    candidates.sort(key=lambda item: item["path"])
    return candidates


def discover_structure_category_coverage() -> dict[str, dict[str, Any]]:
    from .provider_matrix import discover_provider_matrix

    matrix = discover_provider_matrix()
    by_name = {entry.name: entry for entry in matrix}
    artifact_entry = by_name.get("structure_artifact_json")

    mapped_categories = {
        category: False
        for category in _CATEGORY_ORDER
    }
    mapped_fields: list[str] = []
    producer_name: str | None = None

    if artifact_entry is not None:
        mapped_categories.update(artifact_entry.current.mapped_structure_categories)
        mapped_fields = list(artifact_entry.current.mapped_structure_fields)
        if artifact_entry.current.currently_maps_structure:
            producer_name = artifact_entry.name

    evidence_by_category: dict[str, list[str]] = {
        "bos": [
            "scripts.explicit_structure_from_bars.build_bos_events_from_bars",
            "structure_artifact_json:bos.kind",
            "smc_core.ids.bos_id",
        ],
        "choch": [
            "scripts.explicit_structure_from_bars.build_bos_events_from_bars",
            "structure_artifact_json:bos.kind=CHOCH",
            "smc_core.ids.bos_id",
        ],
        "orderblocks": [
            "scripts.explicit_structure_from_bars.build_orderblocks_from_bars",
            "smc_core.ids.ob_id",
        ],
        "fvg": [
            "scripts.explicit_structure_from_bars.build_fvg_from_bars",
            "smc_core.ids.fvg_id",
        ],
        "liquidity_sweeps": [
            "scripts.explicit_structure_from_bars.build_liquidity_sweeps_from_bars",
            "smc_core.ids.sweep_id",
        ],
    }

    notes_by_category: dict[str, list[str]] = {
        "bos": [],
        "choch": ["CHOCH is exported via the explicit bos event family (`kind=CHOCH`)."],
        "orderblocks": [],
        "fvg": [],
        "liquidity_sweeps": [],
    }

    if producer_name is None:
        notes_by_category["bos"].append("No live explicit structure artifact provider is currently available.")
        notes_by_category["choch"].append("No live explicit structure artifact provider is currently available.")

    if not mapped_categories.get("choch") and mapped_categories.get("bos"):
        mapped_categories["choch"] = True

    report: dict[str, dict[str, Any]] = {}
    for category in _CATEGORY_ORDER:
        available = bool(mapped_categories.get(category, False))
        source_evidence = list(evidence_by_category[category]) if available else []
        notes = list(notes_by_category[category])

        if available and mapped_fields:
            notes.append(f"Mapped fields include: {', '.join(mapped_fields)}")

        if not available and category in {"orderblocks", "fvg", "liquidity_sweeps"}:
            notes.append("Category is currently not populated in discovered structure artifacts.")

        report[category] = {
            "available": available,
            "producer": producer_name if available else None,
            "source_evidence": source_evidence,
            "notes": notes,
        }

    return report


def build_structure_gap_report() -> dict[str, Any]:
    from . import repo_sources as _repo_sources
    from .extended_structure_discovery import build_extended_structure_discovery_report
    from .repo_sources import discover_repo_sources

    status_fn = getattr(_repo_sources, "discover_structure_source_status", None)
    if callable(status_fn):
        status = status_fn()
    else:
        status = {
            "selected_structure_source": None,
            "selected_structure_mode": "none",
            "selected_has_structure_capability": False,
            "any_registered_explicit_structure_provider": False,
            "explicit_structure_provider_names": [],
            "notes": ["discover_structure_source_status is unavailable in repo_sources"],
        }
    candidates = discover_structure_source_candidates()
    category_coverage = discover_structure_category_coverage()
    registered_structure_sources = [
        {
            "name": source.name,
            "path_hint": source.path_hint,
            "structure_mode": source.capabilities.structure_mode,
            "has_structure": source.capabilities.has_structure,
            "notes": list(source.notes),
        }
        for source in discover_repo_sources()
        if source.capabilities.has_structure
    ]

    best_candidate = candidates[0] if candidates else None
    has_real_structure_provider = bool(status.get("any_registered_explicit_structure_provider", False))
    selected_source_name = str(status.get("selected_structure_source") or "")

    from .provider_matrix import discover_provider_matrix

    matrix = {entry.name: entry for entry in discover_provider_matrix()}
    selected_entry = matrix.get(selected_source_name)
    selected_mapped_fields = set(selected_entry.current.mapped_structure_fields) if selected_entry is not None else set()

    gaps: list[str] = []
    if not has_real_structure_provider:
        gaps.extend(
            [
                "No registered source currently maps explicit BOS events into raw_structure.bos.",
                "No registered source currently maps explicit orderblocks into raw_structure.orderblocks.",
                "No registered source currently maps explicit FVG events into raw_structure.fvg.",
                "No registered source currently maps explicit liquidity sweeps into raw_structure.liquidity_sweeps.",
            ]
        )
    else:
        if not any(field.startswith("bos.") for field in selected_mapped_fields):
            gaps.append("Selected structure provider does not currently map explicit BOS/CHOCH event fields.")
        if not any(field.startswith("orderblocks.") for field in selected_mapped_fields):
            gaps.append("Selected structure provider does not currently map explicit orderblocks.")
        if not any(field.startswith("fvg.") for field in selected_mapped_fields):
            gaps.append("Selected structure provider does not currently map explicit FVG events.")
        if not any(field.startswith("liquidity_sweeps.") for field in selected_mapped_fields):
            gaps.append("Selected structure provider does not currently map explicit liquidity sweeps.")

    if best_candidate is not None and best_candidate["path"].startswith("spec/examples/"):
        gaps.append("Best explicit-structure files are schema examples, not live/watchlist provider artifacts.")

    missing_categories = [
        category
        for category in _CATEGORY_ORDER
        if not bool(category_coverage[category]["available"])
    ]
    available_categories = [
        category
        for category in _CATEGORY_ORDER
        if bool(category_coverage[category]["available"])
    ]

    provider_by_category = {
        category: category_coverage[category]["producer"]
        for category in _CATEGORY_ORDER
        if category_coverage[category]["producer"] is not None
    }

    report = {
        "has_real_structure_provider": has_real_structure_provider,
        "best_candidate": best_candidate,
        "registered_structure_sources": registered_structure_sources,
        "candidate_sources": candidates,
        "summary": {
            "candidate_count": len(candidates),
            "registered_structure_source_count": len(registered_structure_sources),
            "current_structure_mode": status.get("selected_structure_mode", "none"),
            "available_categories": available_categories,
            "missing_categories": missing_categories,
        },
        "category_coverage": category_coverage,
        "available_categories": available_categories,
        "missing_categories": missing_categories,
        "provider_by_category": provider_by_category,
        "gaps": gaps,
        "structure_status": status,
        "extended_discovery": build_extended_structure_discovery_report(),
    }
    return report


def structure_gap_report_to_dict(report: dict[str, Any]) -> dict[str, Any]:
    return dict(report)
