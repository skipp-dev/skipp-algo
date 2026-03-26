from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

from .repo_sources import discover_repo_sources
from .sources import structure_artifact_json

Mode = Literal["full", "partial", "none"]


@dataclass(frozen=True)
class ProviderPotential:
    can_supply_symbols: bool
    can_supply_volume_meta: bool
    can_supply_technical_meta: bool
    can_supply_news_meta: bool
    can_supply_raw_bars: bool
    can_supply_microstructure: bool
    can_supply_precomputed_structure: bool


@dataclass(frozen=True)
class ProviderCurrentMapping:
    currently_maps_structure: bool
    currently_maps_meta: bool
    currently_maps_volume: bool
    currently_maps_technical: bool
    currently_maps_news: bool
    snapshot_structure_mode: Mode
    snapshot_meta_mode: Mode
    mapped_structure_fields: list[str] = field(default_factory=list)
    mapped_structure_categories: dict[str, bool] = field(default_factory=dict)
    mapped_meta_fields: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProviderMatrixEntry:
    name: str
    source_module: str
    path_hint: str
    source_format: str
    potential: ProviderPotential
    current: ProviderCurrentMapping
    known_gaps: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _source_format(path_hint: str) -> str:
    normalized = str(path_hint).strip().lower()
    if normalized.endswith(".csv"):
        return "csv"
    if normalized.endswith(".json"):
        return "json"
    return "other"


def _source_module_for_name(name: str) -> str:
    return f"smc_integration.sources.{name}"


def _potential_for_provider(name: str) -> ProviderPotential:
    if name == "structure_artifact_json":
        return ProviderPotential(
            can_supply_symbols=True,
            can_supply_volume_meta=False,
            can_supply_technical_meta=False,
            can_supply_news_meta=False,
            can_supply_raw_bars=False,
            can_supply_microstructure=True,
            can_supply_precomputed_structure=True,
        )

    if name == "databento_watchlist_csv":
        return ProviderPotential(
            can_supply_symbols=True,
            can_supply_volume_meta=True,
            can_supply_technical_meta=False,
            can_supply_news_meta=False,
            can_supply_raw_bars=True,
            can_supply_microstructure=True,
            can_supply_precomputed_structure=False,
        )

    if name == "tradingview_watchlist_json":
        return ProviderPotential(
            can_supply_symbols=True,
            can_supply_volume_meta=True,
            can_supply_technical_meta=True,
            can_supply_news_meta=False,
            can_supply_raw_bars=True,
            can_supply_microstructure=False,
            can_supply_precomputed_structure=False,
        )

    if name == "fmp_watchlist_json":
        return ProviderPotential(
            can_supply_symbols=True,
            can_supply_volume_meta=True,
            can_supply_technical_meta=True,
            can_supply_news_meta=False,
            can_supply_raw_bars=True,
            can_supply_microstructure=False,
            can_supply_precomputed_structure=False,
        )

    if name == "benzinga_watchlist_json":
        return ProviderPotential(
            can_supply_symbols=True,
            can_supply_volume_meta=True,
            can_supply_technical_meta=False,
            can_supply_news_meta=True,
            can_supply_raw_bars=True,
            can_supply_microstructure=False,
            can_supply_precomputed_structure=False,
        )

    return ProviderPotential(
        can_supply_symbols=True,
        can_supply_volume_meta=False,
        can_supply_technical_meta=False,
        can_supply_news_meta=False,
        can_supply_raw_bars=False,
        can_supply_microstructure=False,
        can_supply_precomputed_structure=False,
    )


