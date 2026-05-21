"""Regression pin: Databento ``LSTAT`` (listing-status) corporate-action events
propagate into the open-prep ``corporate_action_penalty`` so that delisted /
listing-change tickers are at minimum surfaced as a warn-flag during screening.

Audit "SkippALGO Quant Audit 2026-05-21" claim #8 (survivorship bias)
called this out as a gap. The existing test
``test_corporate_action_flags_include_reference_identifier_change`` covers
``LCC``; this file pins the same flow for the dedicated delisting signal
``LSTAT`` so future refactors of the reference snapshot or penalty pipeline
cannot silently drop the survivorship guard.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import open_prep.run_open_prep as run_open_prep
from open_prep.screen import classify_long_gap


class _StubCalendarClient:
    """Minimal stub for the calendar-API client used by _fetch_corporate_action_flags."""

    def get_splits_calendar(self, *_args, **_kwargs):
        return []

    def get_dividends_calendar(self, *_args, **_kwargs):
        return []

    def get_ipos_calendar(self, *_args, **_kwargs):
        return []


@patch("databento_reference.get_reference_event_risk_snapshot")
@patch("databento_reference.maybe_refresh_symbol_reference_cache")
def test_lstat_event_contributes_corporate_action_penalty(
    mock_refresh_reference,
    mock_reference_snapshot,
) -> None:
    """An LSTAT delisting event must produce a non-zero corporate_action_penalty."""

    mock_reference_snapshot.return_value = {
        "provider_status": "ok",
        "reference_change_tickers": ["ZOMB"],
        "by_symbol": {
            "ZOMB": {
                "event_types": ["LSTAT"],
                "latest_effective_date": "2026-05-20",
                "aliases": [],
            }
        },
    }

    result = run_open_prep._fetch_corporate_action_flags(
        client=_StubCalendarClient(),
        symbols=["ZOMB"],
        today=date(2026, 5, 20),
        window_days=3,
    )

    assert result["ZOMB"]["identifier_change_window"] is True
    assert result["ZOMB"]["identifier_change_event_types"] == "LSTAT"
    assert result["ZOMB"]["identifier_change_effective_date"] == "2026-05-20"
    assert (
        result["ZOMB"]["corporate_action_penalty"]
        == run_open_prep.PENALTY_IDENTIFIER_CHANGE
    )
    mock_refresh_reference.assert_called_once()


def test_screen_surfaces_corporate_action_risk_when_penalty_at_threshold() -> None:
    """A row whose corporate_action_penalty >= 1.0 must carry the warn flag.

    This pins the downstream consumer of the LSTAT penalty: the screen layer
    treats an aggregated corporate-action penalty >= 1.0 as a survivorship /
    delisting warn flag rather than silently letting the candidate through.
    """

    row = {
        "gap_available": True,
        "gap_pct": 2.5,
        "ext_hours_score": 1.5,
        "ext_volume_ratio": 0.12,
        "premarket_stale": False,
        "premarket_spread_bps": 20.0,
        "earnings_risk_window": False,
        "corporate_action_penalty": 1.0,
    }
    out = classify_long_gap(row, bias=0.0)
    assert "corporate_action_risk" in out["warn_flags"].split(";")


def test_screen_no_warn_flag_when_penalty_below_threshold() -> None:
    """Sanity counter-test: a sub-threshold penalty must not produce the flag."""

    row = {
        "gap_available": True,
        "gap_pct": 2.5,
        "ext_hours_score": 1.5,
        "ext_volume_ratio": 0.12,
        "premarket_stale": False,
        "premarket_spread_bps": 20.0,
        "earnings_risk_window": False,
        "corporate_action_penalty": 0.3,
    }
    out = classify_long_gap(row, bias=0.0)
    assert "corporate_action_risk" not in out["warn_flags"].split(";")
