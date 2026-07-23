"""Coverage scope for the full-universe session-minute fetch.

`collect_full_universe_session_minute_detail` asserts complete coverage of the
symbols it is told are *required*. Passing it no scope at all means "every symbol
in the universe is required", which is wrong: an illiquid ticker legitimately has
no minute bars on a given day. Export run 29985038127 died exactly there —
`incomplete symbol coverage (5822/6917)` with the missing names all being
thin-book tickers (AACB, AACBR, AACBU, ...).

The runtime's full path already builds the correct scope from
`daily_symbol_features_full_universe`: every symbol-day is *fetched*, but only
the ones flagged `has_intraday` are *required*. This module hosts that
construction so the export and the runtime cannot drift apart.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from scripts.smc_databento_session_detail import build_session_minute_coverage_scope


def _frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_symbols_without_intraday_are_fetched_but_not_required() -> None:
    scope = build_session_minute_coverage_scope(
        _frame(
            [
                {"trade_date": "2026-06-23", "symbol": "AAPL", "has_intraday": True},
                {"trade_date": "2026-06-23", "symbol": "AACB", "has_intraday": False},
            ]
        )
    )
    day = date(2026, 6, 23)
    assert scope.expected_symbols_by_trade_day[day] == {"AAPL", "AACB"}
    assert scope.required_symbols_by_trade_day[day] == {"AAPL"}
    assert scope.universe_symbols == {"AAPL", "AACB"}


def test_missing_has_intraday_column_requires_every_symbol() -> None:
    """Without the flag there is nothing to relax against, so stay strict."""
    scope = build_session_minute_coverage_scope(
        _frame(
            [
                {"trade_date": "2026-06-23", "symbol": "AAPL"},
                {"trade_date": "2026-06-23", "symbol": "MSFT"},
            ]
        )
    )
    day = date(2026, 6, 23)
    assert scope.required_symbols_by_trade_day[day] == {"AAPL", "MSFT"}


def test_scope_is_per_trade_day() -> None:
    scope = build_session_minute_coverage_scope(
        _frame(
            [
                {"trade_date": "2026-06-23", "symbol": "AAPL", "has_intraday": True},
                {"trade_date": "2026-06-24", "symbol": "AAPL", "has_intraday": False},
                {"trade_date": "2026-06-24", "symbol": "MSFT", "has_intraday": True},
            ]
        )
    )
    assert scope.required_symbols_by_trade_day[date(2026, 6, 23)] == {"AAPL"}
    assert scope.required_symbols_by_trade_day[date(2026, 6, 24)] == {"MSFT"}
    assert scope.expected_symbols_by_trade_day[date(2026, 6, 24)] == {"AAPL", "MSFT"}


def test_symbols_are_upper_cased_and_blanks_dropped() -> None:
    scope = build_session_minute_coverage_scope(
        _frame(
            [
                {"trade_date": "2026-06-23", "symbol": "aapl", "has_intraday": True},
                {"trade_date": "2026-06-23", "symbol": "", "has_intraday": True},
                {"trade_date": None, "symbol": "MSFT", "has_intraday": True},
            ]
        )
    )
    day = date(2026, 6, 23)
    assert scope.expected_symbols_by_trade_day[day] == {"AAPL"}
    assert scope.universe_symbols == {"AAPL"}


def test_string_false_is_not_required() -> None:
    """`has_intraday` survives a parquet round-trip as strings in some bundles.

    A naive `astype(bool)` turns every non-empty string into True, which would
    make the whole universe required again — the exact failure that killed export
    run 29985038127, but silent: the scope would simply be wrong.
    """
    scope = build_session_minute_coverage_scope(
        _frame(
            [
                {"trade_date": "2026-06-23", "symbol": "AAPL", "has_intraday": "true"},
                {"trade_date": "2026-06-23", "symbol": "AACB", "has_intraday": "false"},
                {"trade_date": "2026-06-23", "symbol": "AACG", "has_intraday": "no"},
                {"trade_date": "2026-06-23", "symbol": "AACI", "has_intraday": "0"},
            ]
        )
    )
    day = date(2026, 6, 23)
    assert scope.expected_symbols_by_trade_day[day] == {"AAPL", "AACB", "AACG", "AACI"}
    assert scope.required_symbols_by_trade_day[day] == {"AAPL"}


def test_numeric_and_null_intraday_flags() -> None:
    scope = build_session_minute_coverage_scope(
        _frame(
            [
                {"trade_date": "2026-06-23", "symbol": "AAPL", "has_intraday": 1},
                {"trade_date": "2026-06-23", "symbol": "AACB", "has_intraday": 0},
                {"trade_date": "2026-06-23", "symbol": "AACG", "has_intraday": None},
            ]
        )
    )
    assert scope.required_symbols_by_trade_day[date(2026, 6, 23)] == {"AAPL"}
