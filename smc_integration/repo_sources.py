from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Callable

from .meta_merge import merge_raw_meta_domains
from .sources import benzinga_watchlist_json, databento_watchlist_csv, fmp_watchlist_json, structure_artifact_json, tradingview_watchlist_json
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
    "structure_artifact_json": _SourceProvider(
        descriptor=structure_artifact_json.describe_source(),
        load_structure=structure_artifact_json.load_raw_structure_input,
        load_meta=structure_artifact_json.load_raw_meta_input,
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


_DOMAIN_SOURCE_ORDER: dict[str, list[str]] = {
    "structure": [
        "structure_artifact_json",
        "databento_watchlist_csv",
        "fmp_watchlist_json",
        "tradingview_watchlist_json",
        "benzinga_watchlist_json",
    ],
    "volume": [
        "databento_watchlist_csv",
        "fmp_watchlist_json",
        "tradingview_watchlist_json",
        "benzinga_watchlist_json",
    ],
    "technical": [
        "fmp_watchlist_json",
        "tradingview_watchlist_json",
        "databento_watchlist_csv",
        "benzinga_watchlist_json",
    ],
    "news": [
        "benzinga_watchlist_json",
        "fmp_watchlist_json",
        "tradingview_watchlist_json",
        "databento_watchlist_csv",
    ],
}


def _can_supply_domain(provider: _SourceProvider, domain: str) -> bool:
    caps = provider.descriptor.capabilities
    if domain == "structure":
        return bool(caps.has_structure)
    if domain == "volume":
        return bool(caps.has_meta)
    if domain == "technical":
        return provider.descriptor.name in {"fmp_watchlist_json", "tradingview_watchlist_json"}
    if domain == "news":
        return provider.descriptor.name == "benzinga_watchlist_json"
    return False


def _select_best_source_for_domain(domain: str) -> SourceDescriptor:
    if domain not in _DOMAIN_SOURCE_ORDER:
        known = ", ".join(sorted(_DOMAIN_SOURCE_ORDER))
        raise ValueError(f"unknown domain {domain}; expected one of: {known}")

    ordered_names = _DOMAIN_SOURCE_ORDER[domain]
    for name in ordered_names:
        provider = _SOURCE_PROVIDERS.get(name)
        if provider is None:
            continue
        if _can_supply_domain(provider, domain):
            return provider.descriptor

    raise ValueError(f"no integration source can supply domain={domain}")


def select_best_structure_source() -> SourceDescriptor:
    return _select_best_source_for_domain("structure")


def select_best_volume_source() -> SourceDescriptor:
    return _select_best_source_for_domain("volume")


def select_best_technical_source() -> SourceDescriptor:
    return _select_best_source_for_domain("technical")


def select_best_news_source() -> SourceDescriptor:
    return _select_best_source_for_domain("news")


def select_best_source() -> SourceDescriptor:
    # Backward-compatible alias for existing callers expecting one "best" source.
    return select_best_structure_source()


def _resolve_provider(source: str, *, domain: str) -> _SourceProvider:
    normalized = source.strip().lower()
    if normalized == "auto":
        if domain == "structure":
            best = select_best_structure_source()
        elif domain == "meta":
            best = select_best_volume_source()
        else:
            raise ValueError(f"unknown resolve domain: {domain}")
        return _SOURCE_PROVIDERS[best.name]
    if normalized not in _SOURCE_PROVIDERS:
        known = ", ".join(sorted(_SOURCE_PROVIDERS))
        raise ValueError(f"unknown source {source}; expected one of: {known}, auto")
    return _SOURCE_PROVIDERS[normalized]

def discover_repo_source_paths() -> dict[str, Any]:
    best = select_best_structure_source()
    best_meta = select_best_volume_source()
    all_sources = discover_repo_sources()
    composite = discover_composite_source_plan()

    return {
        "selected_source": best.to_dict(),
        "sources": [item.to_dict() for item in all_sources],
        "source_names": [item.name for item in all_sources],
        "integration_entry": best.path_hint,
        "meta_source": best_meta.name,
        "structure_source": f"{best.name}:{best.capabilities.structure_mode}",
        "composite_source_plan": composite,
        "structure_capabilities": {
            "mode": best.capabilities.structure_mode,
            "has_structure": best.capabilities.has_structure,
        },
    }


def _resolve_auto_structure_source_for_symbol_timeframe(symbol: str, timeframe: str) -> str:
    wanted_symbol = symbol.strip().upper()
    wanted_timeframe = str(timeframe).strip()
    wants_specific_artifact = bool(wanted_symbol and wanted_timeframe)

    for name in _DOMAIN_SOURCE_ORDER["structure"]:
        provider = _SOURCE_PROVIDERS.get(name)
        if provider is None:
            continue
        if name == "structure_artifact_json" and wants_specific_artifact:
            if not structure_artifact_json.has_artifact_for_symbol_timeframe(wanted_symbol, wanted_timeframe):
                continue
        if _can_supply_domain(provider, "structure"):
            return provider.descriptor.name
    raise ValueError("no integration source can supply domain=structure")


def discover_structure_source_status(*, source: str = "auto", symbol: str = "", timeframe: str = "") -> dict[str, Any]:
    plan = discover_composite_source_plan(source=source, symbol=symbol, timeframe=timeframe)
    structure_name = plan["structure"]
    structure_provider = _SOURCE_PROVIDERS[structure_name]
    structure_descriptor = structure_provider.descriptor

    # Import lazily to avoid a module import cycle.
    from .provider_matrix import discover_provider_matrix

    matrix_by_name = {entry.name: entry for entry in discover_provider_matrix()}
    selected_entry = matrix_by_name.get(structure_name)

    any_explicit = any(entry.current.currently_maps_structure for entry in matrix_by_name.values())
    explicit_names = sorted(
        entry.name
        for entry in matrix_by_name.values()
        if entry.current.currently_maps_structure
    )

    selected_notes = list(structure_descriptor.notes)
    if selected_entry is not None:
        selected_notes.extend(selected_entry.known_gaps)

    selected_health_issues: list[dict[str, Any]] = []
    if structure_name == "structure_artifact_json":
        contract_summary = structure_artifact_json.discover_normalized_contract_summary()
        health = contract_summary.get("health", {}) if isinstance(contract_summary, dict) else {}
        raw_issues = health.get("issues", []) if isinstance(health, dict) else []
        if isinstance(raw_issues, list):
            selected_health_issues = [item for item in raw_issues if isinstance(item, dict)]
        if selected_health_issues:
            selected_notes.append(
                f"Structure artifact health issues detected: {len(selected_health_issues)}"
            )

    category_coverage = {
        "bos": False,
        "choch": False,
        "orderblocks": False,
        "fvg": False,
        "liquidity_sweeps": False,
    }
    if selected_entry is not None:
        category_coverage.update(selected_entry.current.mapped_structure_categories)

    missing_categories = [
        category
        for category, available in category_coverage.items()
        if not bool(available)
    ]

    return {
        "selected_structure_source": structure_name,
        "selected_structure_mode": structure_descriptor.capabilities.structure_mode,
        "selected_has_structure_capability": structure_descriptor.capabilities.has_structure,
        "selected_category_coverage": category_coverage,
        "selected_missing_categories": missing_categories,
        "selected_health_issue_count": len(selected_health_issues),
        "selected_health_issues": selected_health_issues,
        "any_registered_explicit_structure_provider": any_explicit,
        "explicit_structure_provider_names": explicit_names,
        "notes": selected_notes,
    }


def discover_composite_source_plan(*, source: str = "auto", symbol: str = "", timeframe: str = "") -> dict[str, str]:
    normalized = source.strip().lower()
    if normalized == "auto":
        structure = _resolve_auto_structure_source_for_symbol_timeframe(symbol, timeframe)
        volume = select_best_volume_source().name
        technical = select_best_technical_source().name
        news = select_best_news_source().name
        return {
            "structure": structure,
            "volume": volume,
            "technical": technical,
            "news": news,
        }

    if normalized not in _SOURCE_PROVIDERS:
        known = ", ".join(sorted(_SOURCE_PROVIDERS))
        raise ValueError(f"unknown source {source}; expected one of: {known}, auto")

    # Explicit source keeps single-provider behavior for all domains.
    return {
        "structure": normalized,
        "volume": normalized,
        "technical": normalized,
        "news": normalized,
    }


def load_raw_structure_input(
    symbol: str,
    timeframe: str,
    *,
    source: str = "auto",
) -> dict[str, Any]:
    normalized = source.strip().lower()
    if normalized == "auto":
        last_error: Exception | None = None
        for name in _DOMAIN_SOURCE_ORDER["structure"]:
            provider = _SOURCE_PROVIDERS.get(name)
            if provider is None or not _can_supply_domain(provider, "structure"):
                continue

            artifact_expected = False
            if name == "structure_artifact_json":
                artifact_expected = structure_artifact_json.has_artifact_for_symbol_timeframe(symbol, timeframe)

            try:
                return provider.load_structure(symbol, timeframe)
            except FileNotFoundError as exc:
                last_error = exc
                continue
            except ValueError as exc:
                if name == "structure_artifact_json" and artifact_expected:
                    raise ValueError(
                        "structure artifact exists for symbol/timeframe but failed validation"
                    ) from exc
                last_error = exc
                continue
        if last_error is not None:
            raise last_error
        raise ValueError("no structure provider available in auto mode")

    provider = _resolve_provider(source, domain="structure")
    return provider.load_structure(symbol, timeframe)


def load_raw_meta_input(
    symbol: str,
    timeframe: str,
    *,
    source: str = "auto",
) -> dict[str, Any]:
    provider = _resolve_provider(source, domain="meta")
    return provider.load_meta(symbol, timeframe)


def load_raw_meta_input_composite(
    symbol: str,
    timeframe: str,
    *,
    source: str = "auto",
) -> dict[str, Any]:
    normalized = source.strip().lower()
    plan = discover_composite_source_plan(source=source, symbol=symbol, timeframe=timeframe)

    structure_provider = _SOURCE_PROVIDERS[plan["structure"]]
    volume_provider = _SOURCE_PROVIDERS[plan["volume"]]
    technical_provider = _SOURCE_PROVIDERS[plan["technical"]]
    news_provider = _SOURCE_PROVIDERS[plan["news"]]

    volume_meta = volume_provider.load_meta(symbol, timeframe)

    technical_meta: dict[str, Any] | None
    try:
        technical_meta = technical_provider.load_meta(symbol, timeframe)
    except (FileNotFoundError, ValueError):
        if normalized == "auto":
            technical_meta = None
        else:
            raise
    if technical_meta is not None and "technical" not in technical_meta:
        technical_meta = None

    news_meta: dict[str, Any] | None
    try:
        news_meta = news_provider.load_meta(symbol, timeframe)
    except (FileNotFoundError, ValueError):
        if normalized == "auto":
            news_meta = None
        else:
            raise
    if news_meta is not None and "news" not in news_meta:
        news_meta = None

    merged = merge_raw_meta_domains(
        volume_meta=volume_meta,
        technical_meta=technical_meta,
        news_meta=news_meta,
        domain_sources={
            "structure": structure_provider.descriptor.name,
            "volume": volume_provider.descriptor.name,
            "technical": technical_provider.descriptor.name,
            "news": news_provider.descriptor.name,
        },
    )

    merged_asof_ts = merged.get("asof_ts")
    if not isinstance(merged_asof_ts, (int, float)):
        raise ValueError("merged raw_meta has invalid asof_ts type")
    merged_asof_ts_f = float(merged_asof_ts)
    if not math.isfinite(merged_asof_ts_f) or merged_asof_ts_f <= 0:
        raise ValueError("merged raw_meta has invalid asof_ts value")

    stale_threshold_secs = 90 * 24 * 60 * 60
    if merged_asof_ts_f < (time.time() - stale_threshold_secs):
        provenance = merged.get("provenance", [])
        if not isinstance(provenance, list):
            provenance = []
        stale_marker = "smc_integration:warning:stale_meta_asof_ts"
        if stale_marker not in provenance:
            provenance.append(stale_marker)
        merged["provenance"] = provenance

    return merged
