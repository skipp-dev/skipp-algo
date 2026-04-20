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

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
            r * w for r, w in zip(self.hit_rates, self.weights)
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


def load_family_metrics(benchmark_dir: Path) -> dict[str, FamilyStats]:
    """Walk benchmark_dir/{SYMBOL}/{TF}/scoring_*.json and aggregate family_metrics."""
    stats: dict[str, FamilyStats] = {}

    for scoring_file in sorted(benchmark_dir.rglob("scoring_*.json")):
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
) -> CalibrationResult:
    """End-to-end calibration: load → aggregate → calibrate."""
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

    return CalibrationResult(
        family_weights=family_weights,
        rank_thresholds=rank_thresholds,
        family_stats=family_stats_out,
        total_events=total_events,
        total_pairs=total_pairs,
        source_dir=str(benchmark_dir),
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


def to_json(cal: CalibrationResult) -> dict[str, Any]:
    """Serialize the calibration result for persistence."""
    return {
        "family_weights": cal.family_weights,
        "rank_thresholds": cal.rank_thresholds,
        "family_stats": cal.family_stats,
        "total_events": cal.total_events,
        "total_pairs": cal.total_pairs,
        "source_dir": cal.source_dir,
    }


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


def main(argv: list[str] | None = None) -> None:
    import argparse

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
    args = parser.parse_args(argv)

    cal = calibrate_from_benchmark(args.benchmark_dir, smoothing=args.smoothing)

    # Write JSON
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(
        json.dumps(to_json(cal), indent=2) + "\n", encoding="utf-8"
    )

    # Write Markdown report alongside
    md_path = args.output_path.with_suffix(".md")
    md_path.write_text(render_calibration_report(cal), encoding="utf-8")

    print(f"Calibration written to {args.output_path}")
    print(f"Report written to {md_path}")
    print()
    print("Calibrated family weights:")
    for fam, w in sorted(cal.family_weights.items()):
        prior = _DEFAULT_FAMILY_WEIGHTS.get(fam, 0.50)
        delta = w - prior
        sign = "+" if delta >= 0 else ""
        print(f"  {fam}: {prior:.2f} → {w:.4f} ({sign}{delta:.4f})")

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
