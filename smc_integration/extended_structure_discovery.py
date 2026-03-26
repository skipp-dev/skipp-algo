from __future__ import annotations

import re
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

EVIDENCE_TYPE_ORDER = {
    "explicit_objects": 4,
    "computed_logic": 3,
    "aggregate_flags": 2,
    "text_only": 1,
}

TARGET_CATEGORIES = ["orderblocks", "fvg", "liquidity_sweeps"]

_SEARCH_GLOBS = [
    "smc_tv_bridge/**/*.{py,js,md}",
    "scripts/**/*.py",
    "reports/**/*.{json,md,csv}",
    "spec/**/*.json",
    "docs/**/*.md",
    "**/*.pine",
    "tests/**/*.py",
]

_IGNORE_FRAGMENTS = (
    "/.git/",
    "/.venv/",
    "/node_modules/",
    "/__pycache__/",
    "/.mypy_cache/",
    "/.pytest_cache/",
)

_EXPLICIT_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "orderblocks": [
        re.compile(r'"orderblocks"\s*:\s*\['),
        re.compile(r'"low"\s*:'),
        re.compile(r'"high"\s*:'),
        re.compile(r'"dir"\s*:'),
        re.compile(r'"valid"\s*:'),
    ],
    "fvg": [
        re.compile(r'"fvg"\s*:\s*\['),
        re.compile(r'"low"\s*:'),
        re.compile(r'"high"\s*:'),
        re.compile(r'"dir"\s*:'),
        re.compile(r'"valid"\s*:'),
    ],
    "liquidity_sweeps": [
        re.compile(r'"liquidity_sweeps"\s*:\s*\['),
        re.compile(r'"time"\s*:'),
        re.compile(r'"price"\s*:'),
        re.compile(r'"side"\s*:'),
    ],
}

_COMPUTED_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "orderblocks": [
        re.compile(r'_detect_orderblocks|OrderBlock|create_ob', re.IGNORECASE),
    ],
    "fvg": [
        re.compile(r'_detect_fvg|fair\s+value\s+gap|show_fvg', re.IGNORECASE),
    ],
    "liquidity_sweeps": [
        re.compile(r'_detect_sweeps|liquidity\s*sweep|sweep_lvl', re.IGNORECASE),
    ],
}

_AGGREGATE_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "orderblocks": [
        re.compile(r'ob_sweep_[a-z0-9_]+', re.IGNORECASE),
        re.compile(r'daily_ob_sweep_[a-z0-9_]+', re.IGNORECASE),
    ],
    "fvg": [
        re.compile(r'fvg_sweep_[a-z0-9_]+', re.IGNORECASE),
        re.compile(r'daily_fvg_sweep_[a-z0-9_]+', re.IGNORECASE),
    ],
    "liquidity_sweeps": [
        re.compile(r'sweep_reversal_rate|sweep_depth|_sweep_', re.IGNORECASE),
    ],
}

_TEXT_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "orderblocks": [re.compile(r'order\s*block', re.IGNORECASE)],
    "fvg": [re.compile(r'\bfvg\b|fair\s+value\s+gap', re.IGNORECASE)],
    "liquidity_sweeps": [re.compile(r'liquidity\s*sweep|\bsweep\b', re.IGNORECASE)],
}


def _iter_candidate_paths() -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()

    for pattern in _SEARCH_GLOBS:
        for path in REPO_ROOT.glob(pattern):
            if not path.is_file():
                continue
            rel = "/" + path.relative_to(REPO_ROOT).as_posix() + "/"
            if any(fragment in rel for fragment in _IGNORE_FRAGMENTS):
                continue
            if path in seen:
                continue
            seen.add(path)
            paths.append(path)

    paths.sort(key=lambda item: item.relative_to(REPO_ROOT).as_posix())
    return paths


def _read_text(path: Path, *, max_chars: int = 500_000) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1")
    return text[:max_chars]


def _matches_all(text: str, patterns: list[re.Pattern[str]]) -> bool:
    return all(pattern.search(text) for pattern in patterns)


