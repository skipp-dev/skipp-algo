"""Regression tests locking the FMP single-point-of-failure (SPOF) contract.

FMP (Financial Modeling Prep) is one external provider among several. Two
independent layers already make an FMP outage *survivable* rather than fatal,
and these tests pin that behaviour so a future refactor cannot silently turn
FMP back into a hard dependency:

1. **Data layer — graceful degradation with explicit markers.**
   ``databento_volatility_screener.fetch_us_equity_universe_with_metadata``
   never raises when the FMP API key is missing. It falls back to the Nasdaq
   Trader symbol directory and always returns a metadata dict whose
   ``source`` / ``fallback_source`` / ``selection_reason`` /
   ``min_market_cap_applied`` keys describe exactly which provider answered and
   why, so a degraded run is observable downstream.

2. **Preflight layer — fail loud.**
   ``scripts.probe_providers`` marks every critical FMP probe ``critical=True``;
   a missing key therefore yields a blocking ``SKIP`` and ``preflight_or_die``
   aborts with ``SystemExit(1)`` instead of letting a half-configured run
   proceed.
"""

from __future__ import annotations

import logging

import pandas as pd
import pytest

import databento_volatility_screener as screener
import scripts.probe_providers as probe_providers
from databento_volatility_screener import (
    UNIVERSE_COLUMNS,
    fetch_us_equity_universe_with_metadata,
)
from scripts.probe_providers import ProbeResult


def _build_universe_frame(symbols: list[str]) -> pd.DataFrame:
    rows = [
        {
            "symbol": s,
            "company_name": f"{s} Inc.",
            "exchange": "NASDAQ",
            "sector": "",
            "industry": "",
            "market_cap": 0.0,
        }
        for s in symbols
    ]
    return pd.DataFrame(rows, columns=UNIVERSE_COLUMNS)


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=UNIVERSE_COLUMNS)


# ---------------------------------------------------------------------------
# Data layer: graceful degradation when FMP is unavailable
# ---------------------------------------------------------------------------


