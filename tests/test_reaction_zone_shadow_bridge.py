"""Tests for the daemon-side reaction_zone_shadow_bridge (URL/local, fail-soft)
plus its metrics render — mirrors test_sweep_trap_shadow_bridge, adapted to the
reaction snapshot's nested by_direction schema and ISO updated_at timestamp."""
from __future__ import annotations

import base64
import datetime
import json
import time
from pathlib import Path

import pytest

from services.live_overlay_daemon import metrics as metrics_mod
from services.live_overlay_daemon import reaction_zone_shadow_bridge as bridge


@pytest.fixture(autouse=True)
def _reset_cache_and_env(monkeypatch):
    # Never hit a real URL; isolate the module cache between tests.
    monkeypatch.setenv("REACTION_ZONE_SHADOW_SNAPSHOT_URL", "")
    bridge._reset_cache_for_tests()
    yield
    bridge._reset_cache_for_tests()


def _snapshot_payload(**overrides) -> dict:
    """A realistic reaction_zone_shadow.json payload (producer schema)."""
    payload = {
        "n_reaction_samples": 120,
        "by_direction": {
            "bull": {
                "n": 60,
                "best_variant": "level_cross",
                "variants": {
                    "old_band": {"n": 60, "n_confirmed": 20, "lift": 0.15, "verdict": "SHADOW"},
                    "level_cross": {
                        "n": 60, "n_confirmed": 30, "lift": 0.4, "verdict": "PROMOTABLE",
                    },
                    "mirrored_band": {"n": 60, "n_confirmed": 15, "lift": 0.07, "verdict": "SHADOW"},
                },
            },
            "bear": {
                "n": 60,
                "best_variant": "old_band",
                "variants": {
                    "old_band": {"n": 60, "n_confirmed": 18, "lift": 0.02, "verdict": "SHADOW"},
                    "level_cross": {"n": 60, "n_confirmed": 22, "lift": -0.01, "verdict": "SHADOW"},
                    "mirrored_band": {
                        "n": 60, "n_confirmed": 5, "lift": None, "verdict": "INCONCLUSIVE",
                    },
                },
            },
        },
        "updated_at": "2026-07-27T12:00:00Z",
        "config": {"min_samples": 40, "lift_promote_threshold": 0.05},
    }
    payload.update(overrides)
    return payload


def _write(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "reaction_zone_shadow.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


# --------------------------------------------------------------------------- #
# GitHub Contents-API handling (base64 envelope)
# --------------------------------------------------------------------------- #


def test_is_github_contents_api_url():
    assert bridge._is_github_contents_api_url(
        "https://api.github.com/repos/o/r/contents/a/b.json?ref=bot/x"
    )
    assert not bridge._is_github_contents_api_url(
        "https://raw.githubusercontent.com/o/r/bot/x/a/b.json"
    )
    assert not bridge._is_github_contents_api_url("https://example.com/x.json")


def test_contents_api_url_requests_raw_accept(monkeypatch):
    """The Contents-API URL must send Accept: vnd.github.raw+json so GitHub
    returns the file, not the base64 envelope (the silent-green bug)."""
    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"n_reaction_samples": 1}'

    def _fake_urlopen(request, timeout=10.0):
        captured["accept"] = request.headers.get("Accept")
        return _Resp()

    monkeypatch.setattr(bridge.urllib.request, "urlopen", _fake_urlopen)
    bridge._fetch_url("https://api.github.com/repos/o/r/contents/x.json?ref=b", "tok")
    assert captured["accept"] == "application/vnd.github.raw+json"


def test_decode_github_envelope():
    inner = {"n_reaction_samples": 5, "updated_at": "2026-07-27T00:00:00Z"}
    env = {
        "name": "reaction_zone_shadow.json",
        "encoding": "base64",
        "content": base64.b64encode(json.dumps(inner).encode()).decode(),
    }
    assert bridge._decode_github_envelope(env) == inner
    # A raw snapshot (no envelope) is passed through as not-an-envelope.
    assert bridge._decode_github_envelope({"n_reaction_samples": 5}) is None


