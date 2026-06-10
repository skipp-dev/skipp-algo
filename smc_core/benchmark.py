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
    time_to_mitigation_mean: float = 0.0
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
        else:
            partial_fill_miss_total += float(e.get("partial_fill_pct", 0))
            miss_count += 1
        if e.get("invalidated"):
            invalids += 1
        ttm_total += float(e.get("time_to_mitigation", 0))
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
        time_to_mitigation_mean=round(ttm_total / n, 2),
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


# --- D2: tri-axis FVG breakdown (Plan §2.1 D2) ---

# Minimum events per (session × htf_bias × vol_regime) bucket required
# before a hit-rate is considered statistically meaningful. Buckets
# below the floor are reported with ``insufficient = True`` and a
# ``hit_rate`` of ``None`` so downstream consumers cannot accidentally
# act on noise. Five matches the project-wide minimum already used in
# benchmark KPIs.
_FVG_BUCKET_MIN_EVENTS = 5


@dataclass(slots=True, frozen=True)
class StratifiedFvgBucket:
    """Single (session × htf_bias × vol_regime) cell of the D2 report."""

    session: str
    htf_bias: str
    vol_regime: str
    n_events: int
    hits: int
    hit_rate: float | None
    insufficient: bool


def stratified_fvg_report(
    events: list[dict[str, Any]],
    *,
    min_events: int = _FVG_BUCKET_MIN_EVENTS,
) -> dict[str, Any]:
    """Plan §2.1 D2 — tri-axis FVG hit-rate report.

    Aggregates evaluated FVG events by ``session × htf_bias × vol_regime``
    and returns a deterministic, JSON-serialisable summary suitable for
    the dashboard's FVG Health tooltip and the calibration report.

    Each event must expose ``hit`` (bool / int) plus the three context
    keys (``session``, ``htf_bias``, ``vol_regime``). Missing keys fall
    back to ``"UNKNOWN"`` so the report stays defensive against partial
    inputs.

    The function intentionally returns ``hit_rate = None`` for buckets
    below ``min_events`` rather than zero — a 0% hit rate from one event
    is not the same signal as a 0% hit rate from 25 events, and
    flattening them would silently lie to the operator.

    The output also includes an ``actionable_buckets`` list of
    ``(bucket_key, hit_rate, n_events)`` tuples for buckets that meet
    the floor and exceed ``hit_rate >= 0.70`` — these are the contexts
    that the plan requires before FVG can be promoted from a tie-breaker
    to a contextual gate (Phase F2 wiring).
    """
    by_bucket: dict[tuple[str, str, str], list[int]] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        session = str(event.get("session") or "UNKNOWN").strip().upper() or "UNKNOWN"
        htf_bias = str(event.get("htf_bias") or "UNKNOWN").strip().upper() or "UNKNOWN"
        vol_regime = str(event.get("vol_regime") or "UNKNOWN").strip().upper() or "UNKNOWN"
        hit_raw = event.get("hit", False)
        hit_val = 1 if bool(hit_raw) else 0
        by_bucket.setdefault((session, htf_bias, vol_regime), []).append(hit_val)

    buckets: list[StratifiedFvgBucket] = []
    for (session, htf_bias, vol_regime), hits in sorted(by_bucket.items()):
        n_events = len(hits)
        hit_count = sum(hits)
        insufficient = n_events < min_events
        hit_rate = None if insufficient else round(hit_count / n_events, 4)
        buckets.append(
            StratifiedFvgBucket(
                session=session,
                htf_bias=htf_bias,
                vol_regime=vol_regime,
                n_events=n_events,
                hits=hit_count,
                hit_rate=hit_rate,
                insufficient=insufficient,
            )
        )

    actionable = [
        {
            "session": b.session,
            "htf_bias": b.htf_bias,
            "vol_regime": b.vol_regime,
            "n_events": b.n_events,
            "hit_rate": b.hit_rate,
        }
        for b in buckets
        if not b.insufficient and b.hit_rate is not None and b.hit_rate >= 0.70
    ]

    total_events = sum(b.n_events for b in buckets)
    total_hits = sum(b.hits for b in buckets)
    overall_hit_rate = round(total_hits / total_events, 4) if total_events else None

    return {
        "min_events": min_events,
        "total_events": total_events,
        "total_buckets": len(buckets),
        "actionable_bucket_count": len(actionable),
        "overall_hit_rate": overall_hit_rate,
        "buckets": [
            {
                "session": b.session,
                "htf_bias": b.htf_bias,
                "vol_regime": b.vol_regime,
                "n_events": b.n_events,
                "hits": b.hits,
                "hit_rate": b.hit_rate,
                "insufficient": b.insufficient,
            }
            for b in buckets
        ],
        "actionable_buckets": actionable,
    }


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
