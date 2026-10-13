"""Tests for open_prep.rt_notify — the fresh-breakout push notifier."""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import httpx
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


def test_default_mutes_a2_early_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_URL", "https://hook.example/x")
    calls = _capture(monkeypatch)
    notified = rt_notify.notify_fresh_signals([_sig("AAPL", "A0"), _sig("NVDA", "A2")])
    # Default level set is now A0,A1 — the noisy A2 early-warning tier is dropped.
    assert notified == ["AAPL LONG A0"]
    text = calls[0][1]["json"]["text"]
    assert "AAPL" in text and "NVDA" not in text


def test_a2_is_included_and_flagged_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_URL", "https://hook.example/x")
    monkeypatch.setenv("RT_SIGNAL_NOTIFY_LEVELS", "A0,A1,A2")
    calls = _capture(monkeypatch)
    notified = rt_notify.notify_fresh_signals([_sig("AAPL", "A0"), _sig("NVDA", "A2")])
    # With A2 opted back in, early-warnings are included…
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


def test_technical_glyph_is_direction_aware() -> None:
    # Bullish TA (>=0.7) corroborates a LONG → 📈.
    assert rt_notify._fmt_signal(_sig_x("A0", technical_score=0.85)).endswith("📈")
    # Bullish TA on a SHORT is a conflict, not backing → NO glyph (the bug: it used
    # to stamp 📈 "bullish technicals" onto a short, reading as backing).
    short_bull = rt_notify._fmt_signal(_sig_x("A0", direction="SHORT", technical_score=0.85))
    assert "📈" not in short_bull and "📉" not in short_bull
    # Bearish TA (<=0.3) corroborates a SHORT → 📉.
    assert rt_notify._fmt_signal(
        _sig_x("A0", direction="SHORT", technical_score=0.15)).endswith("📉")
    # Bearish TA on a LONG is a conflict → no glyph.
    long_bear = rt_notify._fmt_signal(_sig_x("A0", direction="LONG", technical_score=0.15))
    assert "📈" not in long_bear and "📉" not in long_bear
    # Missing technical_score defaults to the NEUTRAL 0.5 → no glyph either way.
    # Regression guard: a naive 0.0 default would false-flag 📉 on every short.
    assert "📉" not in rt_notify._fmt_signal(_sig_x("A0", direction="SHORT"))
    assert "📈" not in rt_notify._fmt_signal(_sig_x("A0", direction="LONG"))


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


def test_ttl_eviction_runs_even_when_signals_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stale dedup entry must not outlive its 2h TTL just because later polls
    carry no signals — the eviction sweep now runs on empty polls too."""
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_URL", "https://hook.example/x")
    _capture(monkeypatch)
    assert rt_notify.notify_fresh_signals([_sig("AAPL", "A0")], now=0.0) == ["AAPL LONG A0"]
    assert ("AAPL", "LONG") in rt_notify._NOTIFIED
    # An empty poll AFTER the TTL still evicts (was skipped by the early return).
    assert rt_notify.notify_fresh_signals([], now=rt_notify._STATE_TTL_SECS + 1.0) == []
    assert ("AAPL", "LONG") not in rt_notify._NOTIFIED


def test_non_positive_cooldown_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-positive cooldown would re-fire the same still-active signal every
    poll (webhook spam) — it must clamp to the 1800s default instead."""
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_URL", "https://hook.example/x")
    for bad in ("-1", "0", "-0.5"):
        monkeypatch.setenv("RT_SIGNAL_NOTIFY_COOLDOWN_SECS", bad)
        assert rt_notify._cooldown() == 1800.0
    monkeypatch.setenv("RT_SIGNAL_NOTIFY_COOLDOWN_SECS", "-1")
    _capture(monkeypatch)
    # First A0 fires; the same still-active A0 shortly after does NOT re-fire.
    assert rt_notify.notify_fresh_signals([_sig("AAPL", "A0")], now=100.0) == ["AAPL LONG A0"]
    assert rt_notify.notify_fresh_signals([_sig("AAPL", "A0")], now=200.0) == []


