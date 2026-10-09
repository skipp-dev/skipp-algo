"""Source-purity tests for Databento A0 reference construction."""

from __future__ import annotations

import pytest

from open_prep.a0_reference import DatabentoDailyBar, build_databento_reference


def _bar(day: int, *, source: str = "databento:daily", adjusted: bool = True):
    return DatabentoDailyBar(
        symbol="NVDA",
        session_date=f"2026-07-{day:02d}",
        close=100.0 + day,
        volume=day * 1_000,
        source=source,
        corporate_action_adjusted=adjusted,
    )


def test_reference_uses_only_prior_adjusted_databento_sessions() -> None:
    reference = build_databento_reference(
        symbol="nvda",
        bars=[_bar(13), _bar(14), _bar(15), _bar(16), _bar(17)],
        as_of_session="2026-07-17",
        lookback_sessions=3,
        reference_version="db-daily-v1",
        corporate_action_version="db-corp-v1",
    )
    assert reference.previous_close == 116.0
    assert reference.average_daily_volume == 15_000.0
    assert reference.as_of_session == "2026-07-16"
    assert reference.source == "databento:daily"


@pytest.mark.parametrize(
    "bars",
    [
        [_bar(14), _bar(15, source="fmp"), _bar(16)],
        [_bar(14), _bar(15, adjusted=False), _bar(16)],
    ],
)
def test_reference_rejects_mixed_or_unadjusted_history(bars) -> None:
    with pytest.raises(ValueError):
        build_databento_reference(
            symbol="NVDA",
            bars=bars,
            as_of_session="2026-07-17",
            lookback_sessions=3,
            reference_version="db-daily-v1",
            corporate_action_version="db-corp-v1",
        )


def test_reference_rejects_insufficient_history() -> None:
    with pytest.raises(ValueError, match="insufficient"):
        build_databento_reference(
            symbol="NVDA",
            bars=[_bar(16)],
            as_of_session="2026-07-17",
            lookback_sessions=2,
            reference_version="db-daily-v1",
            corporate_action_version="db-corp-v1",
        )
