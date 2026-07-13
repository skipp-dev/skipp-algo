"""Quantify SWEEP label censoring and symbol/timeframe dependence.

The measurement event ledger stores the final boolean outcome but not the
number of forward bars that were available when it was assigned.  The rolling
benchmark's ``scored_family_events.json`` carries those forward windows but
omits symbol/timeframe.  This study joins both artifacts through the canonical
SWEEP identity (anchor timestamp, side/direction, swept price), then reports:

* the share of events with fewer than the configured label-horizon bars;
* unresolved negative labels (a partial window with no hit yet);
* identified hit-rate bounds, treating those unresolved negatives as either
  all misses or all eventual hits instead of inventing a point correction;
* one-way symbol/timeframe intraclass correlations; and
* deterministic percentile bootstrap intervals under IID, symbol-cluster,
  timeframe-cluster, and two-way pigeonhole resampling.

This is an evidence tool, not a promotion gate.  A single corpus cannot prove
stationarity, and an identified interval is not an imputed outcome estimate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_json, atomic_write_text
from smc_core.event_ledger import read_event_ledger
from smc_core.label_horizons import LABEL_HORIZON_BARS
from smc_core.scoring import label_sweep_reversal

DEFAULT_BOOTSTRAP_REPLICATES = 2_000
DEFAULT_SEED = 35_870
DEFAULT_THRESHOLD_PCT = 0.005
CONFIRMATION_BARS = 3


@dataclass(frozen=True, slots=True)
class SweepObservation:
    symbol: str
    timeframe: str
    event_id: str
    timestamp: float
    side: str
    sweep_price: float
    ledger_outcome: bool
    forward_closes: tuple[float, ...]
    inferred_forward_timeframe: str | None = None

    @property
    def cluster_pair(self) -> str:
        return f"{self.symbol}/{self.timeframe}"


def _event_identity(event: dict[str, Any]) -> tuple[float, str, float] | None:
    if str(event.get("family", "")).upper() != "SWEEP":
        return None
    event_id = str(event.get("event_id", ""))
    parts = event_id.split(":")
    if len(parts) < 6 or parts[0].lower() != "sweep":
        return None
    side = parts[-2].strip().upper()
    if side not in {"SELL_SIDE", "BUY_SIDE"}:
        return None
    try:
        timestamp = float(event["timestamp"])
        price = float(parts[-1])
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(timestamp) and math.isfinite(price) and price > 0):
        return None
    return timestamp, side, price


def _family_identity(event: dict[str, Any]) -> tuple[float, str, float] | None:
    if str(event.get("family", "")).upper() != "SWEEP":
        return None
    direction = str(event.get("direction", "")).strip().upper()
    side = {"LONG": "SELL_SIDE", "SHORT": "BUY_SIDE"}.get(direction)
    if side is None:
        return None
    try:
        timestamp = float(event["anchor_ts"])
        price = float(event["entry_price"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(timestamp) and math.isfinite(price) and price > 0):
        return None
    return timestamp, side, price


def _identity_bucket(timestamp: float, side: str) -> tuple[float, str]:
    return round(timestamp, 6), side


def _infer_timeframe(family_event: dict[str, Any]) -> str | None:
    """Infer canonical TF from the FamilyEvent's real forward timestamps."""
    try:
        anchor = float(family_event["anchor_ts"])
        timestamps = [float(value) for value in family_event.get("forward_timestamps", [])]
    except (KeyError, TypeError, ValueError):
        return None
    points = [anchor, *timestamps]
    diffs = [right - left for left, right in pairwise(points) if right > left]
    if not diffs:
        return None
    median = statistics.median(diffs)
    seconds_to_tf = {
        300.0: "5m",
        600.0: "10m",
        900.0: "15m",
        1800.0: "30m",
        3600.0: "1H",
        14_400.0: "4H",
        86_400.0: "1D",
    }
    closest = min(seconds_to_tf, key=lambda seconds: abs(seconds - median))
    return seconds_to_tf[closest] if abs(closest - median) <= closest * 0.05 else None