def test_load_raw_decodes_base64_envelope(monkeypatch):
    """Belt-and-suspenders: even if a proxy returns the base64 envelope, the
    bridge must decode it instead of coercing an empty (silent-green) snapshot."""
    inner = _snapshot_payload()
    env = json.dumps(
        {"encoding": "base64", "content": base64.b64encode(json.dumps(inner).encode()).decode()}
    )
    monkeypatch.setenv(
        "REACTION_ZONE_SHADOW_SNAPSHOT_URL",
        "https://api.github.com/repos/o/r/contents/x.json?ref=b",
    )
    monkeypatch.setattr(bridge, "_fetch_url", lambda *a, **k: env)
    snap = bridge.snapshot()
    assert snap["loaded"] == 1.0
    assert snap["n_samples"] == 120.0
    assert snap["bull_best_variant"] == "level_cross"
    assert snap["verdict_code"] == 2.0


# --------------------------------------------------------------------------- #
# Fail-soft loading
# --------------------------------------------------------------------------- #


def test_missing_snapshot_is_fail_soft(monkeypatch, tmp_path):
    monkeypatch.setenv("REACTION_ZONE_SHADOW_SNAPSHOT_PATH", str(tmp_path / "nope.json"))
    snap = bridge.snapshot()
    assert snap["loaded"] == 0.0
    assert snap["error"] == "missing_snapshot"
    # Shape is still complete so metric rendering never KeyErrors.
    assert snap["verdict"] == ""
    assert snap["verdict_code"] == 0.0
    assert snap["generated_at_unix"] == 0.0
    assert snap["bull_best_variant"] == ""
    assert snap["bear_best_lift"] == 0.0


def test_unreadable_snapshot_is_fail_soft(monkeypatch, tmp_path):
    p = tmp_path / "reaction_zone_shadow.json"
    p.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("REACTION_ZONE_SHADOW_SNAPSHOT_PATH", str(p))
    snap = bridge.snapshot()
    assert snap["loaded"] == 0.0
    assert snap["error"] == "unreadable_snapshot"


def test_non_dict_snapshot_is_fail_soft(monkeypatch, tmp_path):
    p = tmp_path / "reaction_zone_shadow.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    monkeypatch.setenv("REACTION_ZONE_SHADOW_SNAPSHOT_PATH", str(p))
    snap = bridge.snapshot()
    assert snap["loaded"] == 0.0
    assert snap["error"] == "malformed_snapshot"


def test_failed_load_preserves_last_good_snapshot(monkeypatch, tmp_path):
    """A transient load failure must not evict a previously-good snapshot."""
    p = _write(tmp_path, _snapshot_payload())
    monkeypatch.setenv("REACTION_ZONE_SHADOW_SNAPSHOT_PATH", str(p))
    first = bridge.snapshot()
    assert first["loaded"] == 1.0
    assert first["n_samples"] == 120.0

    bad = tmp_path / "reaction_zone_shadow_bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("REACTION_ZONE_SHADOW_SNAPSHOT_PATH", str(bad))
    bridge._cached_at_monotonic = 0.0

    second = bridge.snapshot()
    assert second["loaded"] == 1.0
    assert second["n_samples"] == 120.0


def test_failed_load_without_prior_cache_returns_error_payload(monkeypatch, tmp_path):
    bad = tmp_path / "reaction_zone_shadow.json"
    bad.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("REACTION_ZONE_SHADOW_SNAPSHOT_PATH", str(bad))
    snap = bridge.snapshot()
    assert snap["loaded"] == 0.0
    assert snap["error"] == "unreadable_snapshot"


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #


def test_valid_snapshot_is_normalized(monkeypatch, tmp_path):
    p = _write(tmp_path, _snapshot_payload())
    monkeypatch.setenv("REACTION_ZONE_SHADOW_SNAPSHOT_PATH", str(p))
    snap = bridge.snapshot()
    assert snap["loaded"] == 1.0
    assert snap["date"] == "2026-07-27"
    assert snap["n_samples"] == 120.0
    assert snap["min_samples"] == 40.0
    assert snap["lift_promote_threshold"] == 0.05
    # Per-direction best variant + its lift and verdict.
    assert snap["bull_best_variant"] == "level_cross"
    assert snap["bull_best_lift"] == 0.4
    assert snap["bull_best_verdict"] == "PROMOTABLE"
    assert snap["bull_best_verdict_code"] == 2.0
    assert snap["bear_best_variant"] == "old_band"
    assert snap["bear_best_lift"] == 0.02
    assert snap["bear_best_verdict"] == "SHADOW"
    # Overall = strongest cell across both directions.
    assert snap["verdict"] == "PROMOTABLE"
    assert snap["verdict_code"] == 2.0
    # updated_at ISO parsed to the matching unix epoch.
    expected = datetime.datetime(2026, 7, 27, 12, 0, 0, tzinfo=datetime.UTC).timestamp()
    assert snap["generated_at_unix"] == expected


