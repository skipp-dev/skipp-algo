"""TradingView dropdown snapshot bridge and Prometheus contract."""
from __future__ import annotations

import base64
import json

from services.live_overlay_daemon import tradingview_binding_bridge as bridge


def _raw(mismatches: int = 0) -> dict:
    return {
        "generated_at_unix": 1_784_176_000,
        "ok": mismatches == 0,
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
