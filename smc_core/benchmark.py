"""Standardized SMC benchmark & visualization artifact framework.

Defines KPI sets per event family, stratification dimensions,
and a single entry-point to produce all benchmark artifacts.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from smc_core.schema_version import SCHEMA_VERSION

EventFamily = Literal["BOS", "OB", "FVG", "SWEEP"]

STRATIFICATION_DIMENSIONS = ("session", "htf_bias", "vol_regime")


@dataclass(slots=True)
class EventFamilyKPI:
    """KPI set for a single event family."""

    family: EventFamily
    hit_rate: float = 0.0
    time_to_mitigation_mean: float = 0.0
    invalidation_rate: float = 0.0
    mae: float = 0.0   # Maximum Adverse Excursion (mean)
    mfe: float = 0.0   # Maximum Favorable Excursion (mean)
    n_events: int = 0


@dataclass(slots=True)
class BenchmarkResult:
    """Full benchmark result for one symbol+timeframe combination."""

    symbol: str
    timeframe: str
    generated_at: float = field(default_factory=time.time)
    schema_version: str = SCHEMA_VERSION
    kpis: list[EventFamilyKPI] = field(default_factory=list)
    stratified: dict[str, list[EventFamilyKPI]] = field(default_factory=dict)


def compute_event_family_kpi(
    events: list[dict[str, Any]],
    family: EventFamily,
) -> EventFamilyKPI:
    """Compute KPIs for a list of evaluated events.

    Each event dict is expected to have at least:
      - ``hit`` (bool)
      - ``time_to_mitigation`` (float, bars)
      - ``invalidated`` (bool)
      - ``mae`` (float)
      - ``mfe`` (float)

    Missing keys degrade gracefully.
    """
    if not events:
        return EventFamilyKPI(family=family)

    hits = 0
    invalids = 0
    ttm_total = 0.0
    mae_total = 0.0
    mfe_total = 0.0

    for e in events:
        if e.get("hit"):
            hits += 1
        if e.get("invalidated"):
            invalids += 1
        ttm_total += float(e.get("time_to_mitigation", 0))
        mae_total += float(e.get("mae", 0))
        mfe_total += float(e.get("mfe", 0))

    n = len(events)
    return EventFamilyKPI(
        family=family,
        hit_rate=round(hits / n, 4),
        time_to_mitigation_mean=round(ttm_total / n, 2),
        invalidation_rate=round(invalids / n, 4),
        mae=round(mae_total / n, 4),
        mfe=round(mfe_total / n, 4),
        n_events=n,
    )


def build_benchmark(
    symbol: str,
    timeframe: str,
    *,
    events_by_family: dict[EventFamily, list[dict[str, Any]]],
    stratified_events: dict[str, dict[EventFamily, list[dict[str, Any]]]] | None = None,
) -> BenchmarkResult:
    """Build a full benchmark result for one symbol+timeframe.

    Parameters
    ----------
    events_by_family:
        Mapping from event family to list of evaluated event dicts.
    stratified_events:
        Optional stratification keyed by dimension (e.g., ``"session:NY_AM"``).
    """
    kpis = [compute_event_family_kpi(evts, fam) for fam, evts in events_by_family.items()]

    stratified: dict[str, list[EventFamilyKPI]] = {}
    if stratified_events:
        for dim_key, fam_events in stratified_events.items():
            stratified[dim_key] = [compute_event_family_kpi(evts, fam) for fam, evts in fam_events.items()]

    return BenchmarkResult(
        symbol=symbol,
        timeframe=timeframe,
        kpis=kpis,
        stratified=stratified,
    )


# --- Artifact manifest ---


@dataclass(slots=True, frozen=True)
class ArtifactManifest:
    """Machine-readable manifest for the benchmark artifact set."""

    schema_version: str
    generated_at: float
    artifacts: list[str]


def export_benchmark_artifacts(
    result: BenchmarkResult,
    output_dir: Path,
) -> ArtifactManifest:
    """Write all benchmark artifacts and a manifest to *output_dir*.

    Produces:
      1. ``benchmark_{symbol}_{timeframe}.json`` — KPIs + stratifications.
      2. ``manifest.json`` — artifact registry.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Main KPI artifact
    kpi_filename = f"benchmark_{result.symbol}_{result.timeframe}.json"
    kpi_path = output_dir / kpi_filename

    payload: dict[str, Any] = {
        "schema_version": result.schema_version,
        "symbol": result.symbol,
        "timeframe": result.timeframe,
        "generated_at": result.generated_at,
        "kpis": [asdict(k) for k in result.kpis],
        "stratified": {
            dim: [asdict(k) for k in kpis]
            for dim, kpis in result.stratified.items()
        },
    }
    kpi_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    artifacts = [kpi_filename]

    # Manifest
    manifest = ArtifactManifest(
        schema_version=result.schema_version,
        generated_at=result.generated_at,
        artifacts=artifacts,
    )
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(asdict(manifest), indent=2), encoding="utf-8")

    return manifest