def _family_payload_signature(
    closes: tuple[float, ...], family_event: dict[str, Any]
) -> tuple[tuple[float, ...], tuple[float, ...]] | None:
    try:
        timestamps = tuple(float(value) for value in family_event.get("forward_timestamps", []))
    except (TypeError, ValueError):
        return None
    if any(not math.isfinite(value) for value in timestamps):
        return None
    return closes, timestamps


def read_sweep_ledger_events(benchmark_dir: Path) -> tuple[list[dict[str, Any]], list[Path]]:
    paths = sorted(benchmark_dir.glob("*/*/events_*.jsonl"))
    events: list[dict[str, Any]] = []
    for path in paths:
        events.extend(read_event_ledger(path, strict=True))
    return [event for event in events if str(event.get("family", "")).upper() == "SWEEP"], paths


def read_family_events(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path}: expected a JSON list")
    return [event for event in payload if isinstance(event, dict) and str(event.get("family", "")).upper() == "SWEEP"]


def join_sweep_observations(
    ledger_events: Sequence[dict[str, Any]],
    family_events: Sequence[dict[str, Any]],
) -> tuple[list[SweepObservation], dict[str, int]]:
    ledger_index: dict[tuple[float, str], list[tuple[float, dict[str, Any]]]] = defaultdict(list)
    malformed_ledger = 0
    for event in ledger_events:
        identity = _event_identity(event)
        if identity is None or not isinstance(event.get("outcome"), bool):
            malformed_ledger += 1
            continue
        timestamp, side, price = identity
        ledger_index[_identity_bucket(timestamp, side)].append((price, event))

    prepared_families: dict[
        tuple[float, str, float],
        list[tuple[dict[str, Any], float, str, float, tuple[float, ...], str | None]],
    ] = defaultdict(list)
    malformed_family = 0
    for family in family_events:
        identity = _family_identity(family)
        closes_raw = family.get("forward_closes")
        if identity is None or not isinstance(closes_raw, list):
            malformed_family += 1
            continue
        timestamp, side, price = identity
        try:
            closes = tuple(float(value) for value in closes_raw)
        except (TypeError, ValueError):
            malformed_family += 1
            continue
        if any(not math.isfinite(value) for value in closes):
            malformed_family += 1
            continue
        prepared_families[(round(timestamp, 6), side, round(price, 8))].append(
            (family, timestamp, side, price, closes, _infer_timeframe(family))
        )

    joined: list[SweepObservation] = []
    unmatched = ambiguous = multiplicity_allocated = 0
    used_event_ids: set[str] = set()
    for family_group in prepared_families.values():
        _, timestamp, side, price, _, _ = family_group[0]
        candidates = [
            event
            for candidate_price, event in ledger_index.get(_identity_bucket(timestamp, side), [])
            if math.isclose(candidate_price, price, rel_tol=1e-10, abs_tol=0.0050001)
            and str(event.get("event_id", "")) not in used_event_ids
        ]
        if not candidates:
            unmatched += len(family_group)
            continue
        assignments: list[
            tuple[
                tuple[dict[str, Any], float, str, float, tuple[float, ...], str | None],
                dict[str, Any],
            ]
        ] = []
        if len(family_group) == 1:
            family_row = family_group[0]
            inferred_timeframe = family_row[-1]
            inferred_candidates = [
                event for event in candidates if str(event.get("timeframe", "")) == inferred_timeframe
            ]
            if len(inferred_candidates) == 1:
                assignments.append((family_row, inferred_candidates[0]))
            elif len(candidates) == 1:
                assignments.append((family_row, candidates[0]))
            else:
                ambiguous += 1
                continue
        else:
            signatures = {_family_payload_signature(row[4], row[0]) for row in family_group}
            if len(candidates) != len(family_group) or None in signatures or len(signatures) != 1:
                ambiguous += len(family_group)
                continue
            ordered_candidates = sorted(
                candidates,
                key=lambda event: (
                    str(event.get("timeframe", "")),
                    str(event.get("event_id", "")),
                ),
            )
            assignments.extend(zip(family_group, ordered_candidates, strict=True))
            multiplicity_allocated += len(assignments)

        for family_row, event in assignments:
            _, row_timestamp, row_side, row_price, closes, inferred_timeframe = family_row
            event_id = str(event["event_id"])
            used_event_ids.add(event_id)
            joined.append(
                SweepObservation(
                    symbol=str(event.get("symbol", "")).upper(),
                    timeframe=str(event.get("timeframe", "")),
                    event_id=event_id,
                    timestamp=row_timestamp,
                    side=row_side,
                    sweep_price=row_price,
                    ledger_outcome=bool(event["outcome"]),
                    forward_closes=closes,
                    inferred_forward_timeframe=inferred_timeframe,
                )
            )
    return joined, {
        "ledger_sweep_events": len(ledger_events),
        "family_sweep_events": len(family_events),
        "joined": len(joined),
        "unmatched_family_events": unmatched,
        "ambiguous_family_events": ambiguous,
        "multiplicity_allocated_family_events": multiplicity_allocated,
        "malformed_family_events": malformed_family,
        "malformed_ledger_events": malformed_ledger,
        "unmatched_ledger_events": max(0, len(ledger_events) - len(used_event_ids) - malformed_ledger),
    }


