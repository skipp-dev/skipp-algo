from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .meta_merge import merge_raw_meta_domains
from .sources import (
    benzinga_watchlist_json,
    databento_watchlist_csv,
    fmp_watchlist_json,
    largecap_watchlist_json,
    live_news_snapshot_json,
    structure_artifact_json,
    tradingview_watchlist_json,
)
from .sources.base import SourceDescriptor

# Per-domain staleness threshold for technical / news meta.
# Data older than this is flagged as stale in diagnostics.
_META_DOMAIN_STALE_HOURS: float = 48.0


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
    "largecap_watchlist_json": _SourceProvider(
        descriptor=largecap_watchlist_json.describe_source(),
        load_structure=largecap_watchlist_json.load_raw_structure_input,
        load_meta=largecap_watchlist_json.load_raw_meta_input,
    ),
    "live_news_snapshot_json": _SourceProvider(
        descriptor=live_news_snapshot_json.describe_source(),
        load_structure=live_news_snapshot_json.load_raw_structure_input,
        load_meta=live_news_snapshot_json.load_raw_meta_input,
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
        "largecap_watchlist_json",
    ],
    "technical": [
        "fmp_watchlist_json",
        "tradingview_watchlist_json",
        "largecap_watchlist_json",
    ],
    "news": [
        "live_news_snapshot_json",
        "benzinga_watchlist_json",
        "largecap_watchlist_json",
    ],
}

_SYNTHETIC_STRUCTURE_ARTIFACT_META_SOURCE = "synthetic_structure_artifact_meta"
_SOURCE_DOMAIN_STATUS_KEY = "_meta_domain_statuses"
_LOG = logging.getLogger(__name__)


