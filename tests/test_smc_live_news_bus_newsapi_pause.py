"""NewsAPI.ai SSOT pause gating for the live news bus (2026-07-03).

The live news bus previously hardcoded ``include_newsapi_ai=True`` in both
``poll_live_news_bus`` and ``export_live_news_snapshot`` (and the exporter CLI
derived ``not --skip-newsapi-ai``), so the provider ran whenever a key was
present — ignoring the central ``ENABLE_NEWSAPI_AI`` pause switch
(``open_prep.feature_flags.is_newsapi_ai_enabled``, default OFF) that already
gates the newsstack pipeline.

Contract pinned here:
- default (``include_newsapi_ai=None``) + flag unset  -> provider disabled
- default + ``ENABLE_NEWSAPI_AI=1``                   -> provider polled
- explicit ``True``/``False``                          -> caller wins (CLI overrides)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from scripts import smc_live_news_bus as bus

_NOW = 1_751_500_000.0


def _empty(provider: str) -> bus.ProviderPollResult:
    return bus.ProviderPollResult(provider=provider, items=[], raw_count=0, cursor=0.0)


def _poll(**overrides: object) -> tuple[dict, dict, bool]:
    """Run poll_live_news_bus with all fetchers mocked; report newsapi calls."""
    called = {"newsapi": False}

    def _fake_newsapi(**_kwargs: object) -> bus.ProviderPollResult:
        called["newsapi"] = True
        return _empty("newsapi_ai")

    with (
        patch.object(bus, "fetch_live_news_benzinga", return_value=_empty("benzinga")),
        patch.object(bus, "fetch_live_news_fmp_stock", return_value=_empty("fmp_stock")),
        patch.object(bus, "fetch_live_news_fmp_press", return_value=_empty("fmp_press")),
        patch.object(bus, "fetch_live_news_fmp_articles", return_value=_empty("fmp_articles")),
        patch.object(bus, "fetch_live_news_newsapi_ai", side_effect=_fake_newsapi),
        patch.object(bus, "fetch_live_news_tv", return_value=_empty("tv")),
    ):
        snapshot, next_state = bus.poll_live_news_bus(
            symbols=["AAPL"],
            newsapi_ai_key="newsapi-key",
            now_ts=_NOW,
            **overrides,  # type: ignore[arg-type]
        )
    return snapshot, next_state, called["newsapi"]


def test_default_is_paused_when_flag_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENABLE_NEWSAPI_AI", raising=False)
    snapshot, _state, newsapi_called = _poll()

    assert newsapi_called is False, "paused provider must not be polled"
    provider = snapshot["providers"]["newsapi_ai"]
    assert provider["ok"] is False
    assert provider["error"] == "disabled"


def test_default_enables_when_flag_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_NEWSAPI_AI", "1")
    _snapshot, _state, newsapi_called = _poll()

    assert newsapi_called is True, "ENABLE_NEWSAPI_AI=1 must re-enable the provider"


def test_explicit_true_overrides_paused_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENABLE_NEWSAPI_AI", raising=False)
    _snapshot, _state, newsapi_called = _poll(include_newsapi_ai=True)

    assert newsapi_called is True, "explicit include_newsapi_ai=True (e.g. --newsapi-only) must win"


def test_explicit_false_overrides_enabled_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_NEWSAPI_AI", "1")
    _snapshot, _state, newsapi_called = _poll(include_newsapi_ai=False)

    assert newsapi_called is False, "explicit include_newsapi_ai=False (--skip-newsapi-ai) must win"