def _hit(observation: SweepObservation, closes: Sequence[float], threshold_pct: float) -> bool:
    return label_sweep_reversal(
        observation.sweep_price,
        observation.side,
        list(closes),
        threshold_pct=threshold_pct,
    )


def _raw_counts(
    observations: Sequence[SweepObservation],
    *,
    horizon_bars: int,
    threshold_pct: float,
    late: bool,
) -> dict[str, int]:
    n = len(observations)
    complete = hits = unresolved_negative = ledger_mismatch = 0
    for observation in observations:
        canonical_window = observation.forward_closes[:horizon_bars]
        closes = canonical_window[CONFIRMATION_BARS:] if late else canonical_window
        hit = _hit(observation, closes, threshold_pct)
        is_complete = len(observation.forward_closes) >= horizon_bars
        complete += int(is_complete)
        hits += int(hit)
        unresolved_negative += int(not is_complete and not hit)
        if not late:
            ledger_mismatch += int(hit != observation.ledger_outcome)
    return {
        "n": n,
        "complete": complete,
        "censored": n - complete,
        "hits_observed": hits,
        "unresolved_negative": unresolved_negative,
        "early_resolved_positive": (n - complete) - unresolved_negative,
        "ledger_outcome_mismatch": ledger_mismatch,
    }


def summarize_observations(
    observations: Sequence[SweepObservation],
    *,
    horizon_bars: int,
    threshold_pct: float,
) -> dict[str, Any]:
    def one(late: bool) -> dict[str, Any]:
        counts = _raw_counts(
            observations,
            horizon_bars=horizon_bars,
            threshold_pct=threshold_pct,
            late=late,
        )
        n = counts["n"]
        denominator = float(n) if n else 1.0
        lower = counts["hits_observed"] / denominator if n else None
        upper = (counts["hits_observed"] + counts["unresolved_negative"]) / denominator if n else None
        return {
            **counts,
            "censoring_rate": None if not n else round(counts["censored"] / denominator, 6),
            "unresolved_negative_rate": None if not n else round(counts["unresolved_negative"] / denominator, 6),
            "observed_hit_rate": None if lower is None else round(lower, 6),
            "identified_hit_rate_lower": None if lower is None else round(lower, 6),
            "identified_hit_rate_upper": None if upper is None else round(upper, 6),
            "max_downward_bias": (None if not n else round(counts["unresolved_negative"] / denominator, 6)),
        }

    return {"canonical": one(False), "late_window_bars_4_to_8": one(True)}


def timeframe_alignment_summary(
    observations: Sequence[SweepObservation],
) -> dict[str, Any]:
    matches = mismatches = unknown = 0
    mismatch_pairs: Counter[str] = Counter()
    by_timeframe: dict[str, Counter[str]] = defaultdict(Counter)
    for observation in observations:
        inferred = observation.inferred_forward_timeframe
        if inferred is None:
            status = "unknown"
            unknown += 1
        elif inferred == observation.timeframe:
            status = "match"
            matches += 1
        else:
            status = "mismatch"
            mismatches += 1
            mismatch_pairs[f"{observation.timeframe}->{inferred}"] += 1
        by_timeframe[observation.timeframe][status] += 1
    return {
        "n": len(observations),
        "matches": matches,
        "mismatches": mismatches,
        "unknown": unknown,
        "analysis_valid": bool(observations) and mismatches == 0 and unknown == 0,
        "mismatch_pairs": dict(sorted(mismatch_pairs.items())),
        "by_timeframe": {timeframe: dict(sorted(counts.items())) for timeframe, counts in sorted(by_timeframe.items())},
    }


