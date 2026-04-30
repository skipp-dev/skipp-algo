"""Zone Priority calibration from measurement benchmark data.

Reads per-family hit rates from benchmark scoring artifacts and produces
calibrated ``_FAMILY_BASE_PRIORITY`` weights and dimension multipliers
that can be fed back into :func:`build_zone_priority`.

Usage
-----
::

    python scripts/smc_zone_priority_calibration.py \\
        --benchmark-dir artifacts/ci/measurement_benchmark \\
        --output-path artifacts/reports/zone_priority_calibration.json

    # Programmatic:
    from scripts.smc_zone_priority_calibration import calibrate_from_benchmark
    cal = calibrate_from_benchmark(Path("artifacts/ci/measurement_benchmark"))
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

# S-3 (TEMPORAL_NUMERICAL_AUDIT_2026-04-24): defense-in-depth seed for the
# calibration pipeline. Currently no stochastic ops in this module, but a
# future contributor adding e.g. ``np.random.choice`` for tie-breaking would
# silently break reproducibility without this guard.
_CALIBRATION_RANDOM_SEED = 42


@dataclass(slots=True)
class FamilyStats:
    """Aggregated per-family stats across all symbol×timeframe pairs."""

    family: str
    total_events: int = 0
    total_hits: int = 0
    pair_count: int = 0
    hit_rates: list[float] = field(default_factory=list)
    weights: list[int] = field(default_factory=list)

    @property
    def weighted_hit_rate(self) -> float:
        if not self.weights or sum(self.weights) == 0:
            return 0.0
        return sum(
            r * w for r, w in zip(self.hit_rates, self.weights, strict=False)
        ) / sum(self.weights)

    @property
    def simple_hit_rate(self) -> float:
        if self.total_events == 0:
            return 0.0
        return self.total_hits / self.total_events


@dataclass(slots=True)
class CalibrationResult:
    """Output of the calibration pipeline."""

    family_weights: dict[str, float]
    rank_thresholds: dict[str, int]
    family_stats: dict[str, dict[str, Any]]
    total_events: int
    total_pairs: int
    source_dir: str
    # Optional walk-forward CV evidence (audit S-1). ``None`` if the corpus
    # was too small for the requested ``n_splits`` or CV was skipped.
    walk_forward_cv: dict[str, Any] | None = None


# ── Phase F: Contextual calibration ─────────────────────────────

_MIN_BUCKET_EVENTS = 30  # minimum events per context-bucket for promotion
_BRIER_IMPROVEMENT_THRESHOLD = 0.05  # 5pp improvement required
_FAMILIES = ("OB", "FVG", "BOS", "SWEEP")


@dataclass(slots=True)
class ContextBucketStats:
    """Per-family stats for one context bucket (e.g. session:RTH)."""

    context_key: str
    family_stats: dict[str, FamilyStats] = field(default_factory=dict)


@dataclass(slots=True)
class ContextualCalibrationResult:
    """Contextual calibration: per-dimension, per-bucket family weights."""

    # {dimension: {bucket: {family: weight}}}
    # e.g. {"session": {"RTH": {"OB": 0.85, ...}}, "vol_regime": {...}}
    contextual_weights: dict[str, dict[str, dict[str, float]]]
    promoted_buckets: list[str]  # list of "dimension:bucket" keys that met thresholds
    global_weights: dict[str, float]  # fallback
    bucket_stats: dict[str, dict[str, dict[str, Any]]]  # per-bucket detail
    min_bucket_events: int


# ── Hand-tuned defaults (from C9 launch) ────────────────────────

_DEFAULT_FAMILY_WEIGHTS: dict[str, float] = {
    "OB": 0.82,
    "FVG": 0.61,
    "BOS": 0.81,
    "SWEEP": 0.73,
}

_DEFAULT_RANK_THRESHOLDS: dict[str, int] = {
    "A": 75,
    "B": 50,
    "C": 25,
}


def _aggregate_scoring_files(scoring_files: list[Path]) -> dict[str, FamilyStats]:
    """Aggregate ``family_metrics`` from a list of scoring JSON files."""
    stats: dict[str, FamilyStats] = {}

    for scoring_file in scoring_files:
        try:
            data = json.loads(scoring_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        family_metrics = data.get("family_metrics", {})
        if not family_metrics:
            continue

        for family, fm in family_metrics.items():
            n = int(fm.get("n_events", 0))
            hr = fm.get("hit_rate")
            if n == 0 or hr is None:
                continue
            hr = float(hr)
            if math.isnan(hr):
                continue

            if family not in stats:
                stats[family] = FamilyStats(family=family)

            s = stats[family]
            s.total_events += n
            s.total_hits += round(hr * n)
            s.pair_count += 1
            s.hit_rates.append(hr)
            s.weights.append(n)

    return stats


def load_family_metrics(benchmark_dir: Path) -> dict[str, FamilyStats]:
    """Walk benchmark_dir/{SYMBOL}/{TF}/scoring_*.json and aggregate family_metrics."""
    return _aggregate_scoring_files(sorted(benchmark_dir.rglob("scoring_*.json")))


def compute_walk_forward_cv_hr(
    benchmark_dir: Path,
    *,
    n_splits: int = 5,
) -> dict[str, Any]:
    """Walk-forward cross-validated hit-rate per family (audit finding S-1).

    The existing ``calibrate_from_benchmark`` pipeline calibrates and reports
    HRs on the **same** corpus — that is in-sample by construction. This
    helper splits the scoring files chronologically (sorted by path, which
    already encodes ``benchmark_dir/{SYMBOL}/{TF}/`` and the file's
    timestamp suffix) into ``n_splits`` consecutive folds and reports the
    **out-of-sample** hit-rate per family as ``mean ± std`` across folds.

    Returns a dict::

        {
            "n_splits": int,
            "n_files_total": int,
            "per_family": {
                "<family>": {
                    "cv_hr_mean": float,
                    "cv_hr_std": float,
                    "cv_hr_folds": [float, ...],
                    "fold_event_counts": [int, ...],
                },
                ...
            },
        }

    The function is purely additive — it does not mutate ``CalibrationResult``
    and does not change the existing gate behaviour. Operators can call this
    alongside ``calibrate_from_benchmark`` to get a CV-aware sanity check.

    See: ``docs/TEMPORAL_NUMERICAL_IMPROVEMENT_PLAN_2026-04-24.md`` (S-1).
    """
    if n_splits < 2:
        raise ValueError("n_splits must be >= 2 for walk-forward CV")

    files = sorted(benchmark_dir.rglob("scoring_*.json"))
    n_files = len(files)
    if n_files < n_splits:
        raise ValueError(
            f"need at least n_splits={n_splits} scoring files, got {n_files}"
        )

    fold_size = n_files // n_splits
    families_seen: set[str] = set()
    per_fold_hr: dict[str, list[float]] = {}
    per_fold_n: dict[str, list[int]] = {}

    for fold_idx in range(n_splits):
        start = fold_idx * fold_size
        end = (fold_idx + 1) * fold_size if fold_idx < n_splits - 1 else n_files
        test_files = files[start:end]
        if not test_files:
            continue
        fold_stats = _aggregate_scoring_files(test_files)
        for family, s in fold_stats.items():
            families_seen.add(family)
            per_fold_hr.setdefault(family, []).append(s.weighted_hit_rate)
            per_fold_n.setdefault(family, []).append(s.total_events)

    per_family: dict[str, dict[str, Any]] = {}
    for family in sorted(families_seen):
        hrs = per_fold_hr.get(family, [])
        ns = per_fold_n.get(family, [])
        if not hrs:
            continue
        mean = sum(hrs) / len(hrs)
        if len(hrs) > 1:
            variance = sum((hr - mean) ** 2 for hr in hrs) / (len(hrs) - 1)
            std = math.sqrt(variance)
        else:
            std = 0.0
        per_family[family] = {
            "cv_hr_mean": round(mean, 4),
            "cv_hr_std": round(std, 4),
            "cv_hr_folds": [round(hr, 4) for hr in hrs],
            "fold_event_counts": ns,
        }

    return {
        "n_splits": n_splits,
        "n_files_total": n_files,
        "per_family": per_family,
    }


def calibrate_weights(
    stats: dict[str, FamilyStats],
    *,
    smoothing: float = 0.3,
) -> dict[str, float]:
    """Compute calibrated family weights from aggregated stats.

    Uses a Bayesian-style blend:
        calibrated = (1 - smoothing) × observed_hit_rate + smoothing × prior

    where ``prior`` is the hand-tuned default weight.  This prevents
    wild swings from small sample sizes while allowing the data to
    gradually pull the weights.

    Parameters
    ----------
    smoothing:
        Prior weight (0 = pure data, 1 = pure hand-tuned).
    """
    calibrated: dict[str, float] = {}

    for family in ("OB", "FVG", "BOS", "SWEEP"):
        prior = _DEFAULT_FAMILY_WEIGHTS.get(family, 0.50)

        if family in stats and stats[family].total_events >= 5:
            observed = stats[family].weighted_hit_rate
            blended = (1.0 - smoothing) * observed + smoothing * prior
        else:
            # Not enough data — keep prior
            blended = prior

        calibrated[family] = round(max(0.0, min(1.0, blended)), 4)

    return calibrated


def calibrate_rank_thresholds(
    stats: dict[str, FamilyStats],
) -> dict[str, int]:
    """Optionally recalibrate rank thresholds based on score distribution.

    For now returns the defaults — rank thresholds are policy decisions
    that should only change deliberately, not automatically.
    """
    return dict(_DEFAULT_RANK_THRESHOLDS)


def calibrate_from_benchmark(
    benchmark_dir: Path,
    *,
    smoothing: float = 0.3,
    cv_n_splits: int = 5,
) -> CalibrationResult:
    """End-to-end calibration: load → aggregate → calibrate.

    When the corpus contains at least ``cv_n_splits`` scoring files, an
    additive walk-forward CV block is attached to the result (audit S-1).
    The CV is **observational only**; it does not influence weights or
    thresholds — operators read it to detect overfitting drift.
    """
    stats = load_family_metrics(benchmark_dir)

    family_weights = calibrate_weights(stats, smoothing=smoothing)
    rank_thresholds = calibrate_rank_thresholds(stats)

    family_stats_out: dict[str, dict[str, Any]] = {}
    total_events = 0
    total_pairs = 0
    for family, s in sorted(stats.items()):
        family_stats_out[family] = {
            "total_events": s.total_events,
            "total_hits": s.total_hits,
            "pair_count": s.pair_count,
            "simple_hit_rate": round(s.simple_hit_rate, 4),
            "weighted_hit_rate": round(s.weighted_hit_rate, 4),
            "prior_weight": _DEFAULT_FAMILY_WEIGHTS.get(family, 0.50),
            "calibrated_weight": family_weights.get(family, 0.50),
        }
        total_events += s.total_events
        total_pairs += s.pair_count

    walk_forward_cv: dict[str, Any] | None = None
    try:
        walk_forward_cv = compute_walk_forward_cv_hr(
            benchmark_dir, n_splits=cv_n_splits
        )
    except ValueError:
        # Corpus too small for the requested fold count — skip silently;
        # the field is documented as optional.
        walk_forward_cv = None

    return CalibrationResult(
        family_weights=family_weights,
        rank_thresholds=rank_thresholds,
        family_stats=family_stats_out,
        total_events=total_events,
        total_pairs=total_pairs,
        source_dir=str(benchmark_dir),
        walk_forward_cv=walk_forward_cv,
    )


def render_calibration_report(cal: CalibrationResult) -> str:
    """Render a Markdown calibration report."""
    lines: list[str] = [
        "# Zone Priority Calibration Report",
        "",
        f"**Source:** `{cal.source_dir}`  ",
        f"**Total events:** {cal.total_events}  ",
        f"**Pairs contributing:** {cal.total_pairs}",
        "",
        "## Family Weights",
        "",
        "| Family | Prior | Observed Hit Rate | Calibrated | Δ |",
        "|--------|------:|------------------:|-----------:|--:|",
    ]

    for family in ("OB", "FVG", "BOS", "SWEEP"):
        fs = cal.family_stats.get(family, {})
        prior = fs.get("prior_weight", _DEFAULT_FAMILY_WEIGHTS.get(family, 0.50))
        observed = fs.get("weighted_hit_rate", 0.0)
        calibrated = cal.family_weights.get(family, prior)
        delta = calibrated - prior
        sign = "+" if delta >= 0 else ""
        lines.append(
            f"| {family} | {prior:.2f} | {observed:.4f} | "
            f"{calibrated:.4f} | {sign}{delta:.4f} |"
        )

    lines.extend([
        "",
        "## Per-Family Detail",
        "",
        "| Family | Events | Hits | Pairs | Simple HR | Weighted HR |",
        "|--------|-------:|-----:|------:|----------:|------------:|",
    ])

    for family in ("OB", "FVG", "BOS", "SWEEP"):
        fs = cal.family_stats.get(family, {})
        lines.append(
            f"| {family} | {fs.get('total_events', 0)} | "
            f"{fs.get('total_hits', 0)} | {fs.get('pair_count', 0)} | "
            f"{fs.get('simple_hit_rate', 0.0):.4f} | "
            f"{fs.get('weighted_hit_rate', 0.0):.4f} |"
        )

    lines.extend([
        "",
        "## Rank Thresholds (unchanged)",
        "",
        "| Rank | Min Score |",
        "|------|----------:|",
    ])
    for rank in ("A", "B", "C"):
        lines.append(f"| {rank} | {cal.rank_thresholds[rank]} |")
    lines.append("| D | 0 |")
    lines.append("")

    return "\n".join(lines)


def to_json(
    cal: CalibrationResult,
    *,
    frozen_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialize the calibration result for persistence.

    When ``frozen_provenance`` is supplied, it is attached under the
    ``frozen_provenance`` key. The block is purely additive metadata —
    no existing consumer reads it, but it makes the artifact
    self-auditable (corpus hash, source commit, generation time, etc.).
    """
    payload: dict[str, Any] = {
        "family_weights": cal.family_weights,
        "rank_thresholds": cal.rank_thresholds,
        "family_stats": cal.family_stats,
        "total_events": cal.total_events,
        "total_pairs": cal.total_pairs,
        "source_dir": cal.source_dir,
    }
    if cal.walk_forward_cv is not None:
        payload["walk_forward_cv"] = cal.walk_forward_cv
    if frozen_provenance is not None:
        payload["frozen_provenance"] = frozen_provenance
    return payload