def test_updated_at_missing_yields_zero_age(monkeypatch, tmp_path):
    """No updated_at (or None) keeps generated_at_unix 0 so the stale gauge/age
    render as unknown, not fresh — the reaction analog of the no-data seed."""
    p = _write(tmp_path, _snapshot_payload(updated_at=None))
    monkeypatch.setenv("REACTION_ZONE_SHADOW_SNAPSHOT_PATH", str(p))
    snap = bridge.snapshot()
    assert snap["loaded"] == 1.0
    assert snap["generated_at_unix"] == 0.0
    assert snap["date"] == ""


def test_malformed_updated_at_is_fail_soft(monkeypatch, tmp_path):
    p = _write(tmp_path, _snapshot_payload(updated_at="not-a-timestamp"))
    monkeypatch.setenv("REACTION_ZONE_SHADOW_SNAPSHOT_PATH", str(p))
    snap = bridge.snapshot()
    assert snap["loaded"] == 1.0
    assert snap["generated_at_unix"] == 0.0


def test_empty_by_direction_coerces_to_zero(monkeypatch, tmp_path):
    """A snapshot with no samples/directions must not raise; all cells zero."""
    p = _write(
        tmp_path,
        {"n_reaction_samples": 0, "by_direction": {}, "updated_at": None,
         "config": {"min_samples": 40, "lift_promote_threshold": 0.05}},
    )
    monkeypatch.setenv("REACTION_ZONE_SHADOW_SNAPSHOT_PATH", str(p))
    snap = bridge.snapshot()
    assert snap["loaded"] == 1.0
    assert snap["n_samples"] == 0.0
    assert snap["verdict"] == "INCONCLUSIVE"
    assert snap["verdict_code"] == 0.0
    assert snap["bull_best_variant"] == ""
    assert snap["bear_best_lift"] == 0.0


def test_overall_verdict_is_max_across_all_cells(monkeypatch, tmp_path):
    """Even when the best_variant (by lift) is only SHADOW, a PROMOTABLE cell in
    another variant still lifts the overall verdict to PROMOTABLE."""
    payload = _snapshot_payload()
    # Bull best_variant points at a SHADOW cell, but another variant is PROMOTABLE.
    payload["by_direction"]["bull"]["best_variant"] = "old_band"
    payload["by_direction"]["bull"]["variants"]["level_cross"]["verdict"] = "PROMOTABLE"
    payload["by_direction"]["bull"]["variants"]["old_band"]["verdict"] = "SHADOW"
    p = _write(tmp_path, payload)
    monkeypatch.setenv("REACTION_ZONE_SHADOW_SNAPSHOT_PATH", str(p))
    snap = bridge.snapshot()
    assert snap["bull_best_variant"] == "old_band"
    assert snap["bull_best_verdict"] == "SHADOW"
    assert snap["verdict_code"] == 2.0  # overall still PROMOTABLE


def test_snapshot_is_ttl_cached(monkeypatch, tmp_path):
    """A second call inside the TTL returns the cached snapshot without re-reading."""
    p = _write(tmp_path, _snapshot_payload(n_reaction_samples=10))
    monkeypatch.setenv("REACTION_ZONE_SHADOW_SNAPSHOT_PATH", str(p))
    first = bridge.snapshot()
    p.write_text(json.dumps(_snapshot_payload(n_reaction_samples=99)), encoding="utf-8")
    second = bridge.snapshot()
    assert second["n_samples"] == first["n_samples"] == 10.0
    bridge._reset_cache_for_tests()
    assert bridge.snapshot()["n_samples"] == 99.0


# --------------------------------------------------------------------------- #
# Metrics render (gauge output)
# --------------------------------------------------------------------------- #


def _normalized(**overrides) -> dict:
    """The normalized shape the render consumes (bridge.snapshot() output)."""
    snap = {
        "loaded": 1.0,
        "generated_at_unix": time.time() - 60.0,
        "date": "2026-07-27",
        "n_samples": 120.0,
        "min_samples": 40.0,
        "lift_promote_threshold": 0.05,
        "bull_best_variant": "level_cross",
        "bull_best_lift": 0.4,
        "bull_best_verdict": "PROMOTABLE",
        "bull_best_verdict_code": 2.0,
        "bear_best_variant": "old_band",
        "bear_best_lift": 0.02,
        "bear_best_verdict": "SHADOW",
        "bear_best_verdict_code": 1.0,
        "verdict": "PROMOTABLE",
        "verdict_code": 2.0,
        "error": "",
    }
    snap.update(overrides)
    return snap