def _quantile(values: Sequence[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    position = min(max(q, 0.0), 1.0) * (len(ordered) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    weight = position - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def _metric_vector(
    observations: Sequence[SweepObservation],
    *,
    horizon_bars: int,
    threshold_pct: float,
) -> dict[str, float]:
    summary = summarize_observations(
        observations,
        horizon_bars=horizon_bars,
        threshold_pct=threshold_pct,
    )
    out: dict[str, float] = {}
    for scope, metrics in summary.items():
        for key in (
            "censoring_rate",
            "unresolved_negative_rate",
            "observed_hit_rate",
            "identified_hit_rate_upper",
        ):
            value = metrics[key]
            if value is not None:
                out[f"{scope}.{key}"] = float(value)
    return out


def _resample_iid(observations: Sequence[SweepObservation], rng: random.Random) -> list[SweepObservation]:
    return [rng.choice(observations) for _ in observations]


def _resample_cluster(
    observations: Sequence[SweepObservation],
    rng: random.Random,
    key: Callable[[SweepObservation], str],
) -> list[SweepObservation]:
    groups: dict[str, list[SweepObservation]] = defaultdict(list)
    for observation in observations:
        groups[key(observation)].append(observation)
    labels = sorted(groups)
    return [item for _ in labels for item in groups[rng.choice(labels)]]


def _resample_two_way(observations: Sequence[SweepObservation], rng: random.Random) -> list[SweepObservation]:
    symbols = sorted({observation.symbol for observation in observations})
    timeframes = sorted({observation.timeframe for observation in observations})
    symbol_weight = Counter(rng.choice(symbols) for _ in symbols)
    timeframe_weight = Counter(rng.choice(timeframes) for _ in timeframes)
    out: list[SweepObservation] = []
    for observation in observations:
        weight = symbol_weight[observation.symbol] * timeframe_weight[observation.timeframe]
        out.extend([observation] * weight)
    return out


def bootstrap_intervals(
    observations: Sequence[SweepObservation],
    *,
    horizon_bars: int,
    threshold_pct: float,
    replicates: int,
    seed: int,
) -> dict[str, Any]:
    if not observations or replicates <= 0:
        return {}
    methods: dict[str, Callable[[Sequence[SweepObservation], random.Random], list[SweepObservation]]] = {
        "iid": _resample_iid,
        "symbol_cluster": lambda rows, rng: _resample_cluster(rows, rng, lambda row: row.symbol),
        "timeframe_cluster": lambda rows, rng: _resample_cluster(rows, rng, lambda row: row.timeframe),
        "symbol_timeframe_two_way": _resample_two_way,
    }
    result: dict[str, Any] = {}
    symbol_count = len({row.symbol for row in observations})
    timeframe_count = len({row.timeframe for row in observations})
    alignment = timeframe_alignment_summary(observations)
    for method_index, (name, resampler) in enumerate(methods.items()):
        cluster_count = (
            len({row.symbol for row in observations})
            if name == "symbol_cluster"
            else len({row.timeframe for row in observations})
            if name == "timeframe_cluster"
            else min(symbol_count, timeframe_count)
            if name == "symbol_timeframe_two_way"
            else len(observations)
        )
        if name in {"timeframe_cluster", "symbol_timeframe_two_way"} and not alignment["analysis_valid"]:
            result[name] = {
                "measured": False,
                "reason": "forward-window timeframe provenance is incomplete or mismatched",
                "cluster_count": cluster_count,
                "forward_window_alignment": {
                    "mismatches": alignment["mismatches"],
                    "unknown": alignment["unknown"],
                },
            }
            continue
        if name != "iid" and cluster_count < 2:
            result[name] = {
                "measured": False,
                "reason": "fewer than two resampling clusters",
                "cluster_count": cluster_count,
            }
            continue
        rng = random.Random(seed + method_index * 10_003)
        draws: dict[str, list[float]] = defaultdict(list)
        for _ in range(replicates):
            sample = resampler(observations, rng)
            if not sample:
                continue
            for metric, value in _metric_vector(
                sample,
                horizon_bars=horizon_bars,
                threshold_pct=threshold_pct,
            ).items():
                draws[metric].append(value)
        result[name] = {
            "measured": True,
            "cluster_count": cluster_count,
            "cluster_counts": (
                {"symbols": symbol_count, "timeframes": timeframe_count} if name == "symbol_timeframe_two_way" else None
            ),
            "replicates_requested": replicates,
            "replicates_used": min((len(values) for values in draws.values()), default=0),
            "confidence_level": 0.95,
            "intervals": {
                metric: {
                    "low": round(_quantile(values, 0.025), 6),
                    "high": round(_quantile(values, 0.975), 6),
                }
                for metric, values in sorted(draws.items())
            },
        }
    return result


def _intraclass_correlation(
    observations: Sequence[SweepObservation],
    values: Sequence[float],
    key: Callable[[SweepObservation], str],
) -> dict[str, Any]:
    groups: dict[str, list[float]] = defaultdict(list)
    for observation, value in zip(observations, values, strict=True):
        groups[key(observation)].append(float(value))
    nonempty = list(groups.values())
    n = sum(len(group) for group in nonempty)
    k = len(nonempty)
    if k < 2 or n <= k:
        return {"measured": False, "cluster_count": k, "reason": "insufficient replicated clusters"}
    grand = sum(sum(group) for group in nonempty) / n
    ss_between = sum(len(group) * ((sum(group) / len(group)) - grand) ** 2 for group in nonempty)
    ss_within = sum(sum((value - (sum(group) / len(group))) ** 2 for value in group) for group in nonempty)
    ms_between = ss_between / (k - 1)
    ms_within = ss_within / (n - k)
    n0 = (n - sum(len(group) ** 2 for group in nonempty) / n) / (k - 1)
    denominator = ms_between + (n0 - 1.0) * ms_within
    icc = (ms_between - ms_within) / denominator if abs(denominator) > 1e-15 else 0.0
    return {
        "measured": True,
        "cluster_count": k,
        "n": n,
        "mean_cluster_size": round(n / k, 6),
        "icc": round(max(-1.0, min(1.0, icc)), 6),
    }


def dependence_summary(
    observations: Sequence[SweepObservation],
    *,
    horizon_bars: int,
    threshold_pct: float,
) -> dict[str, Any]:
    indicators: dict[str, list[float]] = {
        "censored": [float(len(row.forward_closes) < horizon_bars) for row in observations],
        "canonical_hit": [float(_hit(row, row.forward_closes, threshold_pct)) for row in observations],
        "canonical_unresolved_negative": [
            float(len(row.forward_closes) < horizon_bars and not _hit(row, row.forward_closes, threshold_pct))
            for row in observations
        ],
    }
    alignment = timeframe_alignment_summary(observations)

    def timeframe_icc(values: Sequence[float]) -> dict[str, Any]:
        if not alignment["analysis_valid"]:
            return {
                "measured": False,
                "cluster_count": len({row.timeframe for row in observations}),
                "reason": "forward-window timeframe provenance is incomplete or mismatched",
                "forward_window_alignment": {
                    "mismatches": alignment["mismatches"],
                    "unknown": alignment["unknown"],
                },
            }
        return _intraclass_correlation(observations, values, lambda row: row.timeframe)

    return {
        indicator: {
            "by_symbol": _intraclass_correlation(observations, values, lambda row: row.symbol),
            "by_timeframe": timeframe_icc(values),
        }
        for indicator, values in indicators.items()
    }


def grouped_summaries(
    observations: Sequence[SweepObservation],
    *,
    horizon_bars: int,
    threshold_pct: float,
) -> dict[str, Any]:
    def grouped(key: Callable[[SweepObservation], str]) -> dict[str, Any]:
        buckets: dict[str, list[SweepObservation]] = defaultdict(list)
        for observation in observations:
            buckets[key(observation)].append(observation)
        return {
            label: summarize_observations(rows, horizon_bars=horizon_bars, threshold_pct=threshold_pct)
            for label, rows in sorted(buckets.items())
        }

    return {
        "by_symbol": grouped(lambda row: row.symbol),
        "by_timeframe": grouped(lambda row: row.timeframe),
        "by_symbol_timeframe": grouped(lambda row: row.cluster_pair),
    }


def _combined_sha256(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.name).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def shadow_feature_availability(ledger_events: Sequence[dict[str, Any]]) -> dict[str, int]:
    return {
        "sweep_trap_quality_score": sum(
            "sweep_trap_quality_score" in (event.get("features") or {}) for event in ledger_events
        ),
        "sweep_trap_outcome_late_boolean": sum(
            isinstance(
                (event.get("outcome_extras") or {}).get(
                    "sweep_trap_outcome_late",
                    (event.get("features") or {}).get("sweep_trap_outcome_late"),
                ),
                bool,
            )
            for event in ledger_events
        ),
        "reaction_schema_version": sum(
            "reaction_schema_version" in (event.get("features") or {}) for event in ledger_events
        ),
        "reaction_outcome_late_boolean": sum(
            isinstance(
                (event.get("outcome_extras") or {}).get(
                    "reaction_outcome_late",
                    (event.get("features") or {}).get("reaction_outcome_late"),
                ),
                bool,
            )
            for event in ledger_events
        ),
    }


def build_report(
    *,
    benchmark_dir: Path,
    family_events_path: Path,
    source_run_id: str,
    corpus_era_note: str,
    generated_at: str | None,
    horizon_bars: int,
    threshold_pct: float,
    bootstrap_replicates: int,
    seed: int,
) -> dict[str, Any]:
    ledger_events, ledger_paths = read_sweep_ledger_events(benchmark_dir)
    family_events = read_family_events(family_events_path)
    observations, join = join_sweep_observations(ledger_events, family_events)
    if not observations:
        raise ValueError("no SWEEP observations could be joined")
    alignment = timeframe_alignment_summary(observations)
    aligned_observations = [
        observation for observation in observations if observation.inferred_forward_timeframe == observation.timeframe
    ]
    limitations = [
        "Single workflow-run corpus; no stationarity claim.",
        "Identified hit-rate bounds are not an imputation model.",
        "Cluster bootstrap covers symbol/timeframe dependence, not serial dependence across runs.",
        "Shadow-feature Brier/lift intervals require ledgers emitted with the shadow flags enabled.",
    ]
    if not alignment["analysis_valid"]:
        limitations.append(
            "Timeframe ICC and timeframe/two-way bootstrap intervals are withheld because "
            "forward-window timestamps do not consistently match the ledger timeframe."
        )
        limitations.append(
            "The aligned-only sensitivity subset cannot recover cross-timeframe evidence; "
            "it only removes rows with invalid timeframe provenance."
        )
    return {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "source": {
            "workflow_run_id": source_run_id or None,
            "corpus_era_note": corpus_era_note or None,
            "benchmark_artifact": benchmark_dir.name,
            "ledger_file_count": len(ledger_paths),
            "ledger_sha256": _combined_sha256(ledger_paths),
            "family_events_file": family_events_path.name,
            "family_events_sha256": hashlib.sha256(family_events_path.read_bytes()).hexdigest(),
        },
        "config": {
            "horizon_bars": horizon_bars,
            "confirmation_bars": CONFIRMATION_BARS,
            "threshold_pct": threshold_pct,
            "bootstrap_replicates": bootstrap_replicates,
            "bootstrap_seed": seed,
        },
        "join": join,
        "forward_window_alignment": alignment,
        "shadow_feature_availability": shadow_feature_availability(ledger_events),
        "overall": summarize_observations(observations, horizon_bars=horizon_bars, threshold_pct=threshold_pct),
        "groups": grouped_summaries(observations, horizon_bars=horizon_bars, threshold_pct=threshold_pct),
        "dependence": dependence_summary(observations, horizon_bars=horizon_bars, threshold_pct=threshold_pct),
        "confidence_intervals": bootstrap_intervals(
            observations,
            horizon_bars=horizon_bars,
            threshold_pct=threshold_pct,
            replicates=bootstrap_replicates,
            seed=seed,
        ),
        "alignment_sensitivity": {
            "scope": "forward-timeframe-aligned events only",
            "included": len(aligned_observations),
            "excluded": len(observations) - len(aligned_observations),
            "overall": summarize_observations(
                aligned_observations,
                horizon_bars=horizon_bars,
                threshold_pct=threshold_pct,
            ),
            "dependence": dependence_summary(
                aligned_observations,
                horizon_bars=horizon_bars,
                threshold_pct=threshold_pct,
            ),
            "confidence_intervals": bootstrap_intervals(
                aligned_observations,
                horizon_bars=horizon_bars,
                threshold_pct=threshold_pct,
                replicates=bootstrap_replicates,
                seed=seed,
            ),
        },
        "limitations": limitations,
    }


def render_markdown(report: dict[str, Any]) -> str:
    canonical = report["overall"]["canonical"]
    late = report["overall"]["late_window_bars_4_to_8"]
    join = report["join"]
    alignment = report["forward_window_alignment"]
    sensitivity = report["alignment_sensitivity"]
    aligned_canonical = sensitivity["overall"]["canonical"]
    aligned_late = sensitivity["overall"]["late_window_bars_4_to_8"]
    lines = [
        "# SWEEP label censoring study",
        "",
        f"Source workflow run: `{report['source']['workflow_run_id']}`",
        *([f"Corpus era: {report['source']['corpus_era_note']}"] if report["source"]["corpus_era_note"] else []),
        f"Joined SWEEP events: **{join['joined']} / {join['family_sweep_events']}**",
        (
            "Forward-window timeframe alignment: "
            f"**{alignment['matches']} match, {alignment['mismatches']} mismatch, "
            f"{alignment['unknown']} unknown**."
        ),
        "",
        "## Result",
        "",
        "| Scope | Censored | Unresolved negatives | Observed hit rate | Identified hit-rate interval |",
        "|---|---:|---:|---:|---:|",
        (
            f"| As emitted, canonical bars 1–8 | {canonical['censored']}/{canonical['n']} "
            f"({canonical['censoring_rate']:.1%}) | {canonical['unresolved_negative']} "
            f"({canonical['unresolved_negative_rate']:.1%}) | {canonical['observed_hit_rate']:.1%} | "
            f"[{canonical['identified_hit_rate_lower']:.1%}, {canonical['identified_hit_rate_upper']:.1%}] |"
        ),
        (
            f"| As emitted, late bars 4–8 | {late['censored']}/{late['n']} "
            f"({late['censoring_rate']:.1%}) | "
            f"{late['unresolved_negative']} ({late['unresolved_negative_rate']:.1%}) | "
            f"{late['observed_hit_rate']:.1%} | "
            f"[{late['identified_hit_rate_lower']:.1%}, {late['identified_hit_rate_upper']:.1%}] |"
        ),
        (
            f"| Aligned-only, canonical bars 1–8 | {aligned_canonical['censored']}/"
            f"{aligned_canonical['n']} ({aligned_canonical['censoring_rate']:.1%}) | "
            f"{aligned_canonical['unresolved_negative']} "
            f"({aligned_canonical['unresolved_negative_rate']:.1%}) | "
            f"{aligned_canonical['observed_hit_rate']:.1%} | "
            f"[{aligned_canonical['identified_hit_rate_lower']:.1%}, "
            f"{aligned_canonical['identified_hit_rate_upper']:.1%}] |"
        ),
        (
            f"| Aligned-only, late bars 4–8 | {aligned_late['censored']}/"
            f"{aligned_late['n']} ({aligned_late['censoring_rate']:.1%}) | "
            f"{aligned_late['unresolved_negative']} "
            f"({aligned_late['unresolved_negative_rate']:.1%}) | "
            f"{aligned_late['observed_hit_rate']:.1%} | "
            f"[{aligned_late['identified_hit_rate_lower']:.1%}, "
            f"{aligned_late['identified_hit_rate_upper']:.1%}] |"
        ),
        "",
        "A negative label from a partial horizon is counted as unresolved, not silently corrected. "
        "The upper bound asks what the hit rate would be if every unresolved negative later hit.",
        "Aligned-only excludes rows whose forward timestamps imply a different timeframe.",
        "",
        "## Dependence",
        "",
    ]
    for indicator, blocks in report["dependence"].items():
        symbol = blocks["by_symbol"]
        timeframe = blocks["by_timeframe"]
        aligned_symbol = sensitivity["dependence"][indicator]["by_symbol"]
        symbol_text = (
            f"ICC={symbol['icc']:.3f}, k={symbol['cluster_count']}" if symbol["measured"] else symbol["reason"]
        )
        aligned_symbol_text = (
            f"ICC={aligned_symbol['icc']:.3f}, k={aligned_symbol['cluster_count']}"
            if aligned_symbol["measured"]
            else aligned_symbol["reason"]
        )
        tf_text = (
            f"ICC={timeframe['icc']:.3f}, k={timeframe['cluster_count']}"
            if timeframe["measured"]
            else timeframe["reason"]
        )
        lines.append(
            f"- `{indicator}`: symbol as-emitted {symbol_text}; symbol aligned-only "
            f"{aligned_symbol_text}; timeframe {tf_text}."
        )
    lines.extend(
        [
            "",
            "## Confidence intervals",
            "",
            "Deterministic 95% percentile intervals for the canonical censoring rate:",
            "",
        ]
    )
    for method in (
        "iid",
        "symbol_cluster",
        "timeframe_cluster",
        "symbol_timeframe_two_way",
    ):
        block = report["confidence_intervals"][method]
        if block["measured"]:
            interval = block["intervals"]["canonical.censoring_rate"]
            lines.append(
                f"- `{method}`: [{interval['low']:.1%}, {interval['high']:.1%}] "
                f"({block['replicates_used']} replicates)."
            )
        else:
            lines.append(f"- `{method}`: unavailable — {block['reason']}.")
    aligned_symbol_ci = sensitivity["confidence_intervals"]["symbol_cluster"]
    if aligned_symbol_ci["measured"]:
        interval = aligned_symbol_ci["intervals"]["canonical.censoring_rate"]
        lines.append(
            f"- `symbol_cluster` (aligned-only): [{interval['low']:.1%}, "
            f"{interval['high']:.1%}] ({aligned_symbol_ci['replicates_used']} replicates)."
        )
    lines.extend(
        [
            "",
            "Shadow-feature availability in this corpus: "
            f"`{report['shadow_feature_availability']}`. Therefore Brier/lift confidence intervals "
            "for the new shadow scores remain unmeasured rather than inferred from legacy rows.",
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report["limitations"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-dir", type=Path, required=True)
    parser.add_argument("--family-events-json", type=Path, required=True)
    parser.add_argument("--source-run-id", default="")
    parser.add_argument("--corpus-era-note", default="")
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--horizon-bars", type=int, default=LABEL_HORIZON_BARS["SWEEP"])
    parser.add_argument("--threshold-pct", type=float, default=DEFAULT_THRESHOLD_PCT)
    parser.add_argument("--bootstrap-replicates", type=int, default=DEFAULT_BOOTSTRAP_REPLICATES)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.horizon_bars <= CONFIRMATION_BARS:
        parser.error("--horizon-bars must exceed the three confirmation bars")
    if args.bootstrap_replicates < 0:
        parser.error("--bootstrap-replicates must be non-negative")
    report = build_report(
        benchmark_dir=args.benchmark_dir,
        family_events_path=args.family_events_json,
        source_run_id=str(args.source_run_id),
        corpus_era_note=str(args.corpus_era_note),
        generated_at=str(args.generated_at) or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        horizon_bars=int(args.horizon_bars),
        threshold_pct=float(args.threshold_pct),
        bootstrap_replicates=int(args.bootstrap_replicates),
        seed=int(args.seed),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(report, args.output, indent=2, sort_keys=True)
    if args.markdown_output is not None:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(render_markdown(report), args.markdown_output)
    print(json.dumps(report["overall"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
