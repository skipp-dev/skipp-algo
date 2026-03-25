from __future__ import annotations

import urllib.error

from open_prep import alerts


def test_partial_target_failure_retries_failed_target_only(monkeypatch) -> None:
    alerts._last_sent.clear()

    calls: list[str] = []

    def _fake_send(url: str, payload, headers=None):
        calls.append(url)
        if "slack" in url:
            return {"status": 200}
        return {"status": 503, "error": "upstream"}

    config = {
        "enabled": True,
        "min_confidence_tier": "HIGH_CONVICTION",
        "throttle_seconds": 600,
        "targets": [
            {"name": "slack", "url": "https://hooks.example.com/slack", "type": "generic"},
            {"name": "tp", "url": "https://hooks.example.com/tp", "type": "generic"},
        ],
    }
    ranked = [{"symbol": "AAA", "confidence_tier": "HIGH_CONVICTION", "gap_pct": 2.0, "score": 9.0}]

    monkeypatch.setattr(alerts, "_send_webhook", _fake_send)

    alerts.dispatch_alerts(ranked, regime="RISK_ON", config=config)
    assert alerts._is_throttled("AAA", 600, target_scope="AAA::slack") is True
    assert alerts._is_throttled("AAA", 600, target_scope="AAA::tp") is False

    calls.clear()
    alerts.dispatch_alerts(ranked, regime="RISK_ON", config=config)
    assert calls == ["https://hooks.example.com/tp"]


def test_send_webhook_retries_on_503_and_succeeds(monkeypatch) -> None:
    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"ok": true}'

    class _FakeOpener:
        def __init__(self):
            self.calls = 0

        def open(self, req, timeout=10):
            self.calls += 1
            if self.calls == 1:
                raise urllib.error.HTTPError(req.full_url, 503, "down", hdrs=None, fp=None)
            return _Resp()

    fake = _FakeOpener()
    monkeypatch.setattr("urllib.request.build_opener", lambda *args, **kwargs: fake)
    monkeypatch.setattr(alerts.time, "sleep", lambda _s: None)

    out = alerts._send_webhook("https://hooks.example.com/tp", {"x": 1})
    assert out["status"] == 200


def test_send_webhook_blocks_private_url() -> None:
    out = alerts._send_webhook("http://127.0.0.1/hook", {"x": 1})
    assert out["status"] == 0
    assert "unsafe_url" in str(out.get("error", ""))