def _can_supply_domain(provider: _SourceProvider, domain: str) -> bool:
    caps = provider.descriptor.capabilities
    if domain == "structure":
        return bool(caps.has_structure)
    if domain == "volume":
        return bool(caps.has_meta)
    if domain in {"technical", "news"}:
        # Silent-fallback audit (2026-06-10): derive membership from
        # _DOMAIN_SOURCE_ORDER instead of duplicating the name sets here
        # — the two copies had to be kept in sync by hand (feature-flag
        # SSOT lesson: one owner per fact).
        return provider.descriptor.name in _DOMAIN_SOURCE_ORDER[domain]
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
        if (
            name == "structure_artifact_json"
            and wants_specific_artifact
            and not structure_artifact_json.has_artifact_for_symbol_timeframe(wanted_symbol, wanted_timeframe)
        ):
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
        contract_summary = structure_artifact_json.discover_normalized_contract_summary(repo_state_only=True)
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
        resolution_mode = "n/a"
        if structure == "structure_artifact_json":
            resolution_mode = structure_artifact_json.resolve_artifact_mode(
                symbol.strip().upper(), str(timeframe).strip()
            )
        return {
            "structure": structure,
            "volume": volume,
            "technical": technical,
            "news": news,
            "structure_resolution_mode": resolution_mode,
        }

    if normalized not in _SOURCE_PROVIDERS:
        known = ", ".join(sorted(_SOURCE_PROVIDERS))
        raise ValueError(f"unknown source {source}; expected one of: {known}, auto")

    # Explicit source keeps single-provider behavior for all domains.
    resolution_mode = "n/a"
    if normalized == "structure_artifact_json":
        resolution_mode = structure_artifact_json.resolve_artifact_mode(
            symbol.strip().upper(), str(timeframe).strip()
        )
    return {
        "structure": normalized,
        "volume": normalized,
        "technical": normalized,
        "news": normalized,
        "structure_resolution_mode": resolution_mode,
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
        skipped: list[str] = []
        for name in _DOMAIN_SOURCE_ORDER["structure"]:
            provider = _SOURCE_PROVIDERS.get(name)
            if provider is None or not _can_supply_domain(provider, "structure"):
                continue

            artifact_expected = False
            if name == "structure_artifact_json":
                artifact_expected = structure_artifact_json.has_artifact_for_symbol_timeframe(symbol, timeframe)

            try:
                loaded = provider.load_structure(symbol, timeframe)
            except FileNotFoundError as exc:
                last_error = exc
                skipped.append(name)
                continue
            except ValueError as exc:
                if name == "structure_artifact_json" and artifact_expected:
                    raise ValueError(
                        "structure artifact exists for symbol/timeframe but failed validation"
                    ) from exc
                last_error = exc
                skipped.append(name)
                continue
            if skipped:
                # Silent-fallback audit (2026-06-10): higher-priority
                # structure sources failed and a lower-priority one was
                # served — a quality downgrade that must be visible.
                _LOG.warning(
                    "structure auto-select for %s/%s: fell back to %s after "
                    "%s failed (last error: %s)",
                    symbol,
                    timeframe,
                    name,
                    ", ".join(skipped),
                    last_error,
                )
            return loaded
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


def _try_load_meta_domain(
    domain: str,
    symbol: str,
    timeframe: str,
    primary_name: str,
    *,
    auto_mode: bool,
    reference_time: float | None = None,
) -> tuple[dict[str, Any] | None, str, str]:
    """Load a meta domain from the primary provider, falling back through
    other domain-capable providers when *auto_mode* is ``True``.

    Returns ``(meta_dict | None, status, actual_provider_name)``.
    """
    candidates = [primary_name]
    if auto_mode:
        for name in _DOMAIN_SOURCE_ORDER.get(domain, []):
            if name != primary_name and name in _SOURCE_PROVIDERS and _can_supply_domain(_SOURCE_PROVIDERS[name], domain):
                candidates.append(name)

    last_status = "not_attempted"
    last_provider_name = primary_name
    attempted_any_candidate = False
    saw_domain_key_absent = False
    for name in candidates:
        provider = _SOURCE_PROVIDERS.get(name)
        if provider is None:
            continue
        last_provider_name = name
        attempted_any_candidate = True
        try:
            meta = provider.load_meta(symbol, timeframe, reference_time=reference_time)
        except FileNotFoundError:
            last_status = "source_file_not_found"
            if not auto_mode:
                raise
            continue
        except ValueError:
            last_status = "source_validation_error"
            if not auto_mode:
                raise
            continue
        except Exception as exc:
            last_status = "source_load_error"
            if not auto_mode:
                raise
            _LOG.warning(
                "meta load failed for provider %s symbol %s/%s domain %s: %r",
                name,
                symbol,
                timeframe,
                domain,
                exc,
                exc_info=True,
            )
            continue
        domain_statuses = meta.get(_SOURCE_DOMAIN_STATUS_KEY)
        hinted_status = ""
        if isinstance(domain_statuses, dict):
            hinted_status = str(domain_statuses.get(domain) or "").strip()
        meta = dict(meta)
        meta.pop(_SOURCE_DOMAIN_STATUS_KEY, None)
        if domain not in meta:
            last_status = hinted_status or "domain_key_absent"
            saw_domain_key_absent = True
            continue
        return meta, "present", name

    if not attempted_any_candidate:
        last_status = "not_attempted_no_candidates"
    elif saw_domain_key_absent and last_status == "domain_key_absent":
        last_status = "domain_key_absent_all_candidates"

    if domain in {"volume", "technical", "news"}:
        _LOG.warning(
            "meta domain %s dropped for %s/%s; planned_source=%s actual_source=%s status=%s reason_code=%s auto_mode=%s",
            domain,
            str(symbol).strip().upper(),
            str(timeframe).strip(),
            primary_name,
            last_provider_name,
            last_status,
            last_status,
            auto_mode,
        )

    return None, last_status, last_provider_name


def _build_synthetic_volume_meta(symbol: str, timeframe: str, *, asof_ts: float) -> dict[str, Any]:
    normalized_symbol = str(symbol).strip().upper()
    normalized_timeframe = str(timeframe).strip()
    fresh_asof = float(asof_ts)
    return {
        "symbol": normalized_symbol,
        "timeframe": normalized_timeframe,
        "asof_ts": fresh_asof,
        "volume": {
            "value": {
                "regime": "SYNTHETIC_FALLBACK",
                "thin_fraction": 0.0,
            },
            "asof_ts": fresh_asof,
            "stale": False,
        },
        "provenance": [
            f"smc_integration:{_SYNTHETIC_STRUCTURE_ARTIFACT_META_SOURCE}",
            f"smc_integration:{_SYNTHETIC_STRUCTURE_ARTIFACT_META_SOURCE}#symbol={normalized_symbol}",
            f"smc_integration:{_SYNTHETIC_STRUCTURE_ARTIFACT_META_SOURCE}#timeframe={normalized_timeframe}",
            "smc_integration:volume_regime_synthetic_fallback",
        ],
    }


def _finalize_composite_meta(
    *,
    symbol: str,
    timeframe: str,
    reference_time: float | None,
    structure_source: str,
    planned_volume_source: str,
    volume_meta: dict[str, Any],
    volume_domain_status: str,
    actual_volume_source: str,
    volume_fallback_used: bool,
    planned_technical_source: str,
    technical_meta: dict[str, Any] | None,
    technical_domain_status: str,
    actual_technical_source: str,
    technical_fallback_used: bool,
    planned_news_source: str,
    news_meta: dict[str, Any] | None,
    news_domain_status: str,
    actual_news_source: str,
    news_fallback_used: bool,
    relax_missing_optional_domains: bool,
) -> dict[str, Any]:
    domain_drop_reasons: dict[str, str] = {}
    domain_drop_providers: dict[str, str] = {}
    if technical_meta is None:
        domain_drop_reasons["technical"] = technical_domain_status or "missing_optional_domain"
        if actual_technical_source:
            domain_drop_providers["technical"] = actual_technical_source
    if news_meta is None:
        domain_drop_reasons["news"] = news_domain_status or "missing_optional_domain"
        if actual_news_source:
            domain_drop_providers["news"] = actual_news_source

    for domain, reason in sorted(domain_drop_reasons.items()):
        _LOG.warning(
            "domain_drop: domain=%s reason=%s provider=%s symbol=%s timeframe=%s planned_source=%s",
            domain,
            reason,
            domain_drop_providers.get(domain, ""),
            str(symbol).strip().upper(),
            str(timeframe).strip(),
            planned_technical_source if domain == "technical" else planned_news_source,
        )

    merged = merge_raw_meta_domains(
        volume_meta=volume_meta,
        technical_meta=technical_meta,
        news_meta=news_meta,
        domain_sources={
            "structure": structure_source,
            "volume": actual_volume_source,
            "technical": actual_technical_source,
            "news": actual_news_source,
        },
        domain_drop_reasons=domain_drop_reasons,
        domain_drop_providers=domain_drop_providers,
    )

    diagnostics: dict[str, Any] = {
        "volume": volume_domain_status,
        "volume_planned_source": planned_volume_source,
        "volume_source": actual_volume_source,
        "volume_fallback_used": bool(volume_fallback_used),
        "technical": technical_domain_status,
        "technical_planned_source": planned_technical_source,
        "technical_source": actual_technical_source,
        "technical_fallback_used": bool(technical_fallback_used),
        "news": news_domain_status,
        "news_planned_source": planned_news_source,
        "news_source": actual_news_source,
        "news_fallback_used": bool(news_fallback_used),
    }

    now = float(reference_time) if reference_time is not None else time.time()
    for domain, domain_meta, _domain_status in [
        ("volume", volume_meta, volume_domain_status),
        ("technical", technical_meta, technical_domain_status),
        ("news", news_meta, news_domain_status),
    ]:
        if domain_meta is None:
            diagnostics[f"{domain}_asof_ts"] = None
            diagnostics[f"{domain}_age_hours"] = None
            diagnostics[f"{domain}_stale"] = not (relax_missing_optional_domains and domain in {"technical", "news"})
            continue

        domain_asof = domain_meta.get("asof_ts")
        if isinstance(domain_asof, (int, float)) and math.isfinite(domain_asof) and domain_asof > 0:
            age_hours = (now - float(domain_asof)) / 3600.0
            diagnostics[f"{domain}_asof_ts"] = float(domain_asof)
            diagnostics[f"{domain}_age_hours"] = round(age_hours, 2)
            diagnostics[f"{domain}_stale"] = age_hours > _META_DOMAIN_STALE_HOURS
        else:
            diagnostics[f"{domain}_asof_ts"] = None
            diagnostics[f"{domain}_age_hours"] = None
            diagnostics[f"{domain}_stale"] = not (relax_missing_optional_domains and domain in {"technical", "news"})

    merged["meta_domain_diagnostics"] = diagnostics

    merged_asof_ts = merged.get("asof_ts")
    if not isinstance(merged_asof_ts, (int, float)):
        raise ValueError("merged raw_meta has invalid asof_ts type")
    merged_asof_ts_f = float(merged_asof_ts)
    if not math.isfinite(merged_asof_ts_f) or merged_asof_ts_f <= 0:
        raise ValueError("merged raw_meta has invalid asof_ts value")

    stale_threshold_secs = 90 * 24 * 60 * 60
    if merged_asof_ts_f < (now - stale_threshold_secs):
        provenance = merged.get("provenance", [])
        if not isinstance(provenance, list):
            provenance = []
        stale_marker = "smc_integration:warning:stale_meta_asof_ts"
        if stale_marker not in provenance:
            provenance.append(stale_marker)
        merged["provenance"] = provenance

    return merged


def load_raw_meta_input_composite(
    symbol: str,
    timeframe: str,
    *,
    source: str = "auto",
    reference_time: float | None = None,
) -> dict[str, Any]:
    normalized = source.strip().lower()
    auto_mode = normalized == "auto"
    plan = discover_composite_source_plan(source=source, symbol=symbol, timeframe=timeframe)

    structure_provider = _SOURCE_PROVIDERS[plan["structure"]]

    volume_meta_raw, volume_domain_status, actual_volume_source = _try_load_meta_domain(
        "volume", symbol, timeframe, plan["volume"], auto_mode=auto_mode, reference_time=reference_time,
    )
    # volume is mandatory – if _try_load_meta_domain returned None, fall back
    # to the planned provider so merge_raw_meta_domains raises clearly.
    if volume_meta_raw is None:
        volume_provider = _SOURCE_PROVIDERS[plan["volume"]]
        volume_meta = volume_provider.load_meta(symbol, timeframe, reference_time=reference_time)
        actual_volume_source = plan["volume"]
        # L7 (silent-fallback audit): if the direct load above succeeds,
        # the domain IS present — state that here instead of re-deriving
        # it from ``volume_meta_raw is None`` at the call site below.
        volume_domain_status = "present"
        volume_fallback_used = False
    else:
        volume_meta = volume_meta_raw
        volume_fallback_used = actual_volume_source != plan["volume"]

    technical_meta, technical_domain_status, actual_technical_source = _try_load_meta_domain(
        "technical", symbol, timeframe, plan["technical"], auto_mode=auto_mode, reference_time=reference_time,
    )
    news_meta, news_domain_status, actual_news_source = _try_load_meta_domain(
        "news", symbol, timeframe, plan["news"], auto_mode=auto_mode, reference_time=reference_time,
    )

    return _finalize_composite_meta(
        symbol=symbol,
        timeframe=timeframe,
        reference_time=reference_time,
        structure_source=structure_provider.descriptor.name,
        planned_volume_source=plan["volume"],
        volume_meta=volume_meta,
        volume_domain_status=volume_domain_status,
        actual_volume_source=actual_volume_source,
        volume_fallback_used=volume_fallback_used,
        planned_technical_source=plan["technical"],
        technical_meta=technical_meta,
        technical_domain_status=technical_domain_status,
        actual_technical_source=actual_technical_source,
        technical_fallback_used=actual_technical_source != plan["technical"] and technical_domain_status == "present",
        planned_news_source=plan["news"],
        news_meta=news_meta,
        news_domain_status=news_domain_status,
        actual_news_source=actual_news_source,
        news_fallback_used=actual_news_source != plan["news"] and news_domain_status == "present",
        relax_missing_optional_domains=False,
    )


def load_raw_meta_input_composite_for_release_reference(
    symbol: str,
    timeframe: str,
    *,
    source: str = "auto",
    reference_time: float | None = None,
) -> dict[str, Any]:
    normalized = source.strip().lower()
    if normalized != "auto":
        return load_raw_meta_input_composite(
            symbol,
            timeframe,
            source=source,
            reference_time=reference_time,
        )

    plan = discover_composite_source_plan(source=source, symbol=symbol, timeframe=timeframe)
    structure_source = plan["structure"]
    if structure_source != "structure_artifact_json" or not structure_artifact_json.has_artifact_for_symbol_timeframe(symbol, timeframe):
        return load_raw_meta_input_composite(
            symbol,
            timeframe,
            source=source,
            reference_time=reference_time,
        )

    volume_meta_raw, volume_domain_status, actual_volume_source = _try_load_meta_domain(
        "volume", symbol, timeframe, plan["volume"], auto_mode=True, reference_time=reference_time,
    )
    if volume_meta_raw is None:
        fallback_asof = float(reference_time) if reference_time is not None else time.time()
        volume_meta = _build_synthetic_volume_meta(symbol, timeframe, asof_ts=fallback_asof)
        volume_domain_status = "synthetic_fallback"
        actual_volume_source = _SYNTHETIC_STRUCTURE_ARTIFACT_META_SOURCE
        volume_fallback_used = True
    else:
        volume_meta = volume_meta_raw
        volume_fallback_used = actual_volume_source != plan["volume"]

    technical_meta, technical_domain_status, actual_technical_source = _try_load_meta_domain(
        "technical", symbol, timeframe, plan["technical"], auto_mode=True, reference_time=reference_time,
    )
    news_meta, news_domain_status, actual_news_source = _try_load_meta_domain(
        "news", symbol, timeframe, plan["news"], auto_mode=True, reference_time=reference_time,
    )

    return _finalize_composite_meta(
        symbol=symbol,
        timeframe=timeframe,
        reference_time=reference_time,
        structure_source=structure_source,
        planned_volume_source=plan["volume"],
        volume_meta=volume_meta,
        volume_domain_status=volume_domain_status,
        actual_volume_source=actual_volume_source,
        volume_fallback_used=volume_fallback_used,
        planned_technical_source=plan["technical"],
        technical_meta=technical_meta,
        technical_domain_status=technical_domain_status,
        actual_technical_source=actual_technical_source,
        technical_fallback_used=actual_technical_source != plan["technical"] and technical_domain_status == "present",
        planned_news_source=plan["news"],
        news_meta=news_meta,
        news_domain_status=news_domain_status,
        actual_news_source=actual_news_source,
        news_fallback_used=actual_news_source != plan["news"] and news_domain_status == "present",
        relax_missing_optional_domains=True,
    )
