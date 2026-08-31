"""Tests for the daemon-side pine_library_version_bridge (URL/local, fail-soft)
and the metrics renderer's drift/known gating."""
from __future__ import annotations

import base64
import json

import pytest

from services.live_overlay_daemon import pine_library_version_bridge as bridge

# --------------------------------------------------------------------------- #
# GitHub Contents-API handling (base64 envelope — mirrors evidence-freshness)
# --------------------------------------------------------------------------- #


def test_is_github_contents_api_url():
    assert bridge._is_github_contents_api_url(
        "https://api.github.com/repos/o/r/contents/artifacts/monitoring/pine_library_versions.json?ref=bot/x"
    )
    assert not bridge._is_github_contents_api_url(
        "https://raw.githubusercontent.com/o/r/bot/x/pine_library_versions.json"
    )
    assert not bridge._is_github_contents_api_url("https://example.com/x.json")


def test_contents_api_url_requests_raw_accept(monkeypatch):
    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"generated_at_unix": 1.0}'

    def _fake_urlopen(request, timeout=10.0):
        captured["accept"] = request.headers.get("Accept")
        return _Resp()

    monkeypatch.setattr(bridge.urllib.request, "urlopen", _fake_urlopen)
    bridge._fetch_url("https://api.github.com/repos/o/r/contents/x.json?ref=b", "tok")
    assert captured["accept"] == "application/vnd.github.raw+json"


def test_decode_github_envelope():
    inner = {"generated_at_unix": 5.0, "anyDrift": True}
    env = {
        "name": "pine_library_versions.json",
        "encoding": "base64",
        "content": base64.b64encode(json.dumps(inner).encode()).decode(),
    }
    assert bridge._decode_github_envelope(env) == inner
    assert bridge._decode_github_envelope({"generated_at_unix": 5.0}) is None


# --------------------------------------------------------------------------- #
# Coercion + drift semantics
# --------------------------------------------------------------------------- #


def _raw_snapshot() -> dict:
    return {
        "generatedAt": "2026-07-13T16:00:00.000Z",
        "generated_at_unix": 1_783_958_400,
        "libraries": [
            {
                "name": "smc_micro_profiles_generated",
                "tvVersion": 152,
                "tvVersionKnown": True,
                "dataAsOf": "2026-07-20",
                "dataAsOfUnix": 1_784_505_600,
                "dataAsOfKnown": True,
                "consumers": [{"file": "SMC_Decision_Board.pine", "pinnedVersion": 1, "drift": True}],
                "anyConsumerDrift": True,
            },
            {
                "name": "smc_bus_private",
                "tvVersion": 0,
                "tvVersionKnown": False,
                "consumers": [{"file": "SMC_Long_Dip_Suite.pine", "pinnedVersion": 1, "drift": False}],
                "anyConsumerDrift": False,
            },
        ],
        "anyDrift": True,
        "librariesProbed": 1,
        "librariesDrifted": 1,
        "facadeError": "",
    }


def test_coerce_normalizes_drift_and_known_flags():
    out = bridge._coerce(_raw_snapshot())
    assert out["loaded"] == 1.0
    assert out["any_drift"] == 1.0
    assert out["libraries_probed"] == 1.0
    assert out["libraries_drifted"] == 1.0
    micro = out["libraries"][0]
    assert micro["tv_version"] == 152.0
    assert micro["tv_version_known"] == 1.0
    assert micro["data_asof"] == "2026-07-20"
    assert micro["data_asof_unix"] == 1_784_505_600.0
    assert micro["data_asof_known"] == 1.0
    assert micro["consumers"][0]["drift"] == 1.0
    bus = out["libraries"][1]
    assert bus["tv_version_known"] == 0.0
    assert bus["consumers"][0]["drift"] == 0.0


def test_coerce_tolerates_missing_and_malformed_keys():
    out = bridge._coerce({})
    assert out["loaded"] == 1.0
    assert out["libraries"] == []
    assert out["any_drift"] == 0.0
    # A non-dict library entry is skipped, not fatal.
    out2 = bridge._coerce({"libraries": ["nope", {"name": "x"}]})
    assert [lib["name"] for lib in out2["libraries"]] == ["x"]


# --------------------------------------------------------------------------- #
# _load_raw fail-soft (URL absent -> local path; missing/unreadable/malformed)
# --------------------------------------------------------------------------- #