def test_unknown_level_tokens_are_dropped_and_warned_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """A typo like 'AO' (letter O) for 'A0' silently disabled that level; it is
    now filtered to the valid set and warned about (once, not per poll)."""
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_URL", "https://hook.example/x")
    monkeypatch.setenv("RT_SIGNAL_NOTIFY_LEVELS", "AO,A1")
    with caplog.at_level("WARNING", logger="open_prep.rt_notify"):
        assert rt_notify._levels() == {"A1"}
        rt_notify._levels()  # second call must NOT warn again
    warnings = [r for r in caplog.records if "unrecognised" in r.getMessage().lower()]
    assert len(warnings) == 1
    # 'A0' typo'd as 'AO' is therefore not notified; 'A1' still is.
    _capture(monkeypatch)
    assert rt_notify.notify_fresh_signals([_sig("AAPL", "A0"), _sig("NVDA", "A1")]) == ["NVDA LONG A1"]


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


def test_early_webhook_routes_a2_to_separate_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_MODE", "slack")
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_URL", "https://hook.example/main")
    monkeypatch.setenv("RT_SIGNAL_EARLY_WEBHOOK_URL", "https://hook.example/early")
    # Main feed muted to A0 — A2 must STILL reach the early channel.
    monkeypatch.setenv("RT_SIGNAL_NOTIFY_LEVELS", "A0")
    calls = _capture(monkeypatch)
    notified = rt_notify.notify_fresh_signals([_sig("AAPL", "A0"), _sig("NVDA", "A2")])
    assert set(notified) == {"AAPL LONG A0", "NVDA LONG A2"}

    by_url = {url: kw["json"]["text"] for url, kw in calls}
    assert set(by_url) == {"https://hook.example/main", "https://hook.example/early"}
    main, early = by_url["https://hook.example/main"], by_url["https://hook.example/early"]
    # A0 only in main, A2 only in early — no double-post across channels.
    assert "AAPL" in main and "NVDA" not in main
    assert "NVDA" in early and "AAPL" not in early
    # Early batch reads as early-warning (header emoji + per-line ⚠️early tail).
    assert early.startswith("⚠️") and "early-warning" in early and "⚠️early" in early
    # Neutral header (the batch can be all-SHORT); direction lives per-line.
    assert main.startswith("🚨")


def test_early_webhook_off_keeps_a2_in_main(monkeypatch: pytest.MonkeyPatch) -> None:
    # Without RT_SIGNAL_EARLY_WEBHOOK_URL, A2 follows RT_SIGNAL_NOTIFY_LEVELS as before.
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_URL", "https://hook.example/main")
    monkeypatch.setenv("RT_SIGNAL_NOTIFY_LEVELS", "A0,A1,A2")
    calls = _capture(monkeypatch)
    notified = rt_notify.notify_fresh_signals([_sig("NVDA", "A2")])
    assert notified == ["NVDA LONG A2"]
    assert len(calls) == 1 and calls[0][0] == "https://hook.example/main"


def test_early_levels_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_URL", "https://hook.example/main")
    monkeypatch.setenv("RT_SIGNAL_EARLY_WEBHOOK_URL", "https://hook.example/early")
    monkeypatch.setenv("RT_SIGNAL_EARLY_LEVELS", "A1,A2")  # route BOTH tiers early
    monkeypatch.setenv("RT_SIGNAL_NOTIFY_LEVELS", "A0,A1,A2")
    calls = _capture(monkeypatch)
    rt_notify.notify_fresh_signals(
        [_sig("AAPL", "A0"), _sig("MSFT", "A1"), _sig("NVDA", "A2")]
    )
    by_url = {url: kw["json"]["text"] for url, kw in calls}
    assert "AAPL" in by_url["https://hook.example/main"]
    early = by_url["https://hook.example/early"]
    assert "MSFT" in early and "NVDA" in early
    assert "MSFT" not in by_url["https://hook.example/main"]