def test_market_cap_without_fmp_key_degrades_to_nasdaq_with_markers(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A market-cap filter requested with *no* FMP key must not raise.

    It degrades to the official Nasdaq Trader directory and advertises the
    degradation through the metadata markers (so a consumer can tell the
    market-cap floor was dropped).
    """
    nasdaq = _build_universe_frame(["AAA", "BBB"])
    monkeypatch.setattr(
        screener,
        "_fetch_us_equity_universe_via_nasdaq_trader",
        lambda *, exchanges="NASDAQ,NYSE,AMEX": nasdaq,
    )

    def _fail(*_args: object, **_kwargs: object) -> pd.DataFrame:  # pragma: no cover
        raise AssertionError("FMP screener must not be called without an API key")

    monkeypatch.setattr(screener, "_fetch_us_equity_universe_via_screener", _fail)

    with caplog.at_level(logging.WARNING):
        frame, meta = fetch_us_equity_universe_with_metadata(
            fmp_api_key="",
            min_market_cap=2_000_000_000,
        )

    assert list(frame["symbol"]) == ["AAA", "BBB"]
    assert meta["source"] == "nasdaq_trader_symbol_directory"
    assert meta["fallback_source"] is None
    assert meta["min_market_cap_requested"] == 2_000_000_000.0
    assert meta["min_market_cap_effective"] is None
    assert meta["min_market_cap_applied"] is False
    assert meta["selection_reason"] == "official_directory"
    assert "no FMP API key" in caplog.text


def test_market_cap_with_fmp_key_uses_screener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a key and a market-cap floor, the FMP screener answers and the
    metadata records that the floor was actually applied."""
    screened = _build_universe_frame(["MEGA"])
    seen: dict[str, object] = {}

    def _fake_client(api_key: str) -> object:
        seen["api_key"] = api_key
        return object()

    def _fake_screener(
        client: object,
        *,
        min_market_cap: float | None = None,
        exchanges: str = "NASDAQ,NYSE,AMEX",
    ) -> pd.DataFrame:
        seen["min_market_cap"] = min_market_cap
        return screened

    monkeypatch.setattr(screener, "make_fmp_client", _fake_client)
    monkeypatch.setattr(screener, "_fetch_us_equity_universe_via_screener", _fake_screener)

    def _nasdaq_must_not_run(*_a: object, **_k: object) -> pd.DataFrame:  # pragma: no cover
        raise AssertionError("Nasdaq directory must not be consulted on the FMP happy path")

    monkeypatch.setattr(
        screener, "_fetch_us_equity_universe_via_nasdaq_trader", _nasdaq_must_not_run
    )

    frame, meta = fetch_us_equity_universe_with_metadata(
        fmp_api_key="abc123",
        min_market_cap=5_000_000_000,
    )

    assert list(frame["symbol"]) == ["MEGA"]
    assert seen["api_key"] == "abc123"
    assert seen["min_market_cap"] == 5_000_000_000
    assert meta["source"] == "fmp_company_screener"
    assert meta["fallback_source"] == "nasdaq_trader_symbol_directory"
    assert meta["min_market_cap_applied"] is True
    assert meta["selection_reason"] == "market_cap_filter_requested"


def test_nasdaq_empty_with_fmp_key_falls_back_to_screener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the Nasdaq directory fetch comes back empty but a key is present,
    the screener is used as the documented fallback."""
    monkeypatch.setattr(
        screener,
        "_fetch_us_equity_universe_via_nasdaq_trader",
        lambda *, exchanges="NASDAQ,NYSE,AMEX": _empty_frame(),
    )
    monkeypatch.setattr(screener, "make_fmp_client", lambda api_key: object())
    monkeypatch.setattr(
        screener,
        "_fetch_us_equity_universe_via_screener",
        lambda client, *, min_market_cap=None, exchanges="NASDAQ,NYSE,AMEX": _build_universe_frame(
            ["FALL"]
        ),
    )

    frame, meta = fetch_us_equity_universe_with_metadata(fmp_api_key="abc123")

    assert list(frame["symbol"]) == ["FALL"]
    assert meta["source"] == "fmp_company_screener"
    assert meta["selection_reason"] == "official_directory_failed"


def test_nasdaq_empty_without_fmp_key_returns_empty_loudly(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The worst case — no directory and no key — must still not raise; it
    returns an empty universe and logs a warning so the outage is visible."""
    monkeypatch.setattr(
        screener,
        "_fetch_us_equity_universe_via_nasdaq_trader",
        lambda *, exchanges="NASDAQ,NYSE,AMEX": _empty_frame(),
    )

    def _fail(*_a: object, **_k: object) -> pd.DataFrame:  # pragma: no cover
        raise AssertionError("screener must not run without an API key")

    monkeypatch.setattr(screener, "_fetch_us_equity_universe_via_screener", _fail)

    with caplog.at_level(logging.WARNING):
        frame, meta = fetch_us_equity_universe_with_metadata(fmp_api_key="")

    assert frame.empty
    assert meta["source"] == "empty"
    assert meta["fallback_source"] is None
    assert meta["selection_reason"] == "no_available_source"
    assert "empty universe" in caplog.text


def test_no_market_cap_no_key_uses_official_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default path (no key, no market-cap floor) is a clean, non-degraded
    success served entirely by the official directory — FMP is not required."""
    nasdaq = _build_universe_frame(["AAA", "BBB", "CCC"])
    monkeypatch.setattr(
        screener,
        "_fetch_us_equity_universe_via_nasdaq_trader",
        lambda *, exchanges="NASDAQ,NYSE,AMEX": nasdaq,
    )

    frame, meta = fetch_us_equity_universe_with_metadata()

    assert list(frame["symbol"]) == ["AAA", "BBB", "CCC"]
    assert meta["source"] == "nasdaq_trader_symbol_directory"
    assert meta["fallback_source"] is None
    assert meta["min_market_cap_requested"] is None
    assert meta["min_market_cap_applied"] is False
    assert meta["selection_reason"] == "official_directory"


# ---------------------------------------------------------------------------
# Preflight layer: a missing/dead FMP key fails loud
# ---------------------------------------------------------------------------


def test_critical_skip_is_blocking() -> None:
    """A critical probe that SKIPs (e.g. ``FMP_API_KEY`` missing) is blocking."""
    skipped = ProbeResult(
        name="FMP /stable/quote",
        status="SKIP",
        latency_ms=None,
        detail="FMP_API_KEY missing",
        critical=True,
    )
    assert skipped.is_blocking is True


def test_ok_critical_is_not_blocking() -> None:
    ok = ProbeResult(
        name="FMP /stable/quote",
        status="OK",
        latency_ms=12.0,
        detail="",
        critical=True,
    )
    assert ok.is_blocking is False


def test_non_critical_skip_is_not_blocking() -> None:
    skipped = ProbeResult(
        name="FMP /stable/news",
        status="SKIP",
        latency_ms=None,
        detail="FMP_API_KEY missing",
        critical=False,
    )
    assert skipped.is_blocking is False


def test_preflight_or_die_aborts_on_blocking_fmp_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a critical FMP probe blocks, ``preflight_or_die`` raises
    ``SystemExit`` rather than letting a misconfigured run continue."""
    blocking = ProbeResult(
        name="FMP /stable/quote",
        status="SKIP",
        latency_ms=None,
        detail="FMP_API_KEY missing",
        critical=True,
    )
    notified: list[object] = []
    monkeypatch.setattr(probe_providers, "run_probes", lambda *a, **k: [blocking])
    monkeypatch.setattr(probe_providers, "_log_blocking", lambda *a, **k: None)
    monkeypatch.setattr(
        probe_providers, "_notify_blocking", lambda *a, **k: notified.append(a)
    )

    with pytest.raises(SystemExit) as exc:
        probe_providers.preflight_or_die(notify=True, quiet=True)

    assert exc.value.code == 1
    assert notified, "operators must be notified when preflight blocks"


def test_preflight_or_die_can_report_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``raise_on_block=False`` still surfaces the blocking results so callers
    can render them, without aborting the process."""
    blocking = ProbeResult(
        name="FMP /stable/quote",
        status="SKIP",
        latency_ms=None,
        detail="FMP_API_KEY missing",
        critical=True,
    )
    monkeypatch.setattr(probe_providers, "run_probes", lambda *a, **k: [blocking])
    monkeypatch.setattr(probe_providers, "_log_blocking", lambda *a, **k: None)
    monkeypatch.setattr(probe_providers, "_notify_blocking", lambda *a, **k: None)

    results = probe_providers.preflight_or_die(notify=False, raise_on_block=False)

    assert [r.is_blocking for r in results] == [True]


def test_preflight_or_die_passes_when_nothing_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ok = ProbeResult(
        name="FMP /stable/quote",
        status="OK",
        latency_ms=10.0,
        detail="",
        critical=True,
    )

    def _must_not_notify(*_a: object, **_k: object) -> None:  # pragma: no cover
        raise AssertionError("must not notify when nothing blocks")

    monkeypatch.setattr(probe_providers, "run_probes", lambda *a, **k: [ok])
    monkeypatch.setattr(probe_providers, "_notify_blocking", _must_not_notify)

    results = probe_providers.preflight_or_die(notify=True)

    assert [r.is_blocking for r in results] == [False]