def _current_mapping_for_provider(name: str) -> ProviderCurrentMapping:
    mapped_meta_fields = [
        "symbol",
        "timeframe",
        "asof_ts",
        "volume.regime",
        "volume.thin_fraction",
        "provenance",
    ]

    if name == "structure_artifact_json":
        has_any = structure_artifact_json.has_any_structure_artifact()
        category_coverage = structure_artifact_json.discover_category_coverage() if has_any else {
            "bos": False,
            "choch": False,
            "orderblocks": False,
            "fvg": False,
            "liquidity_sweeps": False,
        }

        mapped_fields: list[str] = []
        if category_coverage.get("bos"):
            mapped_fields.extend([
                "bos.id",
                "bos.time",
                "bos.price",
                "bos.kind",
                "bos.dir",
            ])
        if category_coverage.get("orderblocks"):
            mapped_fields.extend([
                "orderblocks.id",
                "orderblocks.low",
                "orderblocks.high",
                "orderblocks.dir",
                "orderblocks.valid",
            ])
        if category_coverage.get("fvg"):
            mapped_fields.extend([
                "fvg.id",
                "fvg.low",
                "fvg.high",
                "fvg.dir",
                "fvg.valid",
            ])
        if category_coverage.get("liquidity_sweeps"):
            mapped_fields.extend([
                "liquidity_sweeps.id",
                "liquidity_sweeps.time",
                "liquidity_sweeps.price",
                "liquidity_sweeps.side",
            ])

        has_structure_now = has_any and any(category_coverage.values())
        return ProviderCurrentMapping(
            currently_maps_structure=has_structure_now,
            currently_maps_meta=False,
            currently_maps_volume=False,
            currently_maps_technical=False,
            currently_maps_news=False,
            snapshot_structure_mode="full" if has_structure_now and all(category_coverage.values()) else "partial" if has_structure_now else "none",
            snapshot_meta_mode="none",
            mapped_structure_fields=mapped_fields,
            mapped_structure_categories=category_coverage,
            mapped_meta_fields=[],
        )

    if name == "databento_watchlist_csv":
        return ProviderCurrentMapping(
            currently_maps_structure=False,
            currently_maps_meta=True,
            currently_maps_volume=True,
            currently_maps_technical=False,
            currently_maps_news=False,
            snapshot_structure_mode="partial",
            snapshot_meta_mode="partial",
            mapped_structure_fields=[],
            mapped_structure_categories={
                "bos": False,
                "choch": False,
                "orderblocks": False,
                "fvg": False,
                "liquidity_sweeps": False,
            },
            mapped_meta_fields=mapped_meta_fields,
        )

    if name in {"tradingview_watchlist_json", "fmp_watchlist_json"}:
        return ProviderCurrentMapping(
            currently_maps_structure=False,
            currently_maps_meta=True,
            currently_maps_volume=True,
            currently_maps_technical=True,
            currently_maps_news=False,
            snapshot_structure_mode="none",
            snapshot_meta_mode="partial",
            mapped_structure_fields=[],
            mapped_structure_categories={
                "bos": False,
                "choch": False,
                "orderblocks": False,
                "fvg": False,
                "liquidity_sweeps": False,
            },
            mapped_meta_fields=mapped_meta_fields + [
                "technical.value.strength",
                "technical.value.bias",
                "technical.asof_ts",
                "technical.stale",
            ],
        )

    if name == "benzinga_watchlist_json":
        return ProviderCurrentMapping(
            currently_maps_structure=False,
            currently_maps_meta=True,
            currently_maps_volume=True,
            currently_maps_technical=False,
            currently_maps_news=True,
            snapshot_structure_mode="none",
            snapshot_meta_mode="partial",
            mapped_structure_fields=[],
            mapped_structure_categories={
                "bos": False,
                "choch": False,
                "orderblocks": False,
                "fvg": False,
                "liquidity_sweeps": False,
            },
            mapped_meta_fields=mapped_meta_fields + [
                "news.value.strength",
                "news.value.bias",
                "news.asof_ts",
                "news.stale",
            ],
        )

    return ProviderCurrentMapping(
        currently_maps_structure=False,
        currently_maps_meta=True,
        currently_maps_volume=True,
        currently_maps_technical=False,
        currently_maps_news=False,
        snapshot_structure_mode="none",
        snapshot_meta_mode="partial",
        mapped_structure_fields=[],
        mapped_structure_categories={
            "bos": False,
            "choch": False,
            "orderblocks": False,
            "fvg": False,
            "liquidity_sweeps": False,
        },
        mapped_meta_fields=mapped_meta_fields,
    )


