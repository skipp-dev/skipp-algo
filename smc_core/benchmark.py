"""Standardized SMC benchmark & visualization artifact framework.

Defines KPI sets per event family, stratification dimensions,
and a single entry-point to produce all benchmark artifacts.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from smc_core._pytest_canonical_write_guard import (
    guard_against_canonical_repo_write_under_pytest,
)
from smc_core.schema_version import SCHEMA_VERSION

_CANONICAL_BENCHMARK_OUTPUT_DIRS = (
    "artifacts/ci/measurement_benchmark",
    "artifacts/reports/smc_measurement_benchmark",
)


def _write_text_atomic(path: Path, content: str) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


EventFamily = Literal["BOS", "OB", "FVG", "SWEEP"]

STRATIFICATION_DIMENSIONS = ("session", "htf_bias", "vol_regime")


@dataclass(slots=True)
class EventFamilyKPI:
    """KPI set for a single event family."""

    family: EventFamily
    hit_rate: float = 0.0
    time_to_mitigation_mean: float = 0.0  # mean over MITIGATED events (E12); 0.0 if no hits
    invalidation_rate: float = 0.0
    mae: float = 0.0   # Maximum Adverse Excursion (mean)
    mfe: float = 0.0   # Maximum Favorable Excursion (mean)
    n_events: int = 0
    partial_fill_pct_mean: float = 0.0  # Mean zone fill fraction for misses (0.0-1.0)
    # Strict ≥50% partial-fill hit rate (D1 label_fvg_partial_50). Only emitted
    # when the underlying events carry ``features.label_partial_50`` (currently
    # FVG only); ``None`` keeps non-FVG / legacy fixtures untouched.
    partial_50_hit_rate: float | None = None
    partial_50_n_events: int = 0


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
    partial_fill_miss_total = 0.0
    miss_count = 0
    partial_50_hits = 0
    partial_50_n = 0

    for e in events:
        if e.get("hit"):
            hits += 1
            # E12: time-to-mitigation is only meaningful for events that
            # mitigated; accumulate it in the hit branch so the mean is
            # over hits, not diluted by miss rows (which carry 0.0).
            ttm_total += float(e.get("time_to_mitigation", 0))
        else:
            partial_fill_miss_total += float(e.get("partial_fill_pct", 0))
            miss_count += 1
        if e.get("invalidated"):
            invalids += 1
        mae_total += float(e.get("mae", 0))
        mfe_total += float(e.get("mfe", 0))
        # D1 strict label: ``measurement_evidence._evaluate_zone_event``
        # writes it as a flat ``label_partial_50`` key on the payload
        # (FVG path only). The scoring pipeline mirrors it under
        # ``features.label_partial_50`` for ScoredEvent dicts. Accept
        # either to stay schema-tolerant; ``None`` means the label was
        # not emitted (legacy fixtures, non-FVG families).
        label = e.get("label_partial_50")
        if label is None:
            # schema 1.1 stores the label under outcome_extras; 1.0 under features.
            extras = e.get("outcome_extras")
            if isinstance(extras, dict):
                label = extras.get("label_partial_50")
        if label is None:
            feats = e.get("features")
            if isinstance(feats, dict):
                label = feats.get("label_partial_50")
        if label is not None:
            partial_50_n += 1
            if bool(label):
                partial_50_hits += 1

    n = len(events)
    return EventFamilyKPI(
        family=family,
        hit_rate=round(hits / n, 4),
        # Truth-audit E12 (2026-07-11): mean time-to-mitigation over the
        # events that actually mitigated. ``time_to_mitigation`` is 0.0 for
        # misses, so dividing by ``n`` (as before) scaled the mean by the
        # hit rate and systematically understated it. Divide by ``hits``.
        time_to_mitigation_mean=round(ttm_total / hits, 2) if hits > 0 else 0.0,
        invalidation_rate=round(invalids / n, 4),
        mae=round(mae_total / n, 4),
        mfe=round(mfe_total / n, 4),
        n_events=n,
        partial_fill_pct_mean=round(partial_fill_miss_total / miss_count, 4) if miss_count > 0 else 0.0,
        partial_50_hit_rate=round(partial_50_hits / partial_50_n, 4) if partial_50_n > 0 else None,
        partial_50_n_events=partial_50_n,
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


# --- D2: tri-axis FVG breakdown — REMOVED (stranded), 2026-07-28 ---
#
# ``_FVG_BUCKET_MIN_EVENTS`` / ``StratifiedFvgBucket`` / ``stratified_fvg_report``
# and their emit chain (``smc_core/fvg_pine_emit.py`` +
# ``scripts/emit_fvg_context_pine.py``) were removed with the B-sweep: no
# workflow ever invoked the emitter, no FVG_HEALTH_* constant ever reached any
# Pine library, and the docstring's promised consumers ("dashboard's FVG Health
# tooltip", "Phase F2 wiring") were never built — the only plan anchor was the
# phantom improvement-plan document that never existed in the repo. Same
# treatment as the C4.1/C3.1 inference-stack removals. Do NOT rebuild without a
# real, named consumer; the surviving FVG measurement lanes are
# ``scripts/fvg_asia_real_sample.py`` (label audit) and the family benchmarks.


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
    guard_against_canonical_repo_write_under_pytest(
        output_dir,
        canonical_relative_paths=_CANONICAL_BENCHMARK_OUTPUT_DIRS,
        caller="export_benchmark_artifacts",
    )
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
    _write_text_atomic(kpi_path, json.dumps(payload, indent=2))

    artifacts = [kpi_filename]

    # Manifest
    manifest = ArtifactManifest(
        schema_version=result.schema_version,
        generated_at=result.generated_at,
        artifacts=artifacts,
    )
    manifest_path = output_dir / "manifest.json"
    _write_text_atomic(manifest_path, json.dumps(asdict(manifest), indent=2))

    return manifest
