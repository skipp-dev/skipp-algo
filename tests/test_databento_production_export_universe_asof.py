"""Truth-audit #5: point-in-time universe resolution wiring in the export.

The production export used to import the survivorship-BLIND universe fetcher
(the diverged monolith copy without ``trade_date``/snapshot params), so every
historical export shard was screened with *today's* universe. It now imports
the guarded ``databento_universe`` fetcher and resolves the as-of trade date +
``active_only`` via ``_resolve_universe_asof`` so historical runs replay a
per-day snapshot (or honestly flag ``survivorship_bias_risk``) instead of
silently biasing.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

import scripts.databento_production_export as dpe


def test_import_is_the_guarded_fetcher() -> None:
    # The name must resolve to databento_universe (guarded), NOT the blind
    # databento_volatility_screener copy.
    assert dpe.fetch_us_equity_universe_with_metadata.__module__ == "databento_universe"


def test_asof_today_run_is_active_only() -> None:
    today = date(2026, 7, 11)
    days = [date(2026, 7, 9), date(2026, 7, 10), today]
    as_of, active_only = dpe._resolve_universe_asof(days, today=today)
    assert as_of == today
    assert active_only is True  # live run → persists a snapshot


def test_asof_historical_run_opts_out_of_active_only() -> None:
    today = date(2026, 7, 11)
    days = [date(2026, 3, 2), date(2026, 3, 3)]
    as_of, active_only = dpe._resolve_universe_asof(days, today=today)
    assert as_of == date(2026, 3, 3)  # latest processed day
    assert active_only is False  # historical → replay snapshot / honest bias flag


def test_asof_accepts_timestamps_and_strings() -> None:
    today = date(2026, 7, 11)
    days = [pd.Timestamp("2026-07-01"), "2026-07-02"]
    as_of, active_only = dpe._resolve_universe_asof(days, today=today)
    assert as_of == date(2026, 7, 2)
    assert active_only is False


def test_asof_empty_defaults_to_live() -> None:
    as_of, active_only = dpe._resolve_universe_asof([], today=date(2026, 7, 11))
    assert as_of is None
    assert active_only is True
