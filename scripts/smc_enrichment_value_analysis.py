"""WP-OV7: Enrichment A/B comparison framework.

Stratifies trade-log entries by regime, trust tier, and news bias
to quantify the incremental value of each enrichment dimension.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

StratKey = Literal["regime", "trust_tier", "news_bias"]


@dataclass(frozen=True)
class TradeEntry:
    """Minimal trade record consumed by the analysis."""

    pnl: float
    regime: str = "unknown"
    trust_tier: str = "unknown"
    news_bias: str = "neutral"


@dataclass
class BucketStats:
    """Aggregate statistics for a single stratification bucket."""

    label: str
    count: int = 0
    total_pnl: float = 0.0
    pnl_values: list[float] = field(default_factory=list)

    @property
    def mean_pnl(self) -> float:
        return self.total_pnl / self.count if self.count else 0.0

    @property
    def win_rate(self) -> float:
        if not self.count:
            return 0.0
        return sum(1 for p in self.pnl_values if p > 0) / self.count

    @property
    def std_pnl(self) -> float:
        if len(self.pnl_values) < 2:
            return 0.0
        return statistics.stdev(self.pnl_values)


@dataclass
class EnrichmentAnalysisResult:
    """Result of a single stratification dimension analysis."""

    dimension: str
    buckets: dict[str, BucketStats]
    total_trades: int
    baseline_mean_pnl: float

    def lift(self, bucket_label: str) -> float:
        """Return the mean-PnL lift of *bucket_label* over baseline."""
        bucket = self.buckets.get(bucket_label)
        # N-1 (TEMPORAL_NUMERICAL_AUDIT_2026-04-24): epsilon-guard against near-zero
        # baselines. ``== 0.0`` would let values like 1e-17 through and produce
        # massive outlier lift values.
        if bucket is None or bucket.count == 0 or abs(self.baseline_mean_pnl) < 1e-12:
            return 0.0
        return (bucket.mean_pnl - self.baseline_mean_pnl) / abs(self.baseline_mean_pnl)


def _bucket_key(entry: TradeEntry, dimension: StratKey) -> str:
    return str(getattr(entry, dimension, "unknown"))


def _stratify(
    trades: Sequence[TradeEntry], dimension: StratKey
) -> dict[str, BucketStats]:
    buckets: dict[str, BucketStats] = {}
    for trade in trades:
        key = _bucket_key(trade, dimension)
        if key not in buckets:
            buckets[key] = BucketStats(label=key)
        buckets[key].count += 1
        buckets[key].total_pnl += trade.pnl
        buckets[key].pnl_values.append(trade.pnl)
    return buckets


def analyze_enrichment_value(
    trade_log: Sequence[TradeEntry],
    dimensions: Sequence[StratKey] = ("regime", "trust_tier", "news_bias"),
) -> dict[str, EnrichmentAnalysisResult]:
    """Stratify *trade_log* by each dimension and compute per-bucket stats.

    Returns a dict keyed by dimension name.
    """
    if not trade_log:
        return {
            dim: EnrichmentAnalysisResult(
                dimension=dim,
                buckets={},
                total_trades=0,
                baseline_mean_pnl=0.0,
            )
            for dim in dimensions
        }

    baseline_pnl = statistics.mean(t.pnl for t in trade_log)
    results: dict[str, EnrichmentAnalysisResult] = {}

    for dim in dimensions:
        buckets = _stratify(trade_log, dim)
        results[dim] = EnrichmentAnalysisResult(
            dimension=dim,
            buckets=buckets,
            total_trades=len(trade_log),
            baseline_mean_pnl=baseline_pnl,
        )

    return results


def format_analysis_markdown(
    results: dict[str, EnrichmentAnalysisResult],
) -> str:
    """Render the analysis results as a Markdown report fragment."""
    lines: list[str] = ["## Enrichment Value A/B Analysis", ""]

    for dim, result in sorted(results.items()):
        lines.append(f"### {dim.replace('_', ' ').title()}")
        lines.append("")
        if not result.buckets:
            lines.append("No trades available.")
            lines.append("")
            continue

        lines += [
            f"Baseline mean PnL: {result.baseline_mean_pnl:.4f} "
            f"({result.total_trades} trades)",
            "",
            "| Bucket | Trades | Mean PnL | Win Rate | Lift |",
            "|--------|--------|----------|----------|------|",
        ]
        for label, stats in sorted(result.buckets.items()):
            lift = result.lift(label)
            lines.append(
                f"| {label} | {stats.count} "
                f"| {stats.mean_pnl:.4f} "
                f"| {stats.win_rate:.1%} "
                f"| {lift:+.1%} |"
            )
        lines.append("")

    return "\n".join(lines)
