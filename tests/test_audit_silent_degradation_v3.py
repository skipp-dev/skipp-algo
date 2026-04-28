"""Regression tests for the v3 silent-degradation audit.

These tests pin behaviours that were silently broken before the audit:

* ``_parse_retry_after_seconds`` must reject NaN/Inf so the retry loop
  never feeds ``time.sleep(nan)`` (raises ``ValueError``) or
  ``time.sleep(inf)`` (wedges the loop).
* ``smc_core.resilient.resilient`` must call its injected sleep stub
  even when the full-jitter RNG returns 0.0; otherwise injected delays
  and explicit ``Retry-After: 0`` hints are silently dropped.
* ``scripts.smc_calendar_collector.collect_earnings_and_macro`` must
  anchor "today" in US-Eastern, not the server's local timezone.
* The realtime-signals VWAP fallback must keep returning the neutral
  fraction (1.0) when neither ``zoneinfo`` nor ``dateutil.tz`` is
  importable, so a future refactor can't silently swap in a fixed
  UTC offset that mis-fires around DST.
"""
from __future__ import annotations

import builtins
import importlib
import sys
from datetime import date as _date, datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# RED 1 — _parse_retry_after_seconds NaN/Inf hygiene
# ---------------------------------------------------------------------------

_RETRY_AFTER_MODULES = [
    "newsstack_fmp._bz_http",
    "newsstack_fmp.ingest_fmp",
    "open_prep.macro",
]


@pytest.mark.parametrize("module_name", _RETRY_AFTER_MODULES)
@pytest.mark.parametrize(
    "raw_value", ["NaN", "nan", "inf", "-inf", "Infinity"]
)
def test_parse_retry_after_rejects_non_finite(module_name, raw_value):
    mod = importlib.import_module(module_name)
    parser = getattr(mod, "_parse_retry_after_seconds")
    assert parser(raw_value) is None, (
        f"{module_name}._parse_retry_after_seconds({raw_value!r}) must "
        f"return None to avoid time.sleep(NaN/Inf)."
    )


@pytest.mark.parametrize("module_name", _RETRY_AFTER_MODULES)
def test_parse_retry_after_still_accepts_normal_values(module_name):
    mod = importlib.import_module(module_name)
    parser = getattr(mod, "_parse_retry_after_seconds")
    assert parser("30") == 30.0
    assert parser("0") == 0.0
    assert parser(None) is None
    assert parser("") is None
    assert parser("not-a-number-or-date") is None


# ---------------------------------------------------------------------------
# RED 2 — resilient() must invoke sleep stub even when delay == 0
# ---------------------------------------------------------------------------


def test_resilient_calls_sleep_even_when_delay_zero():
    from smc_core.resilient import resilient

    class _FakeSleep:
        def __init__(self) -> None:
            self.calls: list[float] = []

        def __call__(self, seconds: float) -> None:
            self.calls.append(seconds)

    fake_sleep = _FakeSleep()

    @resilient(
        retries=2,
        base_delay=1.0,
        max_delay=5.0,
        exceptions=(RuntimeError,),
        rng=lambda: 0.0,
        sleep=fake_sleep,
    )
    def always_fails() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        always_fails()
    # RNG=0 → delay=0 on both retry attempts; sleep stub MUST still be
    # called so injected fakes remain observable.
    assert fake_sleep.calls == [0.0, 0.0]


# ---------------------------------------------------------------------------
# RED 3 — smc_calendar_collector anchors "today" in US-Eastern
# ---------------------------------------------------------------------------


