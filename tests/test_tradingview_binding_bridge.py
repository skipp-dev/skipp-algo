"""TradingView dropdown snapshot bridge and Prometheus contract."""
from __future__ import annotations

import base64
import json

from services.live_overlay_daemon import tradingview_binding_bridge as bridge


def _raw(mismatches: int = 0) -> dict:
    return {
        "generated_at_unix": 1_784_176_000,
        "ok": mismatches == 0,
        "sources": {
            "expected": 2,
            "checked": 2,
            "drifted": 1,
            "failed": [],
            "consumers": [
                {"scriptName": "SMC Long-Dip Suite", "matches": False},
                {"scriptName": "SMC Decision Board", "matches": True},
            ],
        },
        "bindings": {
            "checkedBindings": 64,
            "mismatches": mismatches,
            "failed": [],
            "consumers": [{
                "scriptName": "SMC Decision Board",
                "checked": 64,
                "ok": mismatches == 0,
                "mismatches": [{} for _ in range(mismatches)],
            }],
        },
    }


def test_coerce_preserves_measured_binding_drift() -> None:
    out = bridge._coerce(_raw(1))
    assert out["loaded"] == 1.0
    assert out["mismatches"] == 1.0
    assert out["checked_bindings"] == 64.0
    assert out["consumers"][0]["script_name"] == "SMC Decision Board"
    assert out["source_check_known"] == 1.0
    assert out["source_drift"] == 1.0
    assert out["source_checked"] == 2.0
    assert out["source_consumers"][0] == {"script_name": "SMC Long-Dip Suite", "matches": 0.0}


def test_legacy_snapshot_marks_source_verification_unknown() -> None:
    raw = _raw()
    raw.pop("sources")
    out = bridge._coerce(raw)
    assert out["source_check_known"] == 0.0
    assert out["source_drift"] == 0.0


def test_schema_v2_provenance_is_additive_to_legacy_metrics_contract() -> None:
    raw = _raw()
    raw.update(
        {
            "schemaVersion": 2,
            "executionMode": "verify-only",
            "observedAt": "2026-07-26T16:30:00.000Z",
            "repoCommitSha": "a" * 40,
            "rolloutConfigSha256": "b" * 64,
            "productManifestVersion": 3,
            "libraryReleaseVersion": 170,
            "inputsMatchCommit": True,
            "repositoryExpected": {"libraryRelease": {"matches": True}},
            "tradingViewObserved": {"sources": [], "bindings": []},
            "mutations": {
                "sourceSaveRequested": False,
                "sourceSavesCompleted": 0,
                "producerRefreshRequested": False,
                "producerInstancesRemoved": 0,
                "bindingRepairRequested": False,
                "bindingsRepaired": 0,
                "layoutSaveRequested": False,
                "layoutSaved": False,
            },
        }
    )
    out = bridge._coerce(raw)
    assert out["loaded"] == 1.0
    assert out["checked_bindings"] == 64.0
    assert out["source_checked"] == 2.0


def test_load_local_snapshot_fail_soft(monkeypatch, tmp_path) -> None:
    snapshot = tmp_path / "bindings.json"
    snapshot.write_text(json.dumps(_raw()), encoding="utf-8")
    monkeypatch.setattr(bridge.config, "tradingview_bindings_snapshot_url", lambda: "")
    monkeypatch.setattr(bridge.config, "tradingview_bindings_snapshot_path", lambda: snapshot)
    assert bridge._load()["checked_bindings"] == 64.0


def test_load_decodes_github_contents_envelope(monkeypatch) -> None:
    payload = base64.b64encode(json.dumps(_raw()).encode()).decode()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"encoding": "base64", "content": payload}).encode()

    monkeypatch.setattr(bridge.config, "tradingview_bindings_snapshot_url", lambda: "https://api.github.com/x")
    monkeypatch.setattr(bridge.config, "tradingview_bindings_snapshot_url_token", lambda: "token")
    monkeypatch.setattr(bridge.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    assert bridge._load()["checked_bindings"] == 64.0


def test_metrics_expose_rollup_and_consumer(monkeypatch) -> None:
    from services.live_overlay_daemon import metrics

    monkeypatch.setattr(metrics.tradingview_binding_bridge, "snapshot", lambda: bridge._coerce(_raw(1)))
    body = "\n".join(metrics._render_tradingview_binding_metrics())
    assert "live_overlay_tv_binding_drift 1.0" in body
    assert "live_overlay_tv_binding_mismatches 1.0" in body
    assert 'live_overlay_tv_consumer_binding_mismatches{consumer="SMC Decision Board"} 1.0' in body
    assert "live_overlay_tv_consumer_source_check_known 1.0" in body
    assert "live_overlay_tv_consumer_source_drift 1.0" in body
    assert 'live_overlay_tv_consumer_source_matches{consumer="SMC Long-Dip Suite"} 0.0' in body


def test_transient_failure_keeps_last_good_snapshot(monkeypatch) -> None:
    """A transient URL/file failure must not evict the last successful
    snapshot for a full TTL (every sibling bridge keeps last-good; flapping
    loaded 1->0 here rode through on the unloadable alert's 30m for:)."""
    import services.live_overlay_daemon.tradingview_binding_bridge as bridge

    good = {
        "loaded": 1.0,
        "generated_at_unix": 1_700_000_000.0,
        "ok": 1.0,
        "mismatches": 0.0,
        "failed_consumers": 0.0,
        "checked_bindings": 3.0,
        "consumers": [],
        "error": "",
    }
    bad = {"loaded": 0.0, "error": "missing_snapshot"}

    monkeypatch.setattr(bridge, "_load", lambda: dict(good))
    with bridge._lock:
        bridge._cache["snapshot"] = None
        bridge._cache["at"] = 0.0
    first = bridge.snapshot()
    assert first["loaded"] == 1.0

    monkeypatch.setattr(bridge, "_load", lambda: dict(bad))
    with bridge._lock:
        bridge._cache["at"] = -10_000.0  # expire the TTL
    second = bridge.snapshot()
    assert second["loaded"] == 1.0  # last-good retained
    assert second["checked_bindings"] == 3.0

    with bridge._lock:
        bridge._cache["snapshot"] = None
        bridge._cache["at"] = 0.0
    third = bridge.snapshot()
    assert third["loaded"] == 0.0  # no last-good yet -> truthful unloaded
