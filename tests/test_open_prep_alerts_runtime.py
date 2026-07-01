from __future__ import annotations

import json
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


def test_send_webhook_blocks_invalid_host_characters() -> None:
    nul_out = alerts._send_webhook("https://example.com\x00evil.com/webhook", {"x": 1})
    assert nul_out["status"] == 0
    assert "unsafe_url" in str(nul_out.get("error", ""))

    ws_out = alerts._send_webhook("https:// user:pass@example.com/webhook", {"x": 1})
    assert ws_out["status"] == 0
    assert "unsafe_url" in str(ws_out.get("error", ""))


def test_send_webhook_blocks_suspicious_local_hints_in_query() -> None:
    out = alerts._send_webhook("https://hooks.example.com?@127.0.0.1/secret", {"x": 1})
    assert out["status"] == 0
    assert "unsafe_url" in str(out.get("error", ""))


def test_send_webhook_blocks_control_characters_in_path() -> None:
    out = alerts._send_webhook("https://hooks.example.com/webhook\n@127.0.0.1/admin", {"x": 1})
    assert out["status"] == 0
    assert "unsafe_url" in str(out.get("error", ""))


def test_send_webhook_sanitizes_non_finite_floats(monkeypatch) -> None:
    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"ok": true}'

    captured_bodies: list[bytes] = []

    class _FakeOpener:
        def open(self, req, timeout=10):
            captured_bodies.append(req.data)
            return _Resp()

    monkeypatch.setattr("urllib.request.build_opener", lambda *args, **kwargs: _FakeOpener())

    out = alerts._send_webhook(
        "https://hooks.example.com/tp",
        {
            "gap_pct": float("nan"),
            "score": float("inf"),
            "nested": {"value": float("-inf")},
            "items": [1.0, float("nan")],
        },
    )
    assert out["status"] == 200
    assert len(captured_bodies) == 1
    decoded = json.loads(captured_bodies[0].decode("utf-8"))
    assert decoded["gap_pct"] is None
    assert decoded["score"] is None
    assert decoded["nested"]["value"] is None
    assert decoded["items"] == [1.0, None]
def test_format_payloads_tolerate_non_numeric_gap_and_score() -> None:
    candidate = {
        "symbol": "AAA",
        "gap_pct": "positive",
        "score": "N/A",
        "confidence_tier": "STANDARD",
    }

    slack = alerts._format_slack_payload(candidate, regime="RISK_ON")
    discord = alerts._format_discord_payload(candidate, regime="RISK_ON")

    assert "gap +0.0%" in slack["text"]
    assert "score 0.00" in slack["blocks"][0]["text"]["text"]
    assert "gap +0.0%" in discord["content"]
    assert "score 0.00" in discord["content"]


def test_traderspost_payload_avoids_false_sell_for_non_finite_gap() -> None:
    nan_payload = alerts._format_traderspost_payload({"symbol": "AAA", "gap_pct": float("nan")})
    none_payload = alerts._format_traderspost_payload({"symbol": "AAA", "gap_pct": None})
    short_payload = alerts._format_traderspost_payload({"symbol": "AAA", "gap_pct": "-1.5"})

    assert nan_payload["action"] == "buy"
    assert none_payload["action"] == "buy"
    assert short_payload["action"] == "sell"


def test_generic_payload_sanitizes_non_finite_values() -> None:
    payload = alerts._format_generic_payload(
        {
            "symbol": "AAA",
            "gap_pct": float("nan"),
            "score": float("inf"),
            "confidence_tier": "STANDARD",
        },
        regime="RISK_ON",
    )

    assert payload["gap_pct"] is None
    assert payload["score"] is None
