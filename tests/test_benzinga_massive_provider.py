"""Tests for the Benzinga transport switch (direct api.benzinga.com vs the
Massive reseller route) — param dialects, normalize tolerance for the Massive
item shape, probe behaviour, and the workflow env plumbing.

Background (2026-07-09): the paid Benzinga subscription is billed via Massive
(formerly Polygon.io) and ships a MASSIVE API key — api.benzinga.com answers
it with 401 "anonymous". BENZINGA_PROVIDER selects the transport per
environment; the default stays ``direct`` so nothing changes until the flag is
flipped together with the matching key.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from newsstack_fmp import ingest_benzinga as ib
from newsstack_fmp.normalize import normalize_benzinga_rest

_REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BENZINGA_PROVIDER", raising=False)


# ── provider resolution ──────────────────────────────────────────────────────

def test_provider_defaults_to_direct_and_rejects_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    assert ib.benzinga_provider() == "direct"
    monkeypatch.setenv("BENZINGA_PROVIDER", "massive")
    assert ib.benzinga_provider() == "massive"
    monkeypatch.setenv("BENZINGA_PROVIDER", "MASSIVE ")
    assert ib.benzinga_provider() == "massive"  # trimmed + case-insensitive
    monkeypatch.setenv("BENZINGA_PROVIDER", "polygon")
    assert ib.benzinga_provider() == "direct"  # garbage falls back loudly


def test_adapter_selects_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    assert ib.BenzingaRestAdapter("k").base_url == ib.BENZINGA_REST_BASE
    monkeypatch.setenv("BENZINGA_PROVIDER", "massive")
    assert ib.BenzingaRestAdapter("k").base_url == ib.BENZINGA_MASSIVE_REST_BASE
    # Explicit param wins over env.
    assert ib.BenzingaRestAdapter("k", provider="direct").base_url == ib.BENZINGA_REST_BASE


# ── param dialects ───────────────────────────────────────────────────────────

def _params(provider: str, **kw) -> dict:
    base = dict(
        api_key="KEY", updated_since=None, page_size=100, channels=None,
        topics=None, page=0, date_from=None, date_to=None, publish_since=None,
        tickers=None, display_output=None, provider=provider,
    )
    base.update(kw)
    return ib._build_news_params(**base)


def test_direct_params_unchanged() -> None:
    p = _params("direct", updated_since="1751980083", channels="News", topics="ai")
    assert p["token"] == "KEY" and p["pageSize"] == 100 and p["page"] == 0
    assert p["updatedSince"] == "1751980083" and p["topics"] == "ai"
    assert "apiKey" not in p and "limit" not in p


def test_massive_params_dialect() -> None:
    p = _params("massive", updated_since="1751980083", channels="News",
                topics="ai", display_output="abstract", tickers="NVDA,MSFT")
    assert p["apiKey"] == "KEY" and p["limit"] == 100
    # Epoch coerced to ISO for the .gte filter (Massive rejects raw epochs).
    assert p["last_updated.gte"] == "2025-07-08T13:08:03Z"
    assert p["tickers"] == "NVDA,MSFT" and p["channels"] == "News"
    # Direct-only params never leak into the Massive dialect.
    for absent in ("token", "pageSize", "page", "topics", "displayOutput", "updatedSince"):
        assert absent not in p, absent


def test_massive_date_range_maps_to_published_bounds() -> None:
    p = _params("massive", date_from="2026-07-01", date_to="2026-07-08T15:30:00Z")
    assert p["published.gte"] == "2026-07-01"
    assert p["published.lte"] == "2026-07-08T15:30:00Z"


def test_epoch_to_iso_passthrough_for_iso() -> None:
    assert ib._epoch_to_iso_utc("2026-07-08T00:00:00Z") == "2026-07-08T00:00:00Z"
    assert ib._epoch_to_iso_utc("1751980083") == "2025-07-08T13:08:03Z"


# ── normalize tolerance for the Massive item shape ──────────────────────────

def test_normalize_handles_massive_shape() -> None:
    item = {
        "benzinga_id": "60350376",
        "author": "benzinga newsdesk",
        "published": "2026-07-09T09:04:15Z",
        "last_updated": "2026-07-09T09:05:00Z",
        "title": "China Considering Export Restrictions",
        "url": "https://www.benzinga.com/news/26/07/60350376/x",
        "channels": ["news"],
        "tickers": ["FXI", "SPY"],
        "tags": [],
    }
    n = normalize_benzinga_rest(item)
    assert n.item_id == "60350376"
    assert n.headline.startswith("China")
    assert n.tickers == ["FXI", "SPY"]
    assert n.published_ts > 0 and n.updated_ts >= n.published_ts
    assert n.snippet == ""  # Massive ships no teaser/body — headline-based scoring
    assert n.source == "benzinga newsdesk"


def test_normalize_direct_shape_unchanged() -> None:
    item = {
        "id": 123, "title": "T", "teaser": "tease", "url": "https://x",
        "created": "2026-07-09T09:00:00Z", "updated": "2026-07-09T09:01:00Z",
        "stocks": [{"name": "NVDA"}], "author": "a",
    }
    n = normalize_benzinga_rest(item)
    assert n.item_id == "123" and n.snippet == "tease" and n.tickers == ["NVDA"]


# ── probes ───────────────────────────────────────────────────────────────────

def test_direct_only_probes_skip_in_massive_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.probe_providers as pp

    monkeypatch.setenv("BENZINGA_API_KEY", "k")
    monkeypatch.setenv("BENZINGA_PROVIDER", "massive")
    for fn in (pp.probe_benzinga_quotes, pp.probe_benzinga_movers):
        status, msg = fn()
        assert status == "SKIP" and "massive" in msg
    status, msg = pp._bz_get("/api/v2/anything")
    assert status == "SKIP" and "massive" in msg


def test_credential_probe_url_follows_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.credential_health_check as chc

    captured: list[str] = []

    def _fake_vendor(**kw):
        captured.append(kw["url"])
        return object()

    monkeypatch.setattr(chc, "_probe_http_vendor", lambda **kw: _fake_vendor(**kw))
    chc.probe_benzinga("KEY")
    monkeypatch.setenv("BENZINGA_PROVIDER", "massive")
    chc.probe_benzinga("KEY")
    assert "api.benzinga.com/api/v2/news?token=KEY" in captured[0]
    assert "api.massive.com/benzinga/v2/news?apiKey=KEY" in captured[1]


# ── workflow env plumbing ────────────────────────────────────────────────────

def test_workflows_pass_the_provider_flag() -> None:
    """Every workflow that passes BENZINGA_API_KEY must also pass
    BENZINGA_PROVIDER — otherwise flipping the repo variable would silently
    leave that job on the direct transport with a Massive key (401s)."""
    wf_dir = _REPO / ".github" / "workflows"
    for wf in sorted(wf_dir.glob("*.yml")):
        text = wf.read_text(encoding="utf-8")
        if "secrets.BENZINGA_API_KEY" in text:
            assert "BENZINGA_PROVIDER" in text, f"{wf.name} passes the key but not the provider flag"


def test_normalize_unescapes_html_entities() -> None:
    # Massive titles arrive HTML-escaped; keyword scoring must see "S&P".
    n = normalize_benzinga_rest({
        "benzinga_id": "1", "title": "S&amp;P 500 &amp; Nasdaq Rise",
        "published": "2026-07-09T09:00:00Z", "url": "https://x", "tickers": ["SPY"],
    })
    assert n.headline == "S&P 500 & Nasdaq Rise"