class _FakeDateTime(datetime):
    """``datetime`` subclass with ``now(tz)`` pinned to a known UTC instant."""

    _PINNED_UTC = datetime(2026, 4, 28, 2, 30, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        if tz is None:
            return cls._PINNED_UTC.replace(tzinfo=None)
        return cls._PINNED_UTC.astimezone(tz)


def test_smc_calendar_collector_anchors_today_on_us_eastern(monkeypatch):
    from scripts import smc_calendar_collector as mod

    # 2026-04-28 02:30 UTC == 2026-04-27 22:30 US/Eastern (EDT, UTC-4).
    # On a UTC server, ``date.today()`` would advance to 2026-04-28 and
    # silently push the AAPL earnings into ``earnings_tomorrow_tickers``.
    monkeypatch.setattr(mod, "datetime", _FakeDateTime)

    result = mod.collect_earnings_and_macro(
        symbols=["AAPL"],
        earnings_data=[
            {"symbol": "AAPL", "date": "2026-04-27", "timing": "amc"},
        ],
        macro_events=[],
    )
    today_tickers = result["earnings_today_tickers"].split(",")
    assert "AAPL" in today_tickers, (
        "Earnings on 2026-04-27 (US/Eastern today) must land in "
        "earnings_today_tickers, not earnings_tomorrow_tickers."
    )


def test_smc_calendar_collector_reference_date_override_still_honored():
    from scripts import smc_calendar_collector as mod

    result = mod.collect_earnings_and_macro(
        symbols=["MSFT"],
        earnings_data=[
            {"symbol": "MSFT", "date": "2026-05-15", "timing": "bmo"},
        ],
        macro_events=[],
        reference_date=_date(2026, 5, 15),
    )
    assert "MSFT" in result["earnings_today_tickers"].split(",")
    assert "MSFT" in result["earnings_bmo_tickers"].split(",")


def test_smc_calendar_collector_macro_event_uses_et_date(monkeypatch):
    """A macro event near UTC midnight must be classified by its ET date,
    not its raw UTC date — otherwise an FOMC release at 02:00 UTC (=
    22:00 ET prior day in EDT) would be silently dropped from "today"."""
    from scripts import smc_calendar_collector as mod

    # Pin "now" to 2026-04-27 22:30 ET (= 2026-04-28 02:30 UTC).
    monkeypatch.setattr(mod, "datetime", _FakeDateTime)

    # Macro event at 2026-04-28 02:00 UTC. In UTC that's 04-28; in ET
    # that's 04-27 22:00 — the same trading day as "today" (04-27 ET).
    result = mod.collect_earnings_and_macro(
        symbols=[],
        earnings_data=[],
        macro_events=[
            {
                "name": "FOMC Rate Decision",
                "time_utc": "2026-04-28T02:00:00+00:00",
                "impact": "high",
            },
        ],
    )
    assert result["high_impact_macro_today"] is True, (
        "Event at 02:00 UTC (= 22:00 ET prior day) must count as today's "
        "macro event when ``today`` is anchored in ET."
    )
    assert result["macro_event_name"] == "FOMC Rate Decision"


# ---------------------------------------------------------------------------
# AMBER pin (Lens 2) — realtime_signals tz-fallback must remain neutral
# ---------------------------------------------------------------------------


def test_realtime_signals_tz_fallback_returns_neutral_fraction(monkeypatch):
    """When neither zoneinfo nor dateutil.tz is available, the VWAP
    expected-fraction helper must return 1.0 (neutral) rather than
    silently swapping in a fixed UTC offset that breaks across DST."""
    real_import = builtins.__import__

    def _blocking_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in ("zoneinfo", "dateutil.tz", "dateutil"):
            raise ImportError(f"blocked for test: {name}")
        if fromlist and name == "dateutil" and "tz" in fromlist:
            raise ImportError("blocked for test: dateutil.tz")
        return real_import(name, globals, locals, fromlist, level)

    # Drop already-imported copies so the patched __import__ runs.
    for cached in list(sys.modules):
        if cached == "open_prep.realtime_signals" or cached.startswith(
            ("zoneinfo", "dateutil")
        ):
            sys.modules.pop(cached, None)

    monkeypatch.setattr(builtins, "__import__", _blocking_import)
    try:
        rs = importlib.import_module("open_prep.realtime_signals")
        assert rs._expected_cumulative_volume_fraction() == 1.0
    finally:
        # Allow subsequent tests to re-import the real module.
        sys.modules.pop("open_prep.realtime_signals", None)
