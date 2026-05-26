"""Property tests for ``smc_integration.timeframes.is_daily_timeframe``.

Tier-2 invariants (PQ re-audit follow-up): pins the canonical daily-bar
alias set, casing/whitespace-normalisation, and explicit non-daily refusal.
Pure stdlib + pytest — no hypothesis / numpy.
"""

from __future__ import annotations

import pytest

from smc_integration.timeframes import is_daily_timeframe

_CANONICAL_DAILY = ("1D", "D", "DAILY", "1DAY")
_NON_DAILY = (
    "",
    "1m",
    "1M",
    "5",
    "5m",
    "15m",
    "30m",
    "1h",
    "1H",
    "4H",
    "60",
    "1W",
    "W",
    "WEEKLY",
    "1MN",
    "MN",
    "MONTH",
    "MONTHLY",
    "2D",
    "3D",
    "1d1h",
    "Day",
    "day",
    "daiily",
    "1 D",
    "1 DAY",
    "1-D",
    "tick",
    "renko",
)


@pytest.mark.parametrize("canonical", _CANONICAL_DAILY)
def test_canonical_aliases_are_daily(canonical: str) -> None:
    assert is_daily_timeframe(canonical) is True


@pytest.mark.parametrize("alias", _CANONICAL_DAILY)
def test_lowercase_variants_are_daily(alias: str) -> None:
    assert is_daily_timeframe(alias.lower()) is True


@pytest.mark.parametrize("alias", _CANONICAL_DAILY)
def test_mixedcase_variants_are_daily(alias: str) -> None:
    if len(alias) >= 2:
        swapped = alias[0].lower() + alias[1:].upper()
        assert is_daily_timeframe(swapped) is True


@pytest.mark.parametrize("alias", _CANONICAL_DAILY)
@pytest.mark.parametrize("pad", [" ", "  ", "\t", " \t ", "\n", " \n"])
def test_whitespace_padding_is_stripped(alias: str, pad: str) -> None:
    assert is_daily_timeframe(f"{pad}{alias}{pad}") is True


@pytest.mark.parametrize("tf", _NON_DAILY)
def test_non_daily_inputs_rejected(tf: str) -> None:
    assert is_daily_timeframe(tf) is False


def test_return_type_is_bool() -> None:
    for tf in ("1D", "1m", ""):
        result = is_daily_timeframe(tf)
        assert isinstance(result, bool), f"expected bool for {tf!r}, got {type(result)}"


def test_idempotent_under_repeat_calls() -> None:
    # Same input → same output across consecutive calls (no global state mutation).
    for tf in sorted({*_CANONICAL_DAILY, *_NON_DAILY}):
        first = is_daily_timeframe(tf)
        second = is_daily_timeframe(tf)
        third = is_daily_timeframe(tf)
        assert first == second == third


def test_alias_set_is_frozen_at_four() -> None:
    # Guards against silent expansion of the daily alias set (would relax
    # the intraday workbook fallback contract).
    from smc_integration.timeframes import _DAILY_ALIASES

    assert _DAILY_ALIASES == frozenset({"1D", "D", "DAILY", "1DAY"})


def test_case_normalisation_via_upper() -> None:
    # Every alias must canonicalise via .strip().upper() — pins the
    # exact normalisation contract used by callsites.
    for alias in _CANONICAL_DAILY:
        for casing in (alias, alias.lower(), alias.swapcase(), alias.title()):
            for pad in ("", " ", "\t "):
                assert is_daily_timeframe(f"{pad}{casing}{pad}") is True