def _known_gaps_for_provider(name: str) -> list[str]:
    common = [
        "No explicit BOS/OB/FVG/Sweep events in source artifact",
        "Technical/news fields are not currently mapped into raw_meta",
    ]

    if name == "structure_artifact_json":
        coverage = structure_artifact_json.discover_category_coverage() if structure_artifact_json.has_any_structure_artifact() else {
            "bos": False,
            "choch": False,
            "orderblocks": False,
            "fvg": False,
            "liquidity_sweeps": False,
        }
        gaps: list[str] = []
        if not coverage.get("bos"):
            gaps.append("BOS events are not currently mapped in artifact structure output")
        if not coverage.get("choch"):
            gaps.append("CHOCH events are not currently mapped in artifact structure output")
        if not coverage.get("orderblocks"):
            gaps.append("Orderblocks are not currently mapped in artifact structure output")
        if not coverage.get("fvg"):
            gaps.append("FVG events are not currently mapped in artifact structure output")
        if not coverage.get("liquidity_sweeps"):
            gaps.append("Liquidity sweeps are not currently mapped in artifact structure output")
        gaps.append("Provider is structure-only and does not expose raw meta domains")
        return gaps

    if name == "databento_watchlist_csv":
        return [
            "Source descriptor marks partial structure but mapped structure arrays are currently empty",
            "Technical/news paths are currently unset in integration mapping",
        ]

    if name == "benzinga_watchlist_json":
        return [
            "No explicit BOS/OB/FVG/sweep events in source artifact",
            "News mapping requires explicit fields (news or news_strength/news_bias)",
        ]

    if name == "tradingview_watchlist_json":
        return [
            "No explicit BOS/OB/FVG/sweep events in source artifact",
            "Technical mapping requires explicit fields (technical or technical_strength/technical_bias)",
        ]

    if name == "fmp_watchlist_json":
        return [
            "No explicit BOS/OB/FVG/sweep events in source artifact",
            "Technical mapping requires explicit fields (technical or technical_strength/technical_bias)",
        ]

    return common


def discover_provider_matrix() -> list[ProviderMatrixEntry]:
    entries: list[ProviderMatrixEntry] = []
    for source in discover_repo_sources():
        entry = ProviderMatrixEntry(
            name=source.name,
            source_module=_source_module_for_name(source.name),
            path_hint=source.path_hint,
            source_format=_source_format(source.path_hint),
            potential=_potential_for_provider(source.name),
            current=_current_mapping_for_provider(source.name),
            known_gaps=_known_gaps_for_provider(source.name),
            notes=list(source.notes),
        )
        entries.append(entry)
    return entries


def provider_matrix_to_dict(entries: list[ProviderMatrixEntry]) -> list[dict]:
    return [asdict(entry) for entry in entries]


def _pick_best_structure_provider(entries: list[ProviderMatrixEntry]) -> str | None:
    ranked = [
        entry
        for entry in entries
        if entry.current.currently_maps_structure
        and entry.current.snapshot_structure_mode in {"full", "partial"}
    ]
    if not ranked:
        return None

    mode_rank = {"full": 2, "partial": 1, "none": 0}
    ranked.sort(key=lambda item: (mode_rank[item.current.snapshot_structure_mode], item.name), reverse=True)
    return ranked[0].name


def _pick_best_candidate(entries: list[ProviderMatrixEntry], *, domain: str) -> str | None:
    if domain == "news":
        candidates = [entry for entry in entries if entry.current.currently_maps_news]
    elif domain == "technical":
        candidates = [entry for entry in entries if entry.current.currently_maps_technical]
    elif domain == "microstructure":
        candidates = [entry for entry in entries if entry.potential.can_supply_microstructure]
    else:
        candidates = []

    if not candidates:
        return None
    candidates.sort(key=lambda item: item.name)
    return candidates[0].name


def build_provider_summary() -> dict:
    entries = discover_provider_matrix()

    structure_modes = [entry.current.snapshot_structure_mode for entry in entries]
    meta_modes = [entry.current.snapshot_meta_mode for entry in entries]

    summary = {
        "providers": provider_matrix_to_dict(entries),
        "counts": {
            "total": len(entries),
            "structure_full": sum(1 for mode in structure_modes if mode == "full"),
            "structure_partial": sum(1 for mode in structure_modes if mode == "partial"),
            "structure_none": sum(1 for mode in structure_modes if mode == "none"),
            "meta_full": sum(1 for mode in meta_modes if mode == "full"),
            "meta_partial": sum(1 for mode in meta_modes if mode == "partial"),
            "meta_none": sum(1 for mode in meta_modes if mode == "none"),
        },
        "best_current_structure_provider": _pick_best_structure_provider(entries),
        "best_current_news_candidate": _pick_best_candidate(entries, domain="news"),
        "best_current_technical_candidate": _pick_best_candidate(entries, domain="technical"),
        "best_current_microstructure_candidate": _pick_best_candidate(entries, domain="microstructure"),
    }
    return summary