def test_render_emits_reaction_zone_gauges_when_fresh(monkeypatch):
    monkeypatch.setattr(metrics_mod.reaction_zone_shadow_bridge, "snapshot", lambda: _normalized())
    body = "\n".join(metrics_mod._render_reaction_zone_shadow_metrics())
    assert "live_overlay_reaction_zone_shadow_loaded 1.0" in body
    assert "live_overlay_reaction_zone_shadow_snapshot_age_known 1.0" in body
    assert "live_overlay_reaction_zone_shadow_snapshot_stale 0.0" in body
    assert "live_overlay_reaction_zone_shadow_sample_count 120.0" in body
    assert 'live_overlay_reaction_zone_shadow_best_lift{direction="bull"} 0.4' in body
    assert 'live_overlay_reaction_zone_shadow_best_lift{direction="bear"} 0.02' in body
    assert 'live_overlay_reaction_zone_shadow_verdict_code{verdict="PROMOTABLE"} 2.0' in body
    assert "live_overlay_reaction_zone_shadow_evidence_info{" in body


def test_render_is_fail_soft_when_missing(monkeypatch):
    """A missing/unreadable snapshot degrades to safe gauge values, never crashes."""
    empty = bridge._empty(0.0, "missing_snapshot")
    monkeypatch.setattr(metrics_mod.reaction_zone_shadow_bridge, "snapshot", lambda: empty)
    body = "\n".join(metrics_mod._render_reaction_zone_shadow_metrics())
    assert "live_overlay_reaction_zone_shadow_loaded 0.0" in body
    assert "live_overlay_reaction_zone_shadow_snapshot_age_known 0.0" in body
    assert "live_overlay_reaction_zone_shadow_snapshot_stale 0.0" in body
    assert 'live_overlay_reaction_zone_shadow_verdict_code{verdict="unknown"} 0.0' in body


def test_render_stale_gauge_fires_past_max_age(monkeypatch):
    snap = _normalized(generated_at_unix=time.time() - 200 * 3600)
    monkeypatch.setattr(metrics_mod.reaction_zone_shadow_bridge, "snapshot", lambda: snap)
    body = "\n".join(metrics_mod._render_reaction_zone_shadow_metrics())
    assert "live_overlay_reaction_zone_shadow_snapshot_age_known 1.0" in body
    assert "live_overlay_reaction_zone_shadow_snapshot_stale 1.0" in body


def test_render_no_data_is_not_stale(monkeypatch):
    """generated_at_unix=0 → age unknown, so stale must NOT fire (gt-0-inert avoided)."""
    snap = _normalized(loaded=1.0, generated_at_unix=0.0, verdict="INCONCLUSIVE", verdict_code=0.0)
    monkeypatch.setattr(metrics_mod.reaction_zone_shadow_bridge, "snapshot", lambda: snap)
    body = "\n".join(metrics_mod._render_reaction_zone_shadow_metrics())
    assert "live_overlay_reaction_zone_shadow_snapshot_age_known 0.0" in body
    assert "live_overlay_reaction_zone_shadow_snapshot_stale 0.0" in body


def test_committed_no_data_seed_loads_but_reports_zero_age(monkeypatch):
    """The committed no-data seed (artifacts/monitoring/reaction_zone_shadow.json)
    loads without error — so the daemon shows loaded=1 before the eval first
    produces samples — but keeps generated_at_unix 0 so the age/stale gauges read
    unknown, not fresh. Mirrors sweep-trap's committed seed. Guards the seed file
    against deletion/corruption."""
    # The autouse fixture blanks the URL; leave _PATH unset so the REAL committed
    # seed at the default repo path is read.
    monkeypatch.delenv("REACTION_ZONE_SHADOW_SNAPSHOT_PATH", raising=False)
    bridge._reset_cache_for_tests()
    snap = bridge.snapshot()
    assert snap["loaded"] == 1.0
    assert snap["generated_at_unix"] == 0.0
    assert snap["verdict"] == "INCONCLUSIVE"
    assert snap["verdict_code"] == 0.0
    assert snap["n_samples"] == 0.0