def test_load_raw_missing_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge.config, "pine_library_versions_snapshot_url", lambda: "")
    monkeypatch.setattr(
        bridge.config, "pine_library_versions_snapshot_path", lambda: tmp_path / "nope.json"
    )
    out = bridge._load_raw()
    assert out["loaded"] == 0.0
    assert out["error"] == "missing_snapshot"


def test_load_raw_malformed_snapshot(monkeypatch, tmp_path):
    p = tmp_path / "pine.json"
    p.write_text("[]", encoding="utf-8")  # valid JSON, wrong top type
    monkeypatch.setattr(bridge.config, "pine_library_versions_snapshot_url", lambda: "")
    monkeypatch.setattr(bridge.config, "pine_library_versions_snapshot_path", lambda: p)
    out = bridge._load_raw()
    assert out["loaded"] == 0.0
    assert out["error"] == "malformed_snapshot"


def test_load_raw_local_happy_path(monkeypatch, tmp_path):
    p = tmp_path / "pine.json"
    p.write_text(json.dumps(_raw_snapshot()), encoding="utf-8")
    monkeypatch.setattr(bridge.config, "pine_library_versions_snapshot_url", lambda: "")
    monkeypatch.setattr(bridge.config, "pine_library_versions_snapshot_path", lambda: p)
    out = bridge._load_raw()
    assert out["loaded"] == 1.0
    assert out["libraries_drifted"] == 1.0




@pytest.fixture(autouse=True)
def _reset_pine_cache():
    bridge._cached = None
    bridge._cached_at_monotonic = 0.0
    yield
    bridge._cached = None
    bridge._cached_at_monotonic = 0.0


def test_failed_load_preserves_last_good_snapshot(monkeypatch, tmp_path):
    """A transient load failure must not evict a previously-good pine snapshot."""
    p = tmp_path / "pine.json"
    p.write_text(json.dumps(_raw_snapshot()), encoding="utf-8")
    monkeypatch.setattr(bridge.config, "pine_library_versions_snapshot_url", lambda: "")
    monkeypatch.setattr(bridge.config, "pine_library_versions_snapshot_path", lambda: p)
    first = bridge.snapshot()
    assert first["loaded"] == 1.0
    assert first["libraries_drifted"] == 1.0

    bad = tmp_path / "pine_bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(bridge.config, "pine_library_versions_snapshot_path", lambda: bad)
    bridge._cached_at_monotonic = 0.0

    second = bridge.snapshot()
    assert second["loaded"] == 1.0
    assert second["libraries_drifted"] == 1.0


def test_failed_load_without_prior_cache_returns_error_payload(monkeypatch, tmp_path):
    bad = tmp_path / "pine.json"
    bad.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(bridge.config, "pine_library_versions_snapshot_url", lambda: "")
    monkeypatch.setattr(bridge.config, "pine_library_versions_snapshot_path", lambda: bad)
    snap = bridge.snapshot()
    assert snap["loaded"] == 0.0
    assert snap["error"] == "unreadable_snapshot"
# --------------------------------------------------------------------------- #
# Metrics renderer: a known TV version emits the gauge; an unknown one does NOT
# (an unreachable facade must never report version 0 as the real TV version).
# --------------------------------------------------------------------------- #


def test_metrics_render_gates_unknown_tv_version(monkeypatch):
    from services.live_overlay_daemon import metrics

    monkeypatch.setattr(
        metrics.pine_library_version_bridge, "snapshot", lambda: bridge._coerce(_raw_snapshot())
    )
    lines = metrics._render_pine_library_version_metrics()
    body = "\n".join(line for line in lines if not line.startswith("#"))

    assert 'live_overlay_pine_library_tv_version{library="smc_micro_profiles_generated"} 152.0' in body
    # bus_private is unknown -> tv_version_known=0 emitted, but NO tv_version series.
    assert 'live_overlay_pine_library_tv_version_known{library="smc_bus_private"} 0.0' in body
    assert 'live_overlay_pine_library_tv_version{library="smc_bus_private"}' not in body
    assert (
        'live_overlay_pine_consumer_drift{library="smc_micro_profiles_generated",'
        'consumer="SMC_Decision_Board.pine"} 1.0' in body
    )
    assert "live_overlay_pine_library_any_drift 1.0" in body
    assert 'live_overlay_pine_library_data_age_known{library="smc_micro_profiles_generated"} 1.0' in body
    assert 'live_overlay_pine_library_data_age_seconds{library="smc_micro_profiles_generated"}' in body