# ── H3: Calibration history feed ────────────────────────────────


_HISTORY_RETENTION = 50  # keep the last N entries (rolling window)


def append_history_entry(
    output_path: Path,
    *,
    cal: CalibrationResult,
    testable: dict[str, Any] | None = None,
    history_filename: str = "zone_priority_calibration_history.jsonl",
) -> Path:
    """Append a compact calibration record to the rolling history JSONL.

    The Pine consumer (:func:`smc_zone_priority_consumer.compute_calibration_trend`)
    reads the last few entries to classify the trajectory as
    IMPROVING / STABLE / DEGRADING. Each entry is one JSON line so
    multiple runs can append without collision.

    The retention window keeps the file from growing unboundedly. We
    rewrite the file in-place when truncation is needed, which is
    safe because the file is only consumed by single-reader pipelines.
    """
    history_path = output_path.with_name(history_filename)
    history_path.parent.mkdir(parents=True, exist_ok=True)

    # Compute the corpus-level weighted hit rate from family stats so
    # the trend formula matches what the dashboard surfaces. Skip
    # families with no events to avoid div-by-zero distortion.
    total_events = 0
    total_hits = 0
    for fam_stats in cal.family_stats.values():
        n = int(fam_stats.get("total_events", 0) or 0)
        h = int(fam_stats.get("total_hits", 0) or 0)
        if n > 0:
            total_events += n
            total_hits += h
    weighted_hr = (total_hits / total_events) if total_events > 0 else 0.0

    entry: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "weighted_hit_rate": round(weighted_hr, 6),
        "total_events": total_events,
        "family_weights": dict(cal.family_weights),
        "family_stats": dict(cal.family_stats),
        "source_dir": cal.source_dir,
    }
    # Surface smECE so trend consumers can also reason about drift.
    if testable and "smooth_ece" in testable:
        entry["smooth_ece"] = testable["smooth_ece"]

    # Read existing entries, append, truncate to retention window.
    existing: list[dict[str, Any]] = []
    if history_path.exists():
        for line in history_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                existing.append(json.loads(line))
            except json.JSONDecodeError:
                # Skip corrupt lines — a future entry will overwrite.
                continue

    existing.append(entry)
    if len(existing) > _HISTORY_RETENTION:
        existing = existing[-_HISTORY_RETENTION:]

    atomic_write_text("\n".join(json.dumps(e) for e in existing) + "\n", history_path)
    return history_path