def test_early_webhook_ignored_for_token_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    # Telegram (token+chat_id, not a URL) has no 2nd-URL concept: the early route
    # is inert, so A2 falls back to the main level gate (dropped when muted to A0).
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_MODE", "telegram")
    monkeypatch.setenv("RT_SIGNAL_TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("RT_SIGNAL_TELEGRAM_CHAT_ID", "c")
    monkeypatch.setenv("RT_SIGNAL_EARLY_WEBHOOK_URL", "https://hook.example/early")
    monkeypatch.setenv("RT_SIGNAL_NOTIFY_LEVELS", "A0")
    calls = _capture(monkeypatch)
    notified = rt_notify.notify_fresh_signals([_sig("AAPL", "A0"), _sig("NVDA", "A2")])
    assert notified == ["AAPL LONG A0"]  # A2 not delivered to any early URL
    assert all("hook.example/early" not in url for url, _ in calls)


def test_long_cooldown_not_capped_by_ttl_eviction(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: the dedup TTL sweep evicted entries after 2h regardless of
    the configured cooldown, so RT_SIGNAL_NOTIFY_COOLDOWN_SECS > 7200 silently
    re-pushed after ~2h. Eviction horizon is now max(TTL, cooldown)."""
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_URL", "https://hook.example/x")
    monkeypatch.setenv("RT_SIGNAL_NOTIFY_COOLDOWN_SECS", "14400")  # 4h
    calls = _capture(monkeypatch)

    assert rt_notify.notify_fresh_signals([_sig("AAPL", "A0")], now=0.0) == ["AAPL LONG A0"]
    # Past the bare 2h TTL but inside the 4h cooldown: entry must survive …
    assert rt_notify.notify_fresh_signals([_sig("AAPL", "A0")], now=7300.0) == []
    assert ("AAPL", "LONG") in rt_notify._NOTIFIED
    assert len(calls) == 1  # … and the signal must NOT be re-pushed early.
    # After the full cooldown the re-notify is legitimate.
    assert rt_notify.notify_fresh_signals([_sig("AAPL", "A0")], now=14401.0) == ["AAPL LONG A0"]
    assert len(calls) == 2


@pytest.mark.parametrize("raw", ["inf", "-inf", "nan"])
def test_non_finite_cooldown_falls_back_to_bounded_default(
    monkeypatch: pytest.MonkeyPatch, raw: str,
) -> None:
    monkeypatch.setenv("RT_SIGNAL_NOTIFY_COOLDOWN_SECS", raw)
    assert rt_notify._cooldown() == 1800.0


def test_mode_is_case_insensitive_and_unknown_mode_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_URL", "https://hook.example/x")
    # Case/typo'd casing must not silently disable the notifier.
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_MODE", "Slack")
    assert rt_notify.is_enabled() is True
    # A genuinely unknown mode disables — but now says so once.
    monkeypatch.setenv("RT_SIGNAL_WEBHOOK_MODE", "bogus")
    with caplog.at_level("WARNING"):
        assert rt_notify.is_enabled() is False
    assert any("not a known mode" in r.message for r in caplog.records)


def test_http_post_never_logs_secret_webhook_url(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_url = "https://hooks.example.invalid/services/SECRET/TOKEN"
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *_args, **_kwargs: SimpleNamespace(status_code=500),
    )

    with caplog.at_level(logging.DEBUG):
        assert rt_notify._http_post(secret_url) is False

    assert secret_url not in caplog.text
    assert "SECRET/TOKEN" not in caplog.text
    assert logging.getLogger("httpx").level == logging.WARNING


def test_http_post_exception_log_contains_type_not_secret_url(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_url = "https://hooks.example.invalid/services/SECRET/TOKEN"

    def fail(*_args: object, **_kwargs: object) -> None:
        raise httpx.ConnectError(f"failed request to {secret_url}")

    monkeypatch.setattr(httpx, "post", fail)
    with caplog.at_level(logging.DEBUG):
        assert rt_notify._http_post(secret_url) is False

    assert "ConnectError" in caplog.text
    assert secret_url not in caplog.text
    assert "SECRET/TOKEN" not in caplog.text