def test_metrics_render_facade_ok_false_on_probe_error(monkeypatch):
    from services.live_overlay_daemon import metrics

    raw = _raw_snapshot()
    raw["facadeError"] = "facade unreachable"
    monkeypatch.setattr(
        metrics.pine_library_version_bridge, "snapshot", lambda: bridge._coerce(raw)
    )
    body = "\n".join(metrics._render_pine_library_version_metrics())
    assert "live_overlay_pine_library_facade_ok 0.0" in body


# --------------------------------------------------------------------------- #
# ADR-0029: payload volume. The pre-existing gauges measure metadata *about* the
# library (version, ASOF_DATE); an empty payload under a fresh date reads green.
# --------------------------------------------------------------------------- #


def _payload_snapshot(*, known=True, universe_size=6929, universe=0, lists=0) -> dict:
    raw = _raw_snapshot()
    raw["libraries"][0].update(
        {
            "payloadKnown": known,
            "payloadUniverseSize": universe_size,
            "payloadUniverseSymbols": universe,
            "payloadListSymbols": lists,
        }
    )
    return raw


def test_coerce_carries_payload_volume():
    micro = bridge._coerce(_payload_snapshot(universe=6900, lists=412))["libraries"][0]

    assert micro["payload_known"] == 1.0
    assert micro["payload_universe_size"] == 6929.0
    assert micro["payload_universe_symbols"] == 6900.0
    assert micro["payload_list_symbols"] == 412.0


def test_coerce_defaults_payload_to_unknown_for_legacy_snapshots():
    """A snapshot written before this change must not read as an empty payload."""
    micro = bridge._coerce(_raw_snapshot())["libraries"][0]

    assert micro["payload_known"] == 0.0


def test_metrics_render_payload_volume_gauges(monkeypatch):
    from services.live_overlay_daemon import metrics

    monkeypatch.setattr(
        metrics.pine_library_version_bridge,
        "snapshot",
        lambda: bridge._coerce(_payload_snapshot(universe=6900, lists=412)),
    )
    body = "\n".join(
        line for line in metrics._render_pine_library_version_metrics() if not line.startswith("#")
    )

    lib = 'library="smc_micro_profiles_generated"'
    assert f"live_overlay_pine_library_payload_known{{{lib}}} 1.0" in body
    assert f"live_overlay_pine_library_payload_symbols{{{lib}}} 6900.0" in body
    assert f"live_overlay_pine_library_payload_lists{{{lib}}} 412.0" in body
    assert f"live_overlay_pine_library_payload_universe_size{{{lib}}} 6929.0" in body


def test_metrics_render_omits_payload_series_when_unknown(monkeypatch):
    """Hand-authored libraries carry no payload exports — they must not read as 0."""
    from services.live_overlay_daemon import metrics

    monkeypatch.setattr(
        metrics.pine_library_version_bridge,
        "snapshot",
        lambda: bridge._coerce(_payload_snapshot(known=False)),
    )
    body = "\n".join(
        line for line in metrics._render_pine_library_version_metrics() if not line.startswith("#")
    )

    lib = 'library="smc_micro_profiles_generated"'
    assert f"live_overlay_pine_library_payload_known{{{lib}}} 0.0" in body
    assert f"live_overlay_pine_library_payload_symbols{{{lib}}}" not in body


def test_snapshot_builder_list_exports_match_the_generator() -> None:
    """The TS builder duplicates the seven membership export names.

    It cannot import them from Python, so pin them here: a list renamed in the
    generator without updating the builder would silently drop that list from
    the payload count and make the metric read low forever.
    """
    import re
    from pathlib import Path

    from scripts.generate_smc_micro_profiles import LIST_EXPORTS

    source = Path("scripts/build_pine_library_version_snapshot.ts").read_text(encoding="utf-8")
    block = re.search(
        r"const MEMBERSHIP_LIST_EXPORTS = \[(.*?)\] as const;", source, re.DOTALL
    )
    assert block is not None, "MEMBERSHIP_LIST_EXPORTS not found in the snapshot builder"
    names = set(re.findall(r'"([A-Z_]+)"', block.group(1)))

    assert names == set(LIST_EXPORTS.values())
