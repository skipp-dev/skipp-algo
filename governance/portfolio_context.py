"""Point-in-time-safe sector and return-correlation context for portfolios.

This contract is intentionally different from the intraday SMT
``correlated_context`` contract.  Portfolio risk consumes completed-session
returns and slowly changing sector reference data; SMT consumes a partner's
same-timeframe structure state.  They may share storage/PIT utilities, not a
business payload.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from itertools import pairwise

from governance.point_in_time import assert_point_in_time
from governance.portfolio_contract import PortfolioRiskContextV1


@dataclass(frozen=True, slots=True)
class CompletedClose:
    symbol: str
    session_date: date
    adjusted_close: float
    published_at: datetime

    def __post_init__(self) -> None:
        if self.published_at.tzinfo is None:
            raise ValueError("CompletedClose.published_at must be timezone-aware")
        if not math.isfinite(self.adjusted_close) or self.adjusted_close <= 0.0:
            raise ValueError("CompletedClose.adjusted_close must be finite and positive")


@dataclass(frozen=True, slots=True)
class SectorAssignment:
    symbol: str
    sector: str
    effective_at: datetime

    def __post_init__(self) -> None:
        if self.effective_at.tzinfo is None:
            raise ValueError("SectorAssignment.effective_at must be timezone-aware")
        if not self.sector.strip():
            raise ValueError("SectorAssignment.sector must be non-empty")


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right, strict=True))
    left_ss = sum((item - left_mean) ** 2 for item in left)
    right_ss = sum((item - right_mean) ** 2 for item in right)
    denominator = math.sqrt(left_ss * right_ss)
    if denominator <= 0.0:
        return None
    return max(-1.0, min(1.0, numerator / denominator))


def build_portfolio_risk_context(
    *,
    symbols: Iterable[str],
    closes: Iterable[CompletedClose],
    sectors: Iterable[SectorAssignment],
    as_of: datetime,
    lookback_sessions: int = 60,
    min_pair_observations: int = 20,
    source: str = "completed_session_returns",
) -> PortfolioRiskContextV1:
    """Build a context using only sessions completed before ``as_of``.

    Any future publication/effective timestamp or same-session close fails
    loudly.  The builder never silently filters such rows because that would
    conceal an upstream lookahead defect.
    """
    if as_of.tzinfo is None:
        raise ValueError("portfolio context as_of must be timezone-aware")
    as_of = as_of.astimezone(UTC)
    if lookback_sessions < 2:
        raise ValueError("lookback_sessions must be at least 2")
    if min_pair_observations < 2:
        raise ValueError("min_pair_observations must be at least 2")

    requested = tuple(sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}))
    close_rows = tuple(closes)
    sector_rows = tuple(sectors)
    assert_point_in_time(
        (row.published_at for row in close_rows),
        as_of,
        label="portfolio close publication",
    )
    assert_point_in_time(
        (row.effective_at for row in sector_rows),
        as_of,
        label="portfolio sector assignment",
    )
    same_or_future_sessions = sorted(
        {
            row.session_date.isoformat()
            for row in close_rows
            if row.session_date >= as_of.date()
        }
    )
    if same_or_future_sessions:
        raise ValueError(
            "portfolio correlation requires completed sessions strictly before as_of; "
            f"got {same_or_future_sessions!r}"
        )

    sector_by_symbol: dict[str, str] = {}
    for row in sorted(sector_rows, key=lambda item: item.effective_at):
        symbol = row.symbol.strip().upper()
        if symbol in requested:
            sector_by_symbol[symbol] = row.sector.strip()

    closes_by_symbol: dict[str, dict[date, float]] = {symbol: {} for symbol in requested}
    for row in close_rows:
        symbol = row.symbol.strip().upper()
        if symbol in closes_by_symbol:
            closes_by_symbol[symbol][row.session_date] = float(row.adjusted_close)

    returns_by_symbol: dict[str, dict[date, float]] = {}
    for symbol, by_date in closes_by_symbol.items():
        ordered = sorted(by_date.items())[-(lookback_sessions + 1) :]
        returns: dict[date, float] = {}
        for (previous_date, previous), (current_date, current) in pairwise(ordered):
            del previous_date
            returns[current_date] = current / previous - 1.0
        returns_by_symbol[symbol] = returns

    correlations: dict[str, float] = {}
    observations: dict[str, int] = {}
    insufficient_symbols: set[str] = {
        symbol
        for symbol, returns in returns_by_symbol.items()
        if len(returns) < min_pair_observations
    }
    for index, left in enumerate(requested):
        for right in requested[index + 1 :]:
            common = sorted(set(returns_by_symbol[left]) & set(returns_by_symbol[right]))
            pair = PortfolioRiskContextV1.pair_key(left, right)
            observations[pair] = len(common)
            if len(common) < min_pair_observations:
                insufficient_symbols.update((left, right))
                continue
            correlation = _pearson(
                [returns_by_symbol[left][day] for day in common],
                [returns_by_symbol[right][day] for day in common],
            )
            if correlation is None:
                insufficient_symbols.update((left, right))
                continue
            correlations[pair] = correlation

    missing_sector = set(requested) - set(sector_by_symbol)
    missing = tuple(sorted(missing_sector | insufficient_symbols))
    required_pairs = len(requested) * (len(requested) - 1) // 2
    complete = not missing and len(correlations) == required_pairs
    return PortfolioRiskContextV1(
        as_of=as_of,
        sector_by_symbol=sector_by_symbol,
        pair_correlations=correlations,
        observations_by_pair=observations,
        source=source,
        complete=complete,
        missing_symbols=missing,
    )


__all__ = [
    "CompletedClose",
    "SectorAssignment",
    "build_portfolio_risk_context",
]
