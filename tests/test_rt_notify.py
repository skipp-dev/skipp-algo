"""Tests for open_prep.rt_notify — the fresh-breakout push notifier."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from open_prep import rt_notify


def _sig(symbol: str, level: str, direction: str = "LONG") -> Any:
    return SimpleNamespace(
        symbol=symbol, level=level, direction=direction, price=100.0,
        volume_ratio=2.4, change_pct=3.1, freshness=1.0,
    )


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    rt_notify.reset_state()
    # Clear every RT_SIGNAL_* var so a developer's real .env cannot leak in.
    for k in list(__import__("os").environ):
        if k.startswith("RT_SIGNAL_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_SYNC", "1")  # POST inline for capture


def _capture(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(rt_notify, "_http_post", lambda url, **kw: (calls.append((url, kw)), True)[1])
    return calls


def test_disabled_by_default_is_a_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch)
    assert rt_notify.is_enabled() is False
    assert rt_notify.notify_fresh_signals([_sig("AAPL", "A0")]) == []
    assert calls == []


def test_generic_webhook_notifies_all_levels_by_default_and_flags_a2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_URL", "https://hook.example/x")
    calls = _capture(monkeypatch)
    notified = rt_notify.notify_fresh_signals([_sig("AAPL", "A0"), _sig("NVDA", "A2")])
    # Default level set is A0,A1,A2 — A2 early-warnings are included…
    assert notified == ["AAPL LONG A0", "NVDA LONG A2"]
    assert len(calls) == 1
    url, kw = calls[0]
    assert url == "https://hook.example/x"
    text = kw["json"]["text"]
    assert "AAPL" in text and "A0" in text and "NVDA" in text
    # …but A2 is flagged so it never reads as a confirmed breakout.
    assert "⚠️early" in text
    a2_line = next(ln for ln in text.splitlines() if "NVDA" in ln)
    assert a2_line.endswith("⚠️early")


def test_high_conviction_a1_gets_near_a0_star(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_URL", "https://hook.example/x")
    calls = _capture(monkeypatch)
    # vol 2.4 / Δ3.1% are both past the midpoint toward the A0 floor -> ⭐.
    notified = rt_notify.notify_fresh_signals([_sig("AAPL", "A1")])
    text = calls[0][1]["json"]["text"]
    a1_line = next(ln for ln in text.splitlines() if "AAPL" in ln)
    assert a1_line.endswith("⭐near-A0")
    # The dedup/return key is the raw level, unaffected by the presentational tag.
    assert notified == ["AAPL LONG A1"]


def test_weak_a1_is_not_starred(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_URL", "https://hook.example/x")
    calls = _capture(monkeypatch)
    # A slow-grinder A1: above the A1 floor but below the near-A0 midpoint on both axes.
    weak = SimpleNamespace(symbol="XYZ", level="A1", direction="LONG", price=50.0,
                           volume_ratio=1.3, change_pct=0.5, freshness=1.0)
    rt_notify.notify_fresh_signals([weak])
    a1_line = next(ln for ln in calls[0][1]["json"]["text"].splitlines() if "XYZ" in ln)
    assert "⭐" not in a1_line and a1_line.endswith("%")
    # One strong axis alone is not enough — both volume and move must lean A0.
    assert rt_notify._is_high_conviction_a1(
        SimpleNamespace(volume_ratio=3.5, change_pct=0.4)
    ) is False
    # The ⭐ is A1-only: an A0 line is never starred even though its momentum
    # clears the gate (A0 is already the top tier).
    assert "⭐" not in rt_notify._fmt_signal(_sig("AAPL", "A0"))


def _sig_x(level: str, **extra: Any) -> Any:
    base = dict(symbol="AAPL", level=level, direction="LONG", price=100.0,
                volume_ratio=1.2, change_pct=0.5)  # below the ⭐ gate by default
    base.update(extra)
    return SimpleNamespace(**base)


def test_corroboration_glyphs_news_and_technical() -> None:
    # News catalyst only.
    assert rt_notify._fmt_signal(_sig_x("A0", news_score=0.7)).endswith("📰")
    # Strong technicals only.
    assert rt_notify._fmt_signal(_sig_x("A0", technical_score=0.85)).endswith("📈")
    # Both — 📰 before 📈, appended after the level tail.
    both = rt_notify._fmt_signal(_sig_x("A1", volume_ratio=2.5, change_pct=1.2,
                                        news_score=0.9, technical_score=0.9))
    assert both.endswith("⭐near-A0 📰 📈")
    # Below thresholds → no glyph (missing enrichment defaults never false-flag).
    assert "📰" not in rt_notify._fmt_signal(_sig_x("A0", news_score=0.4))
    assert "📈" not in rt_notify._fmt_signal(_sig_x("A0", technical_score=0.65))
    assert rt_notify._fmt_signal(_sig_x("A0")).endswith("%")  # no fields set → clean


def test_levels_env_can_mute_a2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_URL", "https://hook.example/x")
    monkeypatch.setenv("RT_SIGNAL_NOTIFY_LEVELS", "A0,A1")
    calls = _capture(monkeypatch)
    notified = rt_notify.notify_fresh_signals([_sig("AAPL", "A0"), _sig("NVDA", "A2")])
    assert notified == ["AAPL LONG A0"]
    assert "NVDA" not in calls[0][1]["json"]["text"]


def test_dedup_and_strengthen_and_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_URL", "https://hook.example/x")
    monkeypatch.setenv("RT_SIGNAL_NOTIFY_COOLDOWN_SECS", "600")
    _capture(monkeypatch)

    # First A1 fires; the same still-active A1 within cooldown does NOT re-fire.
    assert rt_notify.notify_fresh_signals([_sig("AAPL", "A1")], now=1000.0) == ["AAPL LONG A1"]
    assert rt_notify.notify_fresh_signals([_sig("AAPL", "A1")], now=1100.0) == []
    # Upgrade to the stronger A0 re-fires immediately (still within cooldown).
    assert rt_notify.notify_fresh_signals([_sig("AAPL", "A0")], now=1150.0) == ["AAPL LONG A0"]
    # A weaker A1 afterwards does not re-fire (not a strengthen).
    assert rt_notify.notify_fresh_signals([_sig("AAPL", "A1")], now=1200.0) == []
    # After the cooldown a still-active signal re-fires as a reminder.
    assert rt_notify.notify_fresh_signals([_sig("AAPL", "A1")], now=1900.0) == ["AAPL LONG A1"]


@pytest.mark.parametrize(
    "mode,env,check",
    [
        ("discord", {"RT_SIGNAL_WEBHOOK_URL": "https://d/x"},
         lambda url, kw: url == "https://d/x" and "content" in kw["json"]),
        ("slack", {"RT_SIGNAL_WEBHOOK_URL": "https://s/x"},
         lambda url, kw: "text" in kw["json"]),
        ("telegram", {"RT_SIGNAL_TELEGRAM_BOT_TOKEN": "BT", "RT_SIGNAL_TELEGRAM_CHAT_ID": "42"},
         lambda url, kw: url == "https://api.telegram.org/botBT/sendMessage" and kw["json"]["chat_id"] == "42"),
        ("twilio_whatsapp",
         {"RT_SIGNAL_TWILIO_SID": "ACx", "RT_SIGNAL_TWILIO_AUTH": "tok",
          "RT_SIGNAL_TWILIO_FROM": "whatsapp:+1", "RT_SIGNAL_TWILIO_TO": "whatsapp:+49"},
         lambda url, kw: url.endswith("/Accounts/ACx/Messages.json")
         and kw["auth"] == ("ACx", "tok")
         and kw["data"]["To"] == "whatsapp:+49" and kw["data"]["From"] == "whatsapp:+1"),
        ("meta_whatsapp",
         {"RT_SIGNAL_META_TOKEN": "MT", "RT_SIGNAL_META_PHONE_ID": "999", "RT_SIGNAL_META_TO": "+49"},
         lambda url, kw: url == "https://graph.facebook.com/v20.0/999/messages"
         and kw["headers"]["Authorization"] == "Bearer MT"
         and kw["json"]["messaging_product"] == "whatsapp" and kw["json"]["to"] == "+49"),
    ],
)
def test_provider_modes_build_correct_request(
    monkeypatch: pytest.MonkeyPatch, mode: str, env: dict[str, str], check: Any
) -> None:
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_MODE", mode)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    calls = _capture(monkeypatch)
    assert rt_notify.is_enabled() is True
    rt_notify.notify_fresh_signals([_sig("AAPL", "A0")])
    assert len(calls) == 1
    url, kw = calls[0]
    assert check(url, kw), (url, kw)


def test_notify_is_fail_soft_when_post_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_URL", "https://hook.example/x")

    def _boom(url: str, **kw: Any) -> bool:
        raise RuntimeError("network down")

    monkeypatch.setattr(rt_notify, "_http_post", _boom)
    # Must not raise — the poll loop depends on this. And since delivery failed,
    # nothing was notified, so the return is empty (was: claimed the key).
    assert rt_notify.notify_fresh_signals([_sig("AAPL", "A0")]) == []


def test_failed_post_does_not_advance_dedup_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """A webhook that returns HTTP >= 400 (POST 'fails') must NOT mark the
    signal notified — otherwise a transient outage silently suppresses it for a
    whole cooldown. The next poll must re-attempt."""
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_URL", "https://hook.example/x")
    calls = {"n": 0}

    def _failing_post(url: str, **kw: Any) -> bool:
        calls["n"] += 1
        return False

    monkeypatch.setattr(rt_notify, "_http_post", _failing_post)
    # Both calls re-attempt (state never advanced) and report nothing delivered.
    assert rt_notify.notify_fresh_signals([_sig("AAPL", "A0")]) == []
    assert rt_notify.notify_fresh_signals([_sig("AAPL", "A0")]) == []
    assert calls["n"] == 2


def test_raising_post_does_not_advance_dedup_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same guarantee when the POST raises instead of returning False."""
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_URL", "https://hook.example/x")
    calls = {"n": 0}

    def _booming_post(url: str, **kw: Any) -> bool:
        calls["n"] += 1
        raise RuntimeError("network down")

    monkeypatch.setattr(rt_notify, "_http_post", _booming_post)
    assert rt_notify.notify_fresh_signals([_sig("AAPL", "A0")]) == []
    assert rt_notify.notify_fresh_signals([_sig("AAPL", "A0")]) == []
    assert calls["n"] == 2


