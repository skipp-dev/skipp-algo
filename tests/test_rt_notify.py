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


def _sig_with_context(symbol: str, level: str, direction: str = "LONG") -> Any:
    s = _sig(symbol, level, direction)
    s.trade_entry, s.trade_stop, s.trade_target, s.trade_r = 200.0, 195.0, 210.0, 2.0
    return s


def test_trade_context_line_rendered_when_fields_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_URL", "https://hook.example/x")
    calls = _capture(monkeypatch)
    rt_notify.notify_fresh_signals([_sig_with_context("NVDA", "A0")])
    text = calls[0][1]["json"]["text"]
    lines = text.splitlines()
    # Level line first, indented context line directly below it.
    assert lines[1].startswith("🔴 A0 NVDA")
    assert lines[2] == "   ↳ entry ≤200.00 · stop 195.00 (-2.5%) · target 210.00 (+5.0%) · R 2.0"


def test_trade_context_line_bearish_uses_geq_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_URL", "https://hook.example/x")
    calls = _capture(monkeypatch)
    s = _sig_with_context("TSLA", "A1", direction="SHORT")
    s.trade_stop, s.trade_target = 205.0, 190.0  # inverted bracket
    rt_notify.notify_fresh_signals([s])
    ctx_line = calls[0][1]["json"]["text"].splitlines()[2]
    assert ctx_line.startswith("   ↳ entry ≥200.00") and "stop 205.00 (+2.5%)" in ctx_line


def test_no_trade_context_no_extra_line(monkeypatch: pytest.MonkeyPatch) -> None:
    # A signal without trade fields (or entry=None) renders exactly one line.
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_URL", "https://hook.example/x")
    calls = _capture(monkeypatch)
    rt_notify.notify_fresh_signals([_sig("AAPL", "A1")])
    assert len(calls[0][1]["json"]["text"].splitlines()) == 2  # header + one signal line
