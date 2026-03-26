from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .sources import benzinga_watchlist_json, databento_watchlist_csv, fmp_watchlist_json, tradingview_watchlist_json
from .sources.base import SourceDescriptor


@dataclass(frozen=True)
class _SourceProvider:
    descriptor: SourceDescriptor
    load_structure: Callable[[str, str], dict[str, Any]]
    load_meta: Callable[[str, str], dict[str, Any]]


_SOURCE_PROVIDERS: dict[str, _SourceProvider] = {
    "benzinga_watchlist_json": _SourceProvider(
        descriptor=benzinga_watchlist_json.describe_source(),
        load_structure=benzinga_watchlist_json.load_raw_structure_input,
        load_meta=benzinga_watchlist_json.load_raw_meta_input,
    ),
    "databento_watchlist_csv": _SourceProvider(
        descriptor=databento_watchlist_csv.describe_source(),
        load_structure=databento_watchlist_csv.load_raw_structure_input,
        load_meta=databento_watchlist_csv.load_raw_meta_input,
    ),
    "fmp_watchlist_json": _SourceProvider(
        descriptor=fmp_watchlist_json.describe_source(),
        load_structure=fmp_watchlist_json.load_raw_structure_input,
        load_meta=fmp_watchlist_json.load_raw_meta_input,
    ),
    "tradingview_watchlist_json": _SourceProvider(
        descriptor=tradingview_watchlist_json.describe_source(),
        load_structure=tradingview_watchlist_json.load_raw_structure_input,
        load_meta=tradingview_watchlist_json.load_raw_meta_input,
    ),
}


def discover_repo_sources() -> list[SourceDescriptor]:
    return [
        _SOURCE_PROVIDERS[name].descriptor
        for name in sorted(_SOURCE_PROVIDERS)
    ]


def _source_priority_key(descriptor: SourceDescriptor) -> tuple[int, int, int, str]:
    structure_mode_rank = {
        "full": 3,
        "partial": 2,
        "none": 1,
    }
    meta_mode_rank = {
        "full": 3,
        "partial": 2,
        "none": 1,
    }
    return (
        1 if descriptor.capabilities.has_structure else 0,
        structure_mode_rank[descriptor.capabilities.structure_mode],
        meta_mode_rank[descriptor.capabilities.meta_mode],
        descriptor.name,
    )


def select_best_source() -> SourceDescriptor:
    sources = discover_repo_sources()
    if not sources:
        raise ValueError("no integration sources registered")
    return sorted(sources, key=_source_priority_key, reverse=True)[0]


def _resolve_provider(source: str) -> _SourceProvider:
    normalized = source.strip().lower()
    if normalized == "auto":
        best = select_best_source()
        return _SOURCE_PROVIDERS[best.name]
    if normalized not in _SOURCE_PROVIDERS:
        known = ", ".join(sorted(_SOURCE_PROVIDERS))
        raise ValueError(f"unknown source {source}; expected one of: {known}, auto")
    return _SOURCE_PROVIDERS[normalized]

def discover_repo_source_paths() -> dict[str, Any]:
    best = select_best_source()
    all_sources = discover_repo_sources()

    return {
        "selected_source": best.to_dict(),
        "sources": [item.to_dict() for item in all_sources],
        "source_names": [item.name for item in all_sources],
        "integration_entry": best.path_hint,
        "meta_source": best.name,
        "structure_source": f"{best.name}:{best.capabilities.structure_mode}",
        "structure_capabilities": {
            "mode": best.capabilities.structure_mode,
            "has_structure": best.capabilities.has_structure,
        },
    }


def load_raw_structure_input(
    symbol: str,
    timeframe: str,
    *,
    source: str = "auto",
) -> dict[str, Any]:
    provider = _resolve_provider(source)
    return provider.load_structure(symbol, timeframe)


def load_raw_meta_input(
    symbol: str,
    timeframe: str,
    *,
    source: str = "auto",
) -> dict[str, Any]:
    provider = _resolve_provider(source)
    return provider.load_meta(symbol, timeframe)