def load_history_entries(
    output_path: Path,
    *,
    limit: int | None = None,
    history_filename: str = "zone_priority_calibration_history.jsonl",
) -> list[dict[str, Any]]:
    """Load the rolling history alongside ``output_path``.

    Returns the entries oldest → newest (matching what the Pine
    consumer's :func:`compute_calibration_trend` expects). When
    ``limit`` is set, only the last ``limit`` entries are returned.
    Missing or unreadable files yield ``[]``.
    """
    history_path = output_path.with_name(history_filename)
    if not history_path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in history_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if limit is not None and limit > 0:
        entries = entries[-limit:]
    return entries


# ── F1: Testable calibration aggregate (smECE alongside ECE) ────


def collect_calibration_arrays(
    benchmark_dir: Path,
) -> tuple[list[float], list[int]]:
    """Reconstruct (predictions, outcomes) arrays from binned calibration in
    every ``scoring_*.json`` artifact.

    Each bin entry exposes ``predicted_mean``, ``observed_rate`` and
    ``n_events``.  We expand to one (pred, outcome) per event: the
    predicted mean is repeated, and the observed positives/negatives are
    materialised as integer 0/1 outcomes.  This yields a corpus-level
    array suitable for both ECE (binned) and smECE (kernel) without
    requiring per-event scoring artifacts.
    """
    preds: list[float] = []
    outs: list[int] = []
    for scoring_file in sorted(benchmark_dir.rglob("scoring_*.json")):
        try:
            data = json.loads(scoring_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        bins = (data.get("calibration") or {}).get("bins") or []
        for b in bins:
            n = int(b.get("n_events", 0) or 0)
            if n <= 0:
                continue
            p_raw = b.get("predicted_mean")
            r_raw = b.get("observed_rate")
            if p_raw is None or r_raw is None:
                continue
            try:
                p = float(p_raw)
                r = float(r_raw)
            except (TypeError, ValueError):
                continue
            if not (0.0 <= p <= 1.0) or not (0.0 <= r <= 1.0):
                continue
            positives = round(r * n)
            positives = max(0, min(n, positives))
            negatives = n - positives
            preds.extend([p] * n)
            outs.extend([1] * positives)
            outs.extend([0] * negatives)
    return preds, outs


def compute_testable_calibration(
    benchmark_dir: Path,
) -> dict[str, Any]:
    """Compute corpus-level ECE + smECE + dCE on the reconstructed arrays.

    The smECE figure is the *testable* calibration metric advocated by
    Błasiok & Nakkiran (2023) and is the F1 promotion-gate input.  All
    three are reported so reviewers can spot grid-sensitivity drift in
    the classical ECE.  Returns ``{}`` if no usable bins were found.
    """
    preds, outs = collect_calibration_arrays(benchmark_dir)
    if not preds:
        return {}

    # Local import keeps the script importable without smc_core on path
    # in environments that only need the family-weight aggregator.
    try:
        from smc_core.calibration_metrics import dce, ece, smooth_ece
    except ImportError:
        # When invoked as a CLI (python scripts/smc_zone_priority_calibration.py …)
        # sys.path[0] is the scripts/ dir, so smc_core is not resolvable.
        # Retry with the project root prepended.
        import sys
        project_root = str(Path(__file__).resolve().parent.parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        try:
            from smc_core.calibration_metrics import dce, ece, smooth_ece
        except ImportError:
            return {"n_events": len(preds), "error": "smc_core.calibration_metrics unavailable"}

    return {
        "n_events": len(preds),
        "positive_rate": round(sum(outs) / len(outs), 6),
        "ece_binned_n10": round(ece(preds, outs, n_bins=10), 6),
        "smooth_ece": round(smooth_ece(preds, outs), 6),
        "dce_upper_bound": round(dce(preds, outs), 6),
        "method": "binned_aggregate_reconstruction",
        "source": "calibration.bins per scoring_*.json",
    }


# ── F3 follow-on: per-bucket testable calibration (smECE) ──────


def collect_calibration_arrays_per_bucket(
    benchmark_dir: Path,
) -> dict[str, tuple[list[float], list[int]]]:
    """Reconstruct ``(preds, outs)`` arrays separately for each
    ``"<dimension>:<bucket>"`` group surfaced in
    ``stratified_calibration[<dim>].groups[<bucket>].bins``.

    Mirrors :func:`collect_calibration_arrays` but stratifies the corpus
    so each context bucket can be measured independently. Empty / invalid
    bins are skipped silently. Returned dict order is deterministic
    (sorted by ``"<dim>:<bucket>"`` key).
    """
    per_bucket: dict[str, tuple[list[float], list[int]]] = {}

    for scoring_file in sorted(benchmark_dir.rglob("scoring_*.json")):
        try:
            data = json.loads(scoring_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        stratified = data.get("stratified_calibration") or {}
        if not isinstance(stratified, dict):
            continue

        for dim, dim_payload in stratified.items():
            if not isinstance(dim_payload, dict):
                continue
            groups = dim_payload.get("groups") or {}
            if not isinstance(groups, dict):
                continue

            for bucket, bucket_payload in groups.items():
                if not isinstance(bucket_payload, dict):
                    continue
                bins = bucket_payload.get("bins") or []
                if not bins:
                    continue

                key = f"{dim}:{bucket}"
                preds, outs = per_bucket.setdefault(key, ([], []))
                for b in bins:
                    n = int(b.get("n_events", 0) or 0)
                    if n <= 0:
                        continue
                    p_raw = b.get("predicted_mean")
                    r_raw = b.get("observed_rate")
                    if p_raw is None or r_raw is None:
                        continue
                    try:
                        p = float(p_raw)
                        r = float(r_raw)
                    except (TypeError, ValueError):
                        continue
                    if not (0.0 <= p <= 1.0) or not (0.0 <= r <= 1.0):
                        continue
                    positives = max(0, min(n, round(r * n)))
                    preds.extend([p] * n)
                    outs.extend([1] * positives)
                    outs.extend([0] * (n - positives))

    return {k: per_bucket[k] for k in sorted(per_bucket)}


def compute_per_bucket_testable_calibration(
    benchmark_dir: Path,
    *,
    min_events: int = 30,
) -> dict[str, dict[str, Any]]:
    """Compute smECE / ECE / dCE per ``"<dim>:<bucket>"`` group.

    Buckets with fewer than ``min_events`` reconstructed events are
    flagged with ``status='insufficient_events'`` and have no metric
    fields — matching the F1 promotion-gate threshold so the report
    is directly comparable. Returns ``{}`` when no usable bins exist
    in the corpus.
    """
    arrays = collect_calibration_arrays_per_bucket(benchmark_dir)
    if not arrays:
        return {}

    # Same lazy import dance as compute_testable_calibration.
    try:
        from smc_core.calibration_metrics import dce, ece, smooth_ece
    except ImportError:
        import sys
        project_root = str(Path(__file__).resolve().parent.parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        try:
            from smc_core.calibration_metrics import dce, ece, smooth_ece
        except ImportError:
            return {
                key: {
                    "n_events": len(preds),
                    "status": "metrics_unavailable",
                }
                for key, (preds, _outs) in arrays.items()
            }

    out: dict[str, dict[str, Any]] = {}
    for key, (preds, outs) in arrays.items():
        n = len(preds)
        if n < min_events:
            out[key] = {
                "n_events": n,
                "status": "insufficient_events",
                "min_events": min_events,
            }
            continue

        out[key] = {
            "n_events": n,
            "positive_rate": round(sum(outs) / n, 6),
            "ece_binned_n10": round(ece(preds, outs, n_bins=10), 6),
            "smooth_ece": round(smooth_ece(preds, outs), 6),
            "dce_upper_bound": round(dce(preds, outs), 6),
            "status": "ok",
        }
    return out


# ── F1: Contextual calibration pipeline ─────────────────────────


def load_stratified_family_metrics(
    benchmark_dir: Path,
) -> dict[str, ContextBucketStats]:
    """Walk benchmark artifacts and aggregate stratified per-bucket, per-family KPIs.

    Returns ``{context_key: ContextBucketStats}`` where ``context_key`` is
    e.g. ``"session:RTH"`` or ``"vol_regime:HIGH_VOL"``.
    """
    buckets: dict[str, ContextBucketStats] = {}

    for bench_file in sorted(benchmark_dir.rglob("benchmark_*.json")):
        try:
            data = json.loads(bench_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        stratified = data.get("stratified", {})
        if not stratified:
            continue

        for context_key, kpi_list in stratified.items():
            if not isinstance(kpi_list, list):
                continue

            if context_key not in buckets:
                buckets[context_key] = ContextBucketStats(context_key=context_key)

            bucket = buckets[context_key]
            for kpi in kpi_list:
                family = kpi.get("family", "")
                n = int(kpi.get("n_events", 0))
                hr = kpi.get("hit_rate")
                if n == 0 or hr is None or family not in _FAMILIES:
                    continue
                hr = float(hr)
                if math.isnan(hr):
                    continue

                if family not in bucket.family_stats:
                    bucket.family_stats[family] = FamilyStats(family=family)

                s = bucket.family_stats[family]
                s.total_events += n
                s.total_hits += round(hr * n)
                s.pair_count += 1
                s.hit_rates.append(hr)
                s.weights.append(n)

    return buckets


def calibrate_contextual_weights(
    bucket_stats: dict[str, ContextBucketStats],
    global_weights: dict[str, float],
    *,
    smoothing: float = 0.3,
    min_events: int = _MIN_BUCKET_EVENTS,
) -> ContextualCalibrationResult:
    """Produce per-context-bucket family weights where data is sufficient.

    Buckets with fewer than ``min_events`` per family fall back to the
    global calibrated weight.
    """
    contextual_weights: dict[str, dict[str, dict[str, float]]] = {}
    promoted: list[str] = []
    detail: dict[str, dict[str, dict[str, Any]]] = {}

    for context_key, cbs in sorted(bucket_stats.items()):
        parts = context_key.split(":", 1)
        if len(parts) != 2:
            continue
        dimension, bucket = parts[0], parts[1]

        if dimension not in contextual_weights:
            contextual_weights[dimension] = {}

        bucket_weights: dict[str, float] = {}
        bucket_detail: dict[str, dict[str, Any]] = {}

        any_promoted = False
        for family in _FAMILIES:
            prior = global_weights.get(family, _DEFAULT_FAMILY_WEIGHTS.get(family, 0.50))
            fs = cbs.family_stats.get(family)

            if fs is not None and fs.total_events >= min_events:
                observed = fs.weighted_hit_rate
                blended = (1.0 - smoothing) * observed + smoothing * prior
                calibrated = round(max(0.0, min(1.0, blended)), 4)
                bucket_weights[family] = calibrated
                any_promoted = True
                bucket_detail[family] = {
                    "total_events": fs.total_events,
                    "observed_hit_rate": round(observed, 4),
                    "calibrated_weight": calibrated,
                    "global_weight": prior,
                    "promoted": True,
                }
            else:
                bucket_weights[family] = prior
                n = fs.total_events if fs else 0
                bucket_detail[family] = {
                    "total_events": n,
                    "observed_hit_rate": round(fs.weighted_hit_rate, 4) if fs and fs.total_events > 0 else None,
                    "calibrated_weight": prior,
                    "global_weight": prior,
                    "promoted": False,
                }

        contextual_weights[dimension][bucket] = bucket_weights
        if dimension not in detail:
            detail[dimension] = {}
        detail[dimension][bucket] = bucket_detail

        if any_promoted:
            promoted.append(context_key)

    return ContextualCalibrationResult(
        contextual_weights=contextual_weights,
        promoted_buckets=promoted,
        global_weights=global_weights,
        bucket_stats=detail,
        min_bucket_events=min_events,
    )


def check_contextual_promotion(
    ctx_cal: ContextualCalibrationResult,
    *,
    brier_improvement_threshold: float = _BRIER_IMPROVEMENT_THRESHOLD,
) -> list[str]:
    """Return human-readable summary of which buckets were promoted.

    This function reports which context buckets have sufficient data
    and diverge meaningfully from the global weight (> threshold).
    """
    summaries: list[str] = []
    for context_key in sorted(ctx_cal.promoted_buckets):
        parts = context_key.split(":", 1)
        if len(parts) != 2:
            continue
        dimension, bucket = parts

        bucket_w = ctx_cal.contextual_weights.get(dimension, {}).get(bucket, {})
        diffs: list[str] = []
        for family in _FAMILIES:
            cw = bucket_w.get(family, 0.0)
            gw = ctx_cal.global_weights.get(family, 0.0)
            delta = cw - gw
            if abs(delta) >= brier_improvement_threshold:
                sign = "+" if delta >= 0 else ""
                diffs.append(f"{family} {sign}{delta:.4f}")

        if diffs:
            summaries.append(f"{context_key}: {', '.join(diffs)}")

    return summaries


def contextual_to_json(
    ctx_cal: ContextualCalibrationResult,
    *,
    frozen_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialize contextual calibration for persistence.

    When ``frozen_provenance`` is supplied, it is attached under the
    ``frozen_provenance`` key (purely additive metadata; consumers do
    not read it).
    """
    payload: dict[str, Any] = {
        "contextual_weights": ctx_cal.contextual_weights,
        "promoted_buckets": ctx_cal.promoted_buckets,
        "global_weights": ctx_cal.global_weights,
        "bucket_stats": ctx_cal.bucket_stats,
        "min_bucket_events": ctx_cal.min_bucket_events,
    }
    if frozen_provenance is not None:
        payload["frozen_provenance"] = frozen_provenance
    return payload


def resolve_contextual_weight(
    ctx_cal: ContextualCalibrationResult | None,
    family: str,
    *,
    session_context: str | None = None,
    vol_regime: str | None = None,
) -> float:
    """Resolve the best available calibrated weight for a family.

    Lookup chain:
      1. Session-specific weight (if ``session_context`` provided and promoted)
      2. Vol-regime-specific weight (if ``vol_regime`` provided and promoted)
      3. Global calibrated weight
      4. Hand-tuned default

    Only uses promoted buckets — unpromoted contexts fall through to global.
    """
    if ctx_cal is None:
        return _DEFAULT_FAMILY_WEIGHTS.get(family, 0.50)

    # Session-specific
    if session_context:
        session_key = f"session:{session_context.upper()}"
        if session_key in ctx_cal.promoted_buckets:
            session_w = ctx_cal.contextual_weights.get("session", {}).get(session_context.upper(), {})
            if family in session_w:
                return session_w[family]

    # Vol-regime-specific
    if vol_regime:
        vol_key = f"vol_regime:{vol_regime.upper()}"
        if vol_key in ctx_cal.promoted_buckets:
            vol_w = ctx_cal.contextual_weights.get("vol_regime", {}).get(vol_regime.upper(), {})
            if family in vol_w:
                return vol_w[family]

    return ctx_cal.global_weights.get(family, _DEFAULT_FAMILY_WEIGHTS.get(family, 0.50))


def check_drift(
    cal: CalibrationResult,
    *,
    max_drift: float = 0.15,
) -> list[str]:
    """Return a list of drift-violation messages.

    A violation occurs when ``|calibrated - prior| > max_drift``
    for any family.
    """
    violations: list[str] = []
    for family in ("OB", "FVG", "BOS", "SWEEP"):
        prior = _DEFAULT_FAMILY_WEIGHTS.get(family, 0.50)
        calibrated = cal.family_weights.get(family, prior)
        delta = abs(calibrated - prior)
        if delta > max_drift:
            violations.append(
                f"{family}: drift {delta:.4f} exceeds threshold {max_drift:.2f} "
                f"(prior={prior:.2f}, calibrated={calibrated:.4f})"
            )
    return violations


# ── F2 frozen-artifact provenance (PR #43) ───────────────────────


def _sha256_of_file(path: Path) -> str:
    """Return the hex-encoded SHA-256 digest of a file's contents."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_rev(repo_root: Path) -> str | None:
    """Return the current git HEAD commit SHA, or ``None`` if unavailable."""
    try:
        git_exe = shutil.which("git") or "git"
        out = subprocess.run(  # noqa: S603 -- hardcoded git argv resolved via shutil.which (no shell, no user input)
            [git_exe, "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None
    sha = out.stdout.strip()
    return sha or None


def build_frozen_provenance(
    *,
    benchmark_dir: Path,
    status: str,
    frozen_at: str,
    smoothing: float,
    min_events_per_bucket: int,
    corpus_manifest_hash: str | None = None,
    generator_script_path: Path | None = None,
    repo_root: Path | None = None,
    n_events: int | None = None,
    max_event_timestamp_utc: str | None = None,
) -> dict[str, Any]:
    """Build the ``frozen_provenance`` block written into both calibration JSONs.

    The block is self-auditable: an operator can re-derive the same
    artifact by checking out ``source_commit`` and running the script
    against a corpus whose ``benchmark_run_manifest.json`` SHA-256
    matches ``benchmark_manifest_sha256``.

    All fields except ``benchmark_dir``, ``status``, ``frozen_at``,
    ``smoothing`` and ``min_events_per_bucket`` are best-effort:
    missing values are recorded as ``None`` rather than raising.
    """
    if status not in {"shadow", "production"}:
        raise ValueError(
            f"frozen status must be 'shadow' or 'production', got {status!r}"
        )

    manifest_path = benchmark_dir / "benchmark_run_manifest.json"
    manifest_sha = corpus_manifest_hash
    if manifest_sha is None and manifest_path.is_file():
        manifest_sha = _sha256_of_file(manifest_path)

    script_sha: str | None = None
    if generator_script_path is None:
        generator_script_path = Path(__file__).resolve()
    if generator_script_path.is_file():
        script_sha = _sha256_of_file(generator_script_path)

    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent
    source_commit = _git_rev(repo_root)

    return {
        "frozen": True,
        "status": status,
        "frozen_at": frozen_at,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "benchmark_dir": str(benchmark_dir),
        "benchmark_corpus_ephemeral": True,
        "benchmark_manifest_sha256": manifest_sha,
        "n_events": n_events,
        "max_event_timestamp_utc": max_event_timestamp_utc,
        "source_commit": source_commit,
        "generator_script_path": str(generator_script_path.name),
        "generator_script_sha256": script_sha,
        "smoothing": smoothing,
        "min_events_per_bucket": min_events_per_bucket,
        "regeneration_instructions": (
            "docs/f2_contextual_promotion_decision_2026-04-21.md"
            "#regeneration-recipe"
        ),
    }


def main(argv: list[str] | None = None) -> None:
    import argparse

    # S-3: defense-in-depth — set Python + NumPy seeds before any pipeline op.
    random.seed(_CALIBRATION_RANDOM_SEED)
    try:
        import numpy as _np  # local import to keep module-level NumPy optional

        _np.random.seed(_CALIBRATION_RANDOM_SEED)
    except ImportError:  # pragma: no cover - NumPy is a hard dep elsewhere
        pass

    parser = argparse.ArgumentParser(description="Calibrate zone priority weights from benchmark data")
    parser.add_argument(
        "--benchmark-dir",
        type=Path,
        default=Path("artifacts/ci/measurement_benchmark"),
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=Path("artifacts/reports/zone_priority_calibration.json"),
    )
    parser.add_argument("--smoothing", type=float, default=0.3)
    parser.add_argument(
        "--check-drift",
        type=float,
        metavar="MAX_DRIFT",
        default=None,
        help="Fail with exit code 1 if any family weight drifts more than MAX_DRIFT from prior",
    )

    # ── F2 frozen-artifact controls (PR #43) ────────────────────
    parser.add_argument(
        "--frozen",
        action="store_true",
        help=(
            "Mark this run as producing a frozen calibration artifact; "
            "writes a `frozen_provenance` block into both JSON outputs."
        ),
    )
    parser.add_argument(
        "--frozen-at",
        type=str,
        default=None,
        metavar="ISO_TIMESTAMP",
        help=(
            "UTC timestamp recorded in `frozen_provenance.frozen_at`. "
            "Defaults to the current UTC time when --frozen is set."
        ),
    )
    parser.add_argument(
        "--status",
        choices=("shadow", "production"),
        default="shadow",
        help=(
            "Lifecycle stage recorded in `frozen_provenance.status` "
            "(default: shadow). Only meaningful with --frozen."
        ),
    )
    parser.add_argument(
        "--contextual-output-path",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Override the contextual sibling output path. "
            "Defaults to `<output-path>/../zone_priority_contextual_calibration.json`."
        ),
    )
    parser.add_argument(
        "--corpus-manifest-hash",
        type=str,
        default=None,
        metavar="SHA256",
        help=(
            "Pre-computed SHA-256 of the benchmark `benchmark_run_manifest.json`. "
            "If omitted and --frozen is set, the hash is computed from disk."
        ),
    )
    args = parser.parse_args(argv)

    cal = calibrate_from_benchmark(args.benchmark_dir, smoothing=args.smoothing)

    # ── F2 frozen-artifact provenance (PR #43) ───────────────────
    frozen_provenance: dict[str, Any] | None = None
    if args.frozen:
        frozen_at = args.frozen_at or datetime.now(UTC).isoformat(timespec="seconds")
        frozen_provenance = build_frozen_provenance(
            benchmark_dir=args.benchmark_dir,
            status=args.status,
            frozen_at=frozen_at,
            smoothing=args.smoothing,
            min_events_per_bucket=_MIN_BUCKET_EVENTS,
            corpus_manifest_hash=args.corpus_manifest_hash,
            n_events=cal.total_events or None,
        )

    # F1: testable calibration (smECE alongside binned ECE) on the corpus.
    testable = compute_testable_calibration(args.benchmark_dir)

    # Write JSON
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = to_json(cal, frozen_provenance=frozen_provenance)
    if testable:
        payload["testable_calibration"] = testable
    atomic_write_text(json.dumps(payload, indent=2) + "\n", args.output_path)

    # H3 history feed — append a compact history entry alongside the
    # calibration JSON so consumers (Pine ZONE_CAL_TREND) can detect
    # IMPROVING / DEGRADING trajectories across runs.
    append_history_entry(args.output_path, cal=cal, testable=testable)

    # Write Markdown report alongside
    md_path = args.output_path.with_suffix(".md")
    atomic_write_text(render_calibration_report(cal), md_path)

    print(f"Calibration written to {args.output_path}")
    print(f"Report written to {md_path}")
    print()
    print("Calibrated family weights:")
    for fam, w in sorted(cal.family_weights.items()):
        prior = _DEFAULT_FAMILY_WEIGHTS.get(fam, 0.50)
        delta = w - prior
        sign = "+" if delta >= 0 else ""
        print(f"  {fam}: {prior:.2f} → {w:.4f} ({sign}{delta:.4f})")

    if testable:
        print()
        print("Testable calibration (F1):")
        print(f"  n_events    : {testable['n_events']}")
        if "ece_binned_n10" in testable:
            print(f"  ECE (n=10)  : {testable['ece_binned_n10']:.4f}")
            print(f"  smECE       : {testable['smooth_ece']:.4f}  "
                  "(Błasiok & Nakkiran 2023 — primary F1 gate)")
            print(f"  dCE (upper) : {testable['dce_upper_bound']:.4f}  "
                  "(Rossellini et al. 2025)")

    # ── Phase F: Contextual calibration ─────────────────────────
    bucket_stats = load_stratified_family_metrics(args.benchmark_dir)
    ctx_cal = calibrate_contextual_weights(
        bucket_stats, cal.family_weights, smoothing=args.smoothing,
    )
    if args.contextual_output_path is not None:
        ctx_path = args.contextual_output_path
        ctx_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        ctx_path = args.output_path.with_name("zone_priority_contextual_calibration.json")
    atomic_write_text(json.dumps(
            contextual_to_json(ctx_cal, frozen_provenance=frozen_provenance),
            indent=2,
        ) + "\n", ctx_path)
    print(f"\nContextual calibration written to {ctx_path}")

    promotions = check_contextual_promotion(ctx_cal)
    if promotions:
        print(f"Promoted buckets ({len(promotions)}):")
        for p in promotions:
            print(f"  ▸ {p}")
    else:
        print("No context buckets promoted (insufficient data or small deltas)")

    # ── F3 follow-on: per-bucket testable calibration (smECE) ──
    per_bucket = compute_per_bucket_testable_calibration(args.benchmark_dir)
    if per_bucket:
        per_bucket_path = args.output_path.with_name(
            "zone_priority_per_bucket_calibration.json"
        )
        atomic_write_text(json.dumps(per_bucket, indent=2) + "\n", per_bucket_path)
        print(f"\nPer-bucket testable calibration written to {per_bucket_path}")
        ok_buckets = [(k, v) for k, v in per_bucket.items() if v.get("status") == "ok"]
        skipped = [k for k, v in per_bucket.items() if v.get("status") != "ok"]
        if ok_buckets:
            print(f"Per-bucket smECE ({len(ok_buckets)} buckets >= 30 events):")
            for key, payload in ok_buckets:
                print(
                    f"  {key}: smECE={payload['smooth_ece']:.4f}  "
                    f"ECE={payload['ece_binned_n10']:.4f}  "
                    f"n={payload['n_events']}"
                )
        if skipped:
            print(f"Skipped {len(skipped)} bucket(s) with < 30 events")

    if args.check_drift is not None:
        violations = check_drift(cal, max_drift=args.check_drift)
        if violations:
            print()
            print(f"DRIFT CHECK FAILED (threshold={args.check_drift:.2f}):")
            for v in violations:
                print(f"  ✗ {v}")
            raise SystemExit(1)
        else:
            print(f"\nDrift check passed (threshold={args.check_drift:.2f})")


if __name__ == "__main__":
    main()
