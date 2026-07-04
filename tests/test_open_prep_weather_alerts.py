"""Coverage for the Workstream-C weather wording shared across the Pine panel
and the Slack/Discord/generic alert formatters, plus the weather-change alert.
"""
from __future__ import annotations

from open_prep import alerts
from open_prep.market_microstructure import (
    weather_badge_label,
    weather_summary_line,
)


# --- shared wording -------------------------------------------------------

def test_weather_badge_label_and_summary_line() -> None:
    emoji, label = weather_badge_label("green")  # case-insensitive
    assert emoji == "\U0001F7E2"
    assert label == "Breakout-Wetter"
    assert weather_badge_label("nonsense") == weather_badge_label("UNKNOWN")

    line = weather_summary_line("GREEN", er_intraday=0.23, dispersion=3.56, correlation=0.11)
    assert line.startswith("\U0001F7E2 Breakout-Wetter — ")
    assert "ER 0.23" in line and "Disp 3.56%" in line and "Korr 0.11" in line


def test_weather_summary_line_handles_missing_metrics() -> None:
    line = weather_summary_line("RED")
    assert "Sägemarkt" in line
    assert "ER n/a" in line and "Disp n/a" in line and "Korr n/a" in line


# --- formatters carry the weather line ------------------------------------

_CAND = {"symbol": "MCD", "gap_pct": 0.0, "score": 6.17, "confidence_tier": "STANDARD"}
_WX = {
    "market_weather": "GREEN",
    "intraday_efficiency_ratio": 0.23,
    "cs_dispersion": 3.56,
    "avg_pair_correlation": 0.11,
}


def test_slack_payload_includes_weather_when_present() -> None:
    with_wx = alerts._format_slack_payload(_CAND, regime="ROTATION", weather=_WX)
    text = with_wx["blocks"][0]["text"]["text"]
    assert "Breakout-Wetter" in text and "ER 0.23" in text
    # Absent snapshot -> no weather line, no crash.
    without = alerts._format_slack_payload(_CAND, regime="ROTATION", weather=None)
    assert "Breakout-Wetter" not in without["blocks"][0]["text"]["text"]


def test_discord_and_generic_payload_weather() -> None:
    disc = alerts._format_discord_payload(_CAND, regime="ROTATION", weather=_WX)
    assert "Breakout-Wetter" in disc["content"]

    gen = alerts._format_generic_payload(_CAND, regime="ROTATION", weather=_WX)
    assert gen["market_weather"] == "GREEN"
    assert "Breakout-Wetter" in gen["weather_summary"]

    gen_none = alerts._format_generic_payload(_CAND, regime="ROTATION", weather=None)
    assert "market_weather" not in gen_none


# --- weather-change alert + hysteresis ------------------------------------

_ENABLED = {"enabled": True, "targets": [{"name": "t", "url": "https://example.test/hook"}]}


def test_alert_weather_change_suppressed_cases() -> None:
    # no change
    assert alerts.alert_weather_change("GREEN", "GREEN", _ENABLED) == []
    # transitions to/from UNKNOWN (data-gap flicker) suppressed
    assert alerts.alert_weather_change("UNKNOWN", "GREEN", _ENABLED) == []
    assert alerts.alert_weather_change("GREEN", "UNKNOWN", _ENABLED) == []
    # missing endpoints
    assert alerts.alert_weather_change(None, "GREEN", _ENABLED) == []
    # disabled config
    assert alerts.alert_weather_change("GREEN", "RED", {"enabled": False, "targets": []}) == []


def test_alert_weather_change_tolerates_non_dict_target(monkeypatch) -> None:
    """A malformed target entry must be skipped, not crash the alert path."""
    sent: list[dict] = []
    monkeypatch.setattr(alerts, "_send_webhook", lambda u, p, h=None: (sent.append(p) or {"status": "ok"}))
    cfg = {"enabled": True, "targets": ["not-a-dict", {"name": "t", "url": "https://example.test/hook"}]}
    results = alerts.alert_weather_change("GREEN", "RED", cfg)
    assert len(results) == 1 and len(sent) == 1
    # Same guard on the pre-existing regime-change alert (shared pattern).
    sent.clear()
    results = alerts.alert_regime_change("RISK_ON", "ROTATION", cfg)
    assert len(results) == 1 and len(sent) == 1


def test_snapshot_persists_market_weather(monkeypatch, tmp_path) -> None:
    """save_result_snapshot must keep market_weather, else the weather-change
    alert can never fire (prev is always None)."""
    import json as _json
    from open_prep import diff as diff_mod

    monkeypatch.setattr(diff_mod, "LAST_RESULT_PATH", tmp_path / "last_result.json")
    path = diff_mod.save_result_snapshot(
        {"generated_at": "t", "regime": "ROTATION", "market_weather": "GREEN", "candidates": []}
    )
    saved = _json.loads(path.read_text(encoding="utf-8"))
    assert saved["market_weather"] == "GREEN"


def test_alert_weather_change_fires_on_real_change(monkeypatch) -> None:
    sent: list[dict] = []

    def _fake_send(url, payload, headers=None):
        sent.append(payload)
        return {"status": "ok"}

    monkeypatch.setattr(alerts, "_send_webhook", _fake_send)
    results = alerts.alert_weather_change(
        "GREEN", "RED", _ENABLED, weather_line="🔴 Sägemarkt — ..."
    )
    assert len(results) == 1
    assert sent and sent[0]["event"] == "weather_change"
    assert sent[0]["previous"] == "GREEN" and sent[0]["current"] == "RED"
    assert sent[0]["summary"] == "🔴 Sägemarkt — ..."