def test_recovers_after_transient_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Once the webhook recovers, the previously-failed signal is delivered and
    only THEN deduplicated."""
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_URL", "https://hook.example/x")
    ok = {"v": False}
    calls = {"n": 0}

    def _flaky_post(url: str, **kw: Any) -> bool:
        calls["n"] += 1
        return ok["v"]

    monkeypatch.setattr(rt_notify, "_http_post", _flaky_post)
    assert rt_notify.notify_fresh_signals([_sig("AAPL", "A0")], now=1000.0) == []
    ok["v"] = True
    assert rt_notify.notify_fresh_signals([_sig("AAPL", "A0")], now=1010.0) == ["AAPL LONG A0"]
    # Now deduplicated — no re-fire within cooldown, no extra POST.
    assert rt_notify.notify_fresh_signals([_sig("AAPL", "A0")], now=1020.0) == []
    assert calls["n"] == 2


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("price", None),
        ("volume_ratio", None),
        ("change_pct", None),
        ("price", "not-a-number"),
        ("change_pct", "not-a-number"),
    ],
)
def test_corrupt_numeric_field_does_not_kill_the_batch(
    monkeypatch: pytest.MonkeyPatch, field: str, bad_value: Any
) -> None:
    """A single signal with a None/garbage numeric field must not raise and
    blow up the whole batch push (which would also mark every fresh signal
    notified-but-never-sent). The bad field renders as 0.0."""
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_URL", "https://hook.example/x")
    calls = _capture(monkeypatch)
    bad = _sig("AAPL", "A0")
    setattr(bad, field, bad_value)
    good = _sig("NVDA", "A1")
    notified = rt_notify.notify_fresh_signals([bad, good])
    assert notified == ["AAPL LONG A0", "NVDA LONG A1"]
    assert len(calls) == 1
    text = calls[0][1]["json"]["text"]
    assert "AAPL" in text and "NVDA" in text
