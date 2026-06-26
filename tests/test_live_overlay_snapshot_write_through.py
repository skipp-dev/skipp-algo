"""Write-through persistence tests for the live-overlay snapshot loaders.

Each loader, after a successful runtime ``*_URL`` fetch, atomically persists the
fetched payload to its local snapshot path. On Railway that path points at a
mounted volume, so a cold start can read the last-good copy instead of falling
back to the stale Docker-baked seed when the URL is momentarily unreachable.
"""

from __future__ import annotations

import json

import pytest

from services.live_overlay_daemon import compute


@pytest.fixture(autouse=True)
def _reset_loader_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force every loader to perform a fresh fetch by clearing module caches."""
    monkeypatch.setattr(compute, "_news_cache", {})
    monkeypatch.setattr(compute, "_news_loaded_at", 0.0)
    monkeypatch.setattr(compute, "_news_checked_at", 0.0)
    monkeypatch.setattr(compute, "_signals_cache", {})
    monkeypatch.setattr(compute, "_signals_loaded_at", 0.0)
    monkeypatch.setattr(compute, "_signals_checked_at", 0.0)
    monkeypatch.setattr(compute, "_experiment_cache", {})
    monkeypatch.setattr(compute, "_experiment_loaded_at", 0.0)
    monkeypatch.setattr(compute, "_experiment_checked_at", 0.0)
    monkeypatch.setattr(compute, "_experiment_history_cache", [])
    monkeypatch.setattr(compute, "_experiment_history_loaded_at", 0.0)
    monkeypatch.setattr(compute, "_experiment_history_checked_at", 0.0)
    monkeypatch.setattr(compute, "_tradingview_credential_cache", {})
    monkeypatch.setattr(compute, "_tradingview_credential_loaded_at", 0.0)
    monkeypatch.setattr(compute, "_tradingview_credential_checked_at", 0.0)


def test_news_write_through(tmp_path, monkeypatch) -> None:
    dest = tmp_path / "nested" / "news.json"
    payload = {"providers": {"fmp": {"ok": True}}}
    monkeypatch.setattr(compute.config, "news_snapshot_url", lambda: "https://example.test/news")
    monkeypatch.setattr(compute.config, "news_snapshot_url_token", lambda: "")
    monkeypatch.setattr(compute.config, "news_snapshot_path", lambda: dest)
    monkeypatch.setattr(compute, "_fetch_news_url", lambda url, token, **kw: dict(payload))

    result = compute._load_news_snapshot()

    assert result == payload
    assert dest.exists()
    assert json.loads(dest.read_text(encoding="utf-8")) == payload


def test_news_no_write_through_on_fetch_failure(tmp_path, monkeypatch) -> None:
    dest = tmp_path / "news.json"
    monkeypatch.setattr(compute.config, "news_snapshot_url", lambda: "https://example.test/news")
    monkeypatch.setattr(compute.config, "news_snapshot_url_token", lambda: "")
    monkeypatch.setattr(compute.config, "news_snapshot_path", lambda: dest)
    monkeypatch.setattr(compute, "_fetch_news_url", lambda url, token, **kw: None)

    result = compute._load_news_snapshot()

    assert result == {}
    assert not dest.exists()


def test_news_no_write_through_when_payload_exceeds_size_limit(tmp_path, monkeypatch) -> None:
    dest = tmp_path / "news.json"
    payload = {"providers": {"fmp": {"headline": "X" * 128}}}
    monkeypatch.setenv("OVERLAY_SNAPSHOT_PERSIST_MAX_BYTES", "32")
    monkeypatch.setattr(compute.config, "news_snapshot_url", lambda: "https://example.test/news")
    monkeypatch.setattr(compute.config, "news_snapshot_url_token", lambda: "")
    monkeypatch.setattr(compute.config, "news_snapshot_path", lambda: dest)
    monkeypatch.setattr(compute, "_fetch_news_url", lambda url, token, **kw: dict(payload))

    result = compute._load_news_snapshot()

    assert result == payload
    # Oversized payloads are served from memory but not persisted to disk.
    assert not dest.exists()


def test_signals_write_through(tmp_path, monkeypatch) -> None:
    dest = tmp_path / "signals.json"
    payload = {"symbols": {"AAPL": {"bias": "long"}}}
    monkeypatch.setattr(compute.config, "signals_snapshot_url", lambda: "https://example.test/signals")
    monkeypatch.setattr(compute.config, "signals_snapshot_url_token", lambda: "")
    monkeypatch.setattr(compute.config, "signals_snapshot_path", lambda: dest)
    monkeypatch.setattr(compute, "_fetch_signals_url", lambda url, token, **kw: dict(payload))

    result = compute._load_signals_snapshot()

    assert result == payload
    assert dest.exists()
    assert json.loads(dest.read_text(encoding="utf-8")) == payload


def test_experiment_snapshot_write_through(tmp_path, monkeypatch) -> None:
    dest = tmp_path / "rollup.json"
    payload = {"families": [{"tf": "5m", "edge": 1.2}]}
    body = json.dumps(payload)
    monkeypatch.setattr(compute.config, "experiment_snapshot_url", lambda: "https://example.test/rollup")
    monkeypatch.setattr(compute.config, "experiment_snapshot_url_token", lambda: "")
    monkeypatch.setattr(compute.config, "experiment_snapshot_path", lambda: dest)
    monkeypatch.setattr(compute.config, "experiment_cache_ttl_secs", lambda: 900)
    monkeypatch.setattr(compute, "_fetch_experiment_url", lambda url, token, **kw: body)

    result = compute._load_experiment_snapshot()

    assert result == payload
    assert dest.exists()
    # The raw body is persisted verbatim (no re-serialisation drift).
    assert dest.read_text(encoding="utf-8") == body


def test_tradingview_credential_write_through(tmp_path, monkeypatch) -> None:
    dest = tmp_path / "nested" / "credential_health.json"
    payload = {
        "schema_version": "1",
        "overall_severity": "warn",
        "probes": [
            {
                "name": "tv_storage_state_age",
                "severity": "warn",
                "message": "ageing",
                "details": {"validated_at": "2026-06-20T00:00:00+00:00", "age_hours": 60.0},
            }
        ],
    }
    monkeypatch.setattr(
        compute.config, "tradingview_credential_snapshot_url", lambda: "https://example.test/tv"
    )
    monkeypatch.setattr(compute.config, "tradingview_credential_snapshot_url_token", lambda: "")
    monkeypatch.setattr(compute.config, "tradingview_credential_snapshot_path", lambda: dest)
    monkeypatch.setattr(compute.config, "tradingview_credential_cache_ttl_secs", lambda: 3600)
    monkeypatch.setattr(
        compute, "_fetch_tradingview_credential_url", lambda url, token, **kw: dict(payload)
    )

    result = compute._load_tradingview_credential_snapshot()

    assert result == payload
    assert dest.exists()
    assert json.loads(dest.read_text(encoding="utf-8")) == payload


def test_tradingview_credential_no_write_through_on_fetch_failure(tmp_path, monkeypatch) -> None:
    dest = tmp_path / "credential_health.json"
    monkeypatch.setattr(
        compute.config, "tradingview_credential_snapshot_url", lambda: "https://example.test/tv"
    )
    monkeypatch.setattr(compute.config, "tradingview_credential_snapshot_url_token", lambda: "")
    monkeypatch.setattr(compute.config, "tradingview_credential_snapshot_path", lambda: dest)
    monkeypatch.setattr(compute.config, "tradingview_credential_cache_ttl_secs", lambda: 3600)
    monkeypatch.setattr(compute, "_fetch_tradingview_credential_url", lambda url, token, **kw: None)

    result = compute._load_tradingview_credential_snapshot()

    assert result == {}
    assert not dest.exists()


def test_experiment_history_write_through(tmp_path, monkeypatch) -> None:
    dest = tmp_path / "history.jsonl"
    rows = [
        {"captured_at": "2026-06-20", "edge": 1.0},
        {"captured_at": "2026-06-21", "edge": 1.1},
    ]
    body = "\n".join(json.dumps(r) for r in rows) + "\n"
    monkeypatch.setattr(compute.config, "experiment_history_url", lambda: "https://example.test/history")
    monkeypatch.setattr(compute.config, "experiment_history_url_token", lambda: "")
    monkeypatch.setattr(compute.config, "experiment_history_path", lambda: dest)
    monkeypatch.setattr(compute.config, "experiment_cache_ttl_secs", lambda: 900)
    monkeypatch.setattr(compute.config, "experiment_history_max_days", lambda: 30)
    monkeypatch.setattr(compute, "_fetch_experiment_url", lambda url, token, **kw: body)

    result = compute._load_experiment_history()

    assert len(result) == 2
    assert dest.exists()
    assert dest.read_text(encoding="utf-8") == body


def test_fetch_experiment_url_uses_raw_accept_for_github_contents_api(monkeypatch) -> None:
    captured_headers: dict[str, str] = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def read(self) -> bytes:
            return b'{"ok": true}'

    def _fake_urlopen(req, timeout=10.0):
        del timeout
        captured_headers.update(req.headers)
        return _Resp()

    monkeypatch.setattr(compute.urllib.request, "urlopen", _fake_urlopen)

    body = compute._fetch_experiment_url(
        "https://API.GITHUB.COM/repos/skippALGO/skipp-algo/contents/artifacts/rollup.json",
        "",
    )

    assert body == '{"ok": true}'
    assert captured_headers.get("Accept") == "application/vnd.github.raw+json"


def test_fetch_experiment_url_does_not_match_query_string_substrings(monkeypatch) -> None:
    captured_headers: dict[str, str] = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def read(self) -> bytes:
            return b'{"ok": true}'

    def _fake_urlopen(req, timeout=10.0):
        del timeout
        captured_headers.update(req.headers)
        return _Resp()

    monkeypatch.setattr(compute.urllib.request, "urlopen", _fake_urlopen)

    body = compute._fetch_experiment_url(
        "https://example.test/rollup.json?next=api.github.com/repos/skippALGO/skipp-algo/contents/x",
        "",
    )

    assert body == '{"ok": true}'
    assert captured_headers.get("Accept") == "application/json"


# ---------------------------------------------------------------------------
# smc-signals-producer direct-service fetch tests
# ---------------------------------------------------------------------------


def test_signals_service_fetch_takes_precedence_and_writes_through(
    tmp_path, monkeypatch
) -> None:
    """When SIGNALS_SERVICE_URL is set, the producer is consulted first."""
    dest = tmp_path / "signals.json"
    payload = {"signals": [{"symbol": "AAPL", "level": "A1"}], "signal_count": 1}

    captured: list[tuple[str, str]] = []

    def _fake_fetch_service(base: str, token: str, timeout: float = 10.0):
        captured.append((base, token))
        return dict(payload)

    monkeypatch.setattr(compute.config, "signals_service_url", lambda: "smc-signals-producer.railway.internal")
    monkeypatch.setattr(compute.config, "signals_internal_token", lambda: "secret-token")
    monkeypatch.setattr(compute.config, "signals_snapshot_url", lambda: "https://example.test/signals")
    monkeypatch.setattr(compute.config, "signals_snapshot_path", lambda: dest)
    monkeypatch.setattr(compute, "_fetch_signals_service", _fake_fetch_service)
    # Make the public URL fail loudly if it were ever reached.
    def _fail_if_public_url_reached(url: str, token: str, **kw):
        raise AssertionError("public URL path should not be reached when producer succeeds")
    monkeypatch.setattr(compute, "_fetch_signals_url", _fail_if_public_url_reached)

    result = compute._load_signals_snapshot()

    assert result == payload
    assert captured == [("smc-signals-producer.railway.internal", "secret-token")]
    assert dest.exists()
    assert json.loads(dest.read_text(encoding="utf-8")) == payload


def test_signals_service_fetch_falls_back_to_url(tmp_path, monkeypatch) -> None:
    """A failing producer fetch falls back to SIGNALS_SNAPSHOT_URL."""
    dest = tmp_path / "signals.json"
    payload = {"signals": [{"symbol": "TSLA", "level": "A0"}], "signal_count": 1}

    monkeypatch.setattr(compute.config, "signals_service_url", lambda: "smc-signals-producer.railway.internal")
    monkeypatch.setattr(compute.config, "signals_internal_token", lambda: "")
    monkeypatch.setattr(compute.config, "signals_snapshot_url", lambda: "https://example.test/signals")
    monkeypatch.setattr(compute.config, "signals_snapshot_path", lambda: dest)
    monkeypatch.setattr(compute, "_fetch_signals_service", lambda base, token, **kw: None)
    monkeypatch.setattr(compute, "_fetch_signals_url", lambda url, token, **kw: dict(payload))

    result = compute._load_signals_snapshot()

    assert result == payload
    assert dest.exists()


def test_signals_service_fetch_falls_back_to_path(tmp_path, monkeypatch) -> None:
    """A failing producer fetch with no URL falls back to the local path."""
    dest = tmp_path / "signals.json"
    payload = {"signals": [{"symbol": "NVDA", "level": "A1"}], "signal_count": 1}
    dest.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(compute.config, "signals_service_url", lambda: "smc-signals-producer.railway.internal")
    monkeypatch.setattr(compute.config, "signals_internal_token", lambda: "")
    monkeypatch.setattr(compute.config, "signals_snapshot_url", lambda: "")
    monkeypatch.setattr(compute.config, "signals_snapshot_path", lambda: dest)
    monkeypatch.setattr(compute, "_fetch_signals_service", lambda base, token, **kw: None)

    result = compute._load_signals_snapshot()

    assert result == payload


def test_signals_service_url_to_full_with_host_and_url() -> None:
    assert compute._signals_service_url_to_full("smc-signals-producer.railway.internal") == (
        "http://smc-signals-producer.railway.internal/signals.json"
    )
    assert compute._signals_service_url_to_full("http://producer:8080") == (
        "http://producer:8080/signals.json"
    )
    assert compute._signals_service_url_to_full("https://producer/path/") == (
        "https://producer/path/signals.json"
    )


def test_is_valid_service_url() -> None:
    assert compute._is_valid_service_url("smc-signals-producer.railway.internal") is True
    assert compute._is_valid_service_url("smc-signals-producer.railway.internal:8080") is True
    assert compute._is_valid_service_url("http://smc-signals-producer.railway.internal") is True
    assert compute._is_valid_service_url("http://host") is False
    assert compute._is_valid_service_url("http://example.com") is False
    assert compute._is_valid_service_url("https://host") is True
    assert compute._is_valid_service_url("example.com") is False
    assert compute._is_valid_service_url("   ") is False
    assert compute._is_valid_service_url("") is False
    assert compute._is_valid_service_url("ftp://host") is False
