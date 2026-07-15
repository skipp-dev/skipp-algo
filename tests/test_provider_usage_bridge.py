"""Tests for services.live_overlay_daemon.provider_usage_bridge."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.live_overlay_daemon import provider_usage_bridge as bridge


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    bridge._cached = None
    bridge._cached_at_monotonic = 0.0
    yield
    bridge._cached = None
    bridge._cached_at_monotonic = 0.0


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_coerce_reduces_to_current_month_per_provider() -> None:
    out = bridge._coerce(
        {
            "updated_at": "2026-07-07T10:00:00Z",
            "current_month": "2026-07",
            "months": {
                "2026-06": {"fmp": {"calls": 1, "bytes": 10, "records": 1}},
                "2026-07": {
                    "fmp": {"calls": 553, "bytes": 142_990_000_000, "records": 9},
                    "massive": {"calls": 40, "bytes": 5000, "records": 0, "rate_limit_hits": 4},
                },
            },
        }
    )
    assert out["loaded"] == 1.0
    assert out["current_month"] == "2026-07"
    assert out["providers"]["fmp"]["bytes"] == 142_990_000_000
    assert out["providers"]["fmp"]["calls"] == 553
    assert out["providers"]["massive"]["rate_limit_hits"] == 4
    assert out["providers"]["fmp"]["rate_limit_hits"] == 0  # absent field -> 0
    assert "2026-06" not in out["providers"]  # only the current month is exposed


def test_coerce_falls_back_to_newest_month_when_current_missing() -> None:
    out = bridge._coerce(
        {"current_month": "2026-09", "months": {"2026-07": {"fmp": {"bytes": 5}}, "2026-08": {"fmp": {"bytes": 9}}}}
    )
    assert out["current_month"] == "2026-08"
    assert out["providers"]["fmp"]["bytes"] == 9


def test_coerce_empty_on_no_months() -> None:
    assert bridge._coerce({"months": {}})["loaded"] == 0.0
    assert bridge._coerce({})["loaded"] == 0.0


def test_load_raw_reads_local_snapshot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = tmp_path / "provider_usage.json"
    _write(p, {"current_month": "2026-07", "months": {"2026-07": {"fmp": {"bytes": 42}}}})
    monkeypatch.setattr(bridge.config, "provider_usage_snapshot_url", lambda: "")
    monkeypatch.setattr(bridge.config, "provider_usage_snapshot_path", lambda: p)
    out = bridge._load_raw()
    assert out["providers"]["fmp"]["bytes"] == 42


def test_load_raw_missing_snapshot_is_loaded_zero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(bridge.config, "provider_usage_snapshot_url", lambda: "")
    monkeypatch.setattr(bridge.config, "provider_usage_snapshot_path", lambda: tmp_path / "nope.json")
    out = bridge._load_raw()
    assert out["loaded"] == 0.0
    assert out["error"] == "missing_snapshot"


def test_load_raw_prefers_url_over_local(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    local = tmp_path / "provider_usage.json"
    _write(local, {"current_month": "2026-07", "months": {"2026-07": {"fmp": {"bytes": 1}}}})
    monkeypatch.setattr(bridge.config, "provider_usage_snapshot_url", lambda: "https://example/u.json")
    monkeypatch.setattr(bridge.config, "provider_usage_snapshot_url_token", lambda: "")
    monkeypatch.setattr(bridge.config, "provider_usage_snapshot_path", lambda: local)
    monkeypatch.setattr(
        bridge, "_fetch_url",
        lambda url, token, timeout=10.0: json.dumps(
            {"current_month": "2026-07", "months": {"2026-07": {"fmp": {"bytes": 999}}}}
        ),
    )
    out = bridge._load_raw()
    assert out["providers"]["fmp"]["bytes"] == 999  # URL wins


def test_load_raw_falls_back_to_local_on_url_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    local = tmp_path / "provider_usage.json"
    _write(local, {"current_month": "2026-07", "months": {"2026-07": {"fmp": {"bytes": 7}}}})
    monkeypatch.setattr(bridge.config, "provider_usage_snapshot_url", lambda: "https://example/u.json")
    monkeypatch.setattr(bridge.config, "provider_usage_snapshot_url_token", lambda: "")
    monkeypatch.setattr(bridge.config, "provider_usage_snapshot_path", lambda: local)
    monkeypatch.setattr(bridge, "_fetch_url", lambda *a, **k: None)  # URL down
    out = bridge._load_raw()
    assert out["providers"]["fmp"]["bytes"] == 7  # local fallback


def test_fetch_url_rejects_non_https() -> None:
    assert bridge._fetch_url("http://insecure/u.json", "") is None




def test_failed_load_preserves_last_good_snapshot(monkeypatch, tmp_path):
    """A transient load failure must keep the last good provider-usage snapshot."""
    p = tmp_path / "provider_usage.json"
    _write(p, {"current_month": "2026-07", "months": {"2026-07": {"fmp": {"bytes": 42}}}})
    monkeypatch.setattr(bridge.config, "provider_usage_snapshot_url", lambda: "")
    monkeypatch.setattr(bridge.config, "provider_usage_snapshot_path", lambda: p)
    first = bridge.snapshot()
    assert first["loaded"] == 1.0
    assert first["providers"]["fmp"]["bytes"] == 42

    bad = tmp_path / "provider_usage_bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(bridge.config, "provider_usage_snapshot_path", lambda: bad)
    bridge._cached_at_monotonic = 0.0

    second = bridge.snapshot()
    assert second["loaded"] == 1.0
    assert second["providers"]["fmp"]["bytes"] == 42


def test_failed_load_without_prior_cache_returns_error_payload(monkeypatch, tmp_path):
    """With no prior good snapshot, a failure must still be fail-soft."""
    bad = tmp_path / "provider_usage.json"
    bad.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(bridge.config, "provider_usage_snapshot_url", lambda: "")
    monkeypatch.setattr(bridge.config, "provider_usage_snapshot_path", lambda: bad)
    snap = bridge.snapshot()
    assert snap["loaded"] == 0.0
    assert snap["error"] == "unreadable_snapshot"
def test_metrics_emit_provider_usage_gauges(monkeypatch: pytest.MonkeyPatch) -> None:
    """render path emits per-provider byte/call gauges + the FMP limit."""
    from services.live_overlay_daemon import metrics

    monkeypatch.setattr(
        metrics.provider_usage_bridge, "snapshot",
        lambda: {
            "loaded": 1.0, "error": "", "current_month": "2026-07",
            "updated_at": "2026-07-07T10:00:00Z", "snapshot_age_seconds": 12.0,
            "providers": {
                "fmp": {"calls": 553, "bytes": 142_990_000_000, "records": 9},
                "massive": {"calls": 40, "bytes": 5000, "records": 0, "rate_limit_hits": 4},
            },
        },
    )
    monkeypatch.setattr(metrics.config, "fmp_monthly_bandwidth_limit_bytes", lambda: 150_000_000_000)
    text = "\n".join(metrics._render_provider_usage_metrics())
    assert "live_overlay_provider_usage_loaded 1.0" in text
    assert 'live_overlay_provider_usage_bytes{provider="fmp"} 142990000000' in text
    assert 'live_overlay_provider_usage_calls{provider="fmp"} 553' in text
    assert 'live_overlay_provider_usage_rate_limit_hits{provider="massive"} 4' in text
    assert 'live_overlay_provider_usage_rate_limit_hits{provider="fmp"} 0' in text
    assert 'live_overlay_provider_bandwidth_limit_bytes{provider="fmp"} 150000000000' in text
    # 142.99 GB / 150 GB ~= 95% -> the dashboard/alert ratio is computable.


def test_snapshot_age_recomputed_each_call_while_cached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # snapshot_age_seconds must reflect true wall-clock age on every call, not
    # the value frozen at load time, even while the payload is TTL-cached.
    p = tmp_path / "provider_usage.json"
    _write(
        p,
        {
            "updated_at": "2026-07-07T10:00:00Z",
            "current_month": "2026-07",
            "months": {"2026-07": {"fmp": {"bytes": 42}}},
        },
    )
    monkeypatch.setattr(bridge.config, "provider_usage_snapshot_url", lambda: "")
    monkeypatch.setattr(bridge.config, "provider_usage_snapshot_path", lambda: p)
    monkeypatch.setattr(bridge.config, "experiment_cache_ttl_secs", lambda: 9999.0)

    fake = {"t": 2_000_000_000.0}  # year 2033 wall clock, well after updated_at
    monkeypatch.setattr(bridge.time, "time", lambda: fake["t"])

    age1 = bridge.snapshot()["snapshot_age_seconds"]  # loads + caches
    fake["t"] += 120.0  # wall clock advances; monotonic (TTL) unchanged -> cache warm
    age2 = bridge.snapshot()["snapshot_age_seconds"]

    assert age1 is not None and age2 is not None
    assert age2 == pytest.approx(age1 + 120.0)  # recomputed, not frozen at load
