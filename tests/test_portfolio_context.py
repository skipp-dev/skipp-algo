from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from governance.point_in_time import LookaheadError
from governance.portfolio_context import (
    CompletedClose,
    SectorAssignment,
    build_portfolio_risk_context,
)

AS_OF = datetime(2026, 8, 8, 14, 0, tzinfo=UTC)


def _closes(symbol: str, multiplier: float = 1.0) -> list[CompletedClose]:
    rows = []
    price = 100.0
    for offset in range(25):
        session = date(2026, 7, 1) + timedelta(days=offset)
        price *= 1.0 + multiplier * (0.002 if offset % 2 == 0 else -0.001)
        rows.append(
            CompletedClose(
                symbol=symbol,
                session_date=session,
                adjusted_close=price,
                published_at=datetime.combine(
                    session,
                    datetime.min.time(),
                    tzinfo=UTC,
                )
                + timedelta(hours=22),
            )
        )
    return rows


def test_builds_completed_session_context_with_pair_coverage() -> None:
    context = build_portfolio_risk_context(
        symbols=("AAPL", "MSFT"),
        closes=(*_closes("AAPL"), *_closes("MSFT")),
        sectors=(
            SectorAssignment("AAPL", "Technology", AS_OF - timedelta(days=100)),
            SectorAssignment("MSFT", "Technology", AS_OF - timedelta(days=100)),
        ),
        as_of=AS_OF,
        min_pair_observations=20,
    )
    assert context.complete is True
    assert context.correlation("AAPL", "MSFT") == pytest.approx(1.0)
    assert context.observations_by_pair["AAPL::MSFT"] == 24


def test_future_publication_fails_loud() -> None:
    rows = _closes("AAPL")
    rows[0] = CompletedClose(
        symbol="AAPL",
        session_date=rows[0].session_date,
        adjusted_close=rows[0].adjusted_close,
        published_at=AS_OF + timedelta(seconds=1),
    )
    with pytest.raises(LookaheadError):
        build_portfolio_risk_context(
            symbols=("AAPL",),
            closes=rows,
            sectors=(),
            as_of=AS_OF,
        )


def test_same_day_close_is_rejected_even_when_timestamp_is_not_future() -> None:
    row = CompletedClose(
        symbol="AAPL",
        session_date=AS_OF.date(),
        adjusted_close=100,
        published_at=AS_OF - timedelta(minutes=1),
    )
    with pytest.raises(ValueError, match="completed sessions strictly before"):
        build_portfolio_risk_context(
            symbols=("AAPL",),
            closes=(row,),
            sectors=(),
            as_of=AS_OF,
        )


def test_missing_sector_or_history_remains_explicit() -> None:
    context = build_portfolio_risk_context(
        symbols=("AAPL", "MSFT"),
        closes=_closes("AAPL"),
        sectors=(SectorAssignment("AAPL", "Technology", AS_OF - timedelta(days=100)),),
        as_of=AS_OF,
        min_pair_observations=20,
    )
    assert context.complete is False
    assert "MSFT" in context.missing_symbols
    assert context.correlation("AAPL", "MSFT") is None
