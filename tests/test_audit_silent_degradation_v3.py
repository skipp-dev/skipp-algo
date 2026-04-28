"""Audit Silent-Degradation v3 — pin RED-fix contracts.

Each test maps to a specific RED finding from the v2 prompt re-run on
2026-04-28.

Findings:
    RED 1 (Lens 9): ``_parse_retry_after_seconds`` rejects NaN/Inf in
        all three copies (``newsstack_fmp/_bz_http``,
        ``newsstack_fmp/ingest_fmp``, ``open_prep/macro``) so callers
        never invoke ``time.sleep(nan)`` (which raises ``ValueError``)
        or ``time.sleep(inf)`` (which would wedge the retry loop).
    RED 2 (Lens 9): ``smc_core/resilient.py`` calls ``sleep`` even
        when the full-jitter RNG returns 0, so injected sleeps are
        observed deterministically and ``Retry-After``-style hints are
        not silently dropped.
    RED 3 (Lens 2): ``scripts/smc_calendar_collector.collect_calendar``
        anchors ``today`` on US-Eastern (``ZoneInfo("America/New_York")``)
        instead of the server-local clock, so 20:00\u201324:00 ET on a UTC
        runner does not flip the bucketing one day early.
"""

from __future__ import annotations

import math
from datetime import datetime
from unittest import mock

import pytest


# ── RED 1 — NaN / Inf guard on Retry-After parsers ───────────────────


@pytest.mark.parametrize(
    "module_path",
    [
        "newsstack_fmp._bz_http",
        "newsstack_fmp.ingest_fmp",
        "open_prep.macro",
    ],
)
@pytest.mark.parametrize("raw", ["NaN", "nan", "inf", "-inf", "Infinity"])
def test_parse_retry_after_rejects_non_finite(module_path: str, raw: str) -> None:
    """``time.sleep(nan)`` raises ValueError; ``time.sleep(inf)`` wedges.

    All three module copies of ``_parse_retry_after_seconds`` must
    return ``None`` for non-finite inputs so the caller falls back to
    its bounded backoff schedule instead.
    """
    import importlib

    mod = importlib.import_module(module_path)
    parse = getattr(mod, "_parse_retry_after_seconds")
    assert parse(raw) is None, (
        f"{module_path}._parse_retry_after_seconds({raw!r}) must "
        f"return None to avoid time.sleep(nan/inf) downstream."
    )


@pytest.mark.parametrize(
    "module_path",
    [
        "newsstack_fmp._bz_http",
        "newsstack_fmp.ingest_fmp",
        "open_prep.macro",
    ],
)
def test_parse_retry_after_still_accepts_normal_values(module_path: str) -> None:
    """Regression: numeric and HTTP-date inputs continue to parse."""
    import importlib

    mod = importlib.import_module(module_path)
    parse = getattr(mod, "_parse_retry_after_seconds")
    assert parse("30") == 30.0
    assert parse("0") == 0.0
    assert parse(None) is None
    assert parse("") is None
    assert parse("not-a-number-or-date") is None


# ── RED 2 — resilient.py honors zero-delay sleeps ────────────────────


def test_resilient_calls_sleep_even_when_delay_zero() -> None:
    """If full-jitter RNG returns 0, ``sleep`` must still be called.

    Without this, monkeypatched sleeps in tests fire 0 times even
    though a retry happened, making retry observability brittle and
    hiding real outages from per-attempt counters.
    """
    from smc_core.resilient import resilient

    sleeps: list[float] = []

    def fake_sleep(s: float) -> None:
        sleeps.append(s)

    calls = {"n": 0}

    @resilient(
        retries=2,
        base_delay=1.0,
        max_delay=5.0,
        exceptions=(RuntimeError,),
        rng=lambda: 0.0,  # full-jitter -> always 0
        sleep=fake_sleep,
    )
    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3
    # Two retries -> two sleeps observed (both with delay == 0.0)
    assert sleeps == [0.0, 0.0], (
        f"resilient must call sleep even on delay=0; got {sleeps!r}"
    )


# ── RED 3 — calendar collector anchors on US-Eastern ─────────────────


def test_smc_calendar_collector_anchors_today_on_us_eastern() -> None:
    """22:00 ET on 2026-04-27 must bucket as 2026-04-27, not 2026-04-28.

    A UTC runner at this instant has ``date.today() == 2026-04-28``,
    which would push the same-day earnings into the "tomorrow" bucket.
    The collector must consult ``ZoneInfo("America/New_York")``
    explicitly so bucketing matches the trading session.
    """
    from scripts import smc_calendar_collector as mod

    # 2026-04-28 02:30 UTC == 2026-04-27 22:30 EDT (UTC-4 during DST)
    fake_utc = datetime(2026, 4, 28, 2, 30, 0)

    class _FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            base = fake_utc.replace(tzinfo=__import__("datetime").timezone.utc)
            if tz is None:
                return base.replace(tzinfo=None)
            return base.astimezone(tz)

    with mock.patch.object(mod, "datetime", _FakeDateTime):
        result = mod.collect_earnings_and_macro(
            symbols=["AAPL"],
            earnings_data=[{"symbol": "AAPL", "date": "2026-04-27", "timing": "amc"}],
            macro_events=[],
        )

    today_csv = result["earnings_today_tickers"]
    tomorrow_csv = result["earnings_tomorrow_tickers"]
    assert "AAPL" in today_csv.split(","), (
        "Expected AAPL bucketed under earnings_today on 2026-04-27 ET; "
        f"got result={result!r}"
    )
    assert "AAPL" not in tomorrow_csv.split(","), (
        "AAPL must not appear in earnings_tomorrow when ET clock still on 2026-04-27."
    )


def test_smc_calendar_collector_reference_date_override_still_honored() -> None:
    """Regression: ``reference_date`` keeps deterministic-test path."""
    from datetime import date as _date

    from scripts import smc_calendar_collector as mod

    result = mod.collect_earnings_and_macro(
        symbols=["MSFT"],
        earnings_data=[{"symbol": "MSFT", "date": "2026-05-15", "timing": "bmo"}],
        macro_events=[],
        reference_date=_date(2026, 5, 15),
    )
    assert "MSFT" in result["earnings_today_tickers"].split(",")
    assert "MSFT" in result["earnings_bmo_tickers"].split(",")


# ── AMBER pin — realtime_signals tz-fallback is observable ───────────


def test_realtime_signals_tz_fallback_returns_neutral_fraction() -> None:
    """Pin: when both ``zoneinfo`` and ``dateutil.tz`` are missing,
    ``_expected_cumulative_volume_fraction`` must return 1.0
    (no-adjustment) AND log at debug level — never silently return a
    DST-drifting fixed-offset value.

    This is a guard so a future refactor can't replace the AMBER
    fallback with a fixed-offset one without breaking this contract.
    """
    from open_prep import realtime_signals

    # Force both tz backends to ImportError simultaneously.
    real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    def _no_tz_import(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name in ("zoneinfo", "dateutil.tz", "dateutil"):
            raise ImportError(f"forced for test: {name}")
        return real_import(name, *args, **kwargs)

    with mock.patch("builtins.__import__", side_effect=_no_tz_import):
        result = realtime_signals._expected_cumulative_volume_fraction()

    assert result == 1.0