def _matches_any(text: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _evidence_type_for(text: str, category: str) -> str | None:
    if _matches_all(text, _EXPLICIT_PATTERNS[category]):
        return "explicit_objects"
    if _matches_any(text, _COMPUTED_PATTERNS[category]):
        return "computed_logic"
    if _matches_any(text, _AGGREGATE_PATTERNS[category]):
        return "aggregate_flags"
    if _matches_any(text, _TEXT_PATTERNS[category]):
        return "text_only"
    return None


def _evidence_tokens(text: str, category: str, evidence_type: str) -> list[str]:
    patterns: list[re.Pattern[str]]
    if evidence_type == "explicit_objects":
        patterns = _EXPLICIT_PATTERNS[category]
    elif evidence_type == "computed_logic":
        patterns = _COMPUTED_PATTERNS[category]
    elif evidence_type == "aggregate_flags":
        patterns = _AGGREGATE_PATTERNS[category]
    else:
        patterns = _TEXT_PATTERNS[category]

    tokens: list[str] = []
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            tokens.append(match.group(0))
    return tokens


def _is_fixture_like(rel_path: str) -> bool:
    return rel_path.startswith("tests/") or rel_path.startswith("spec/examples/") or rel_path.startswith("docs/")


def _is_runtime_provider_artifact(rel_path: str) -> bool:
    if not rel_path.startswith("reports/"):
        return False
    return rel_path.endswith(".json") or rel_path.endswith(".csv")


def _candidate_rank(candidate: dict[str, Any]) -> tuple[int, int, int, str]:
    rel_path = str(candidate["path"])
    evidence_type = str(candidate["evidence_type"])
    fixture_penalty = 0 if not _is_fixture_like(rel_path) else -1
    runtime_bonus = 1 if _is_runtime_provider_artifact(rel_path) else 0
    return (
        EVIDENCE_TYPE_ORDER[evidence_type],
        runtime_bonus,
        fixture_penalty,
        rel_path,
    )


def discover_extended_structure_candidates() -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    for path in _iter_candidate_paths():
        rel_path = path.relative_to(REPO_ROOT).as_posix()
        text = _read_text(path)

        for category in TARGET_CATEGORIES:
            evidence_type = _evidence_type_for(text, category)
            if evidence_type is None:
                continue

            tokens = _evidence_tokens(text, category, evidence_type)

            candidates.append(
                {
                    "category": category,
                    "path": rel_path,
                    "evidence_type": evidence_type,
                    "evidence_tokens": tokens,
                    "is_fixture_like": _is_fixture_like(rel_path),
                    "is_runtime_provider_artifact": _is_runtime_provider_artifact(rel_path),
                }
            )

    candidates.sort(
        key=lambda item: (
            item["category"],
            -EVIDENCE_TYPE_ORDER[str(item["evidence_type"])],
            str(item["path"]),
        )
    )
    return candidates


def _best_candidate_for_category(candidates: list[dict[str, Any]], category: str) -> dict[str, Any] | None:
    scoped = [item for item in candidates if item["category"] == category]
    if not scoped:
        return None
    scoped.sort(key=_candidate_rank, reverse=True)
    return dict(scoped[0])


def _integrability_for(category: str, best_candidate: dict[str, Any] | None) -> dict[str, Any]:
    if best_candidate is None:
        return {
            "integrable_now": False,
            "reason": f"No evidence found for category={category} in the scanned extended repository paths.",
        }

    path = str(best_candidate["path"])
    evidence_type = str(best_candidate["evidence_type"])

    if evidence_type != "explicit_objects":
        return {
            "integrable_now": False,
            "reason": "Best candidate is not explicit object payload data.",
        }

    if _is_fixture_like(path):
        return {
            "integrable_now": False,
            "reason": "Best explicit candidate is fixture/spec/test material, not a live provider artifact.",
        }

    if not _is_runtime_provider_artifact(path):
        return {
            "integrable_now": False,
            "reason": "Best explicit candidate is code/bridge output logic, not a registered watchlist/artifact source.",
        }

    return {
        "integrable_now": True,
        "reason": "Best candidate is an explicit runtime artifact under reports/ and can be mapped without fabrication.",
    }


def discover_extended_structure_by_category() -> dict[str, dict[str, Any]]:
    candidates = discover_extended_structure_candidates()
    report: dict[str, dict[str, Any]] = {}

    for category in TARGET_CATEGORIES:
        best = _best_candidate_for_category(candidates, category)
        scoped = [item for item in candidates if item["category"] == category]
        scoped.sort(key=_candidate_rank, reverse=True)
        integrability = _integrability_for(category, best)

        report[category] = {
            "candidate_count": len(scoped),
            "best_candidate": best,
            "top_candidates": scoped[:5],
            "integrability": integrability,
        }

    return report


def build_extended_structure_discovery_report() -> dict[str, Any]:
    by_category = discover_extended_structure_by_category()
    candidates = discover_extended_structure_candidates()

    strongest_evidence_type: dict[str, str] = {}
    for category in TARGET_CATEGORIES:
        best = by_category[category]["best_candidate"]
        strongest_evidence_type[category] = str(best["evidence_type"]) if isinstance(best, dict) else "text_only"

    return {
        "scanned_paths": [path.relative_to(REPO_ROOT).as_posix() for path in _iter_candidate_paths()],
        "categories": by_category,
        "strongest_evidence_type": strongest_evidence_type,
        "candidate_count": len(candidates),
    }
