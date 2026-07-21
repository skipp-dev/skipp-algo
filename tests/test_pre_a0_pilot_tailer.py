"""Contract tests for the PRE-A0 pilot alert tailer.

The tailer is a read-only stdin->stdout log filter that runs as a separate
process behind the A0-Fast shadow worker (see ``start.sh``). It must:

1. pass every input line through unchanged (Railway logs stay intact),
2. never crash on malformed input,
3. alert only on the transition into IMMINENT, deduplicated by cooldown and
   bounded by the hourly budget,
4. keep the PRE-A0 user semantics: no A0 claim, no confirmed wording, no
   probability/percentage, an explicit pilot disclaimer,
5. stay fail-closed: without the explicit pilot env gates it is a pure
   passthrough with zero egress.
"""

from __future__ import annotations

import io
import json
from typing import Any

from services.a0_fast_detector.pilot_alert_tailer import (
    PilotAlertTailer,
    build_tailer_from_env,
)


def _observe_line(
    symbol: str = "NVDA",
    state: str = "IMMINENT",
    direction: str = "up",
    eta_low_s: float | None = 90.0,
    eta_high_s: float | None = 240.0,
    **extra: Any,
) -> str:
    payload: dict[str, Any] = {
        "kind": "PRE_A0",
        "level": None,
        "confirmed": False,
        "is_calibrated": False,
        "symbol": symbol,
        "state": state,
        "direction": direction,
        "eta_low_s": eta_low_s,
        "eta_high_s": eta_high_s,
        "session_date": "2026-07-21",
    }
    payload.update(extra)
    return f"2026-07-21 15:00:00,000 INFO worker PRE_A0_OBSERVE {json.dumps(payload, sort_keys=True)}\n"


class _Recorder:
    def __init__(self) -> None:
        self.posts: list[str] = []

    def __call__(self, message: str) -> None:
        self.posts.append(message)


def _tailer(recorder: _Recorder, *, clock: list[float], **kwargs: Any) -> PilotAlertTailer:
    return PilotAlertTailer(
        post=recorder,
        clock=lambda: clock[0],
        out=io.StringIO(),
        err=io.StringIO(),
        **kwargs,
    )


def test_passthrough_preserves_every_line_verbatim() -> None:
    recorder = _Recorder()
    out = io.StringIO()
    tailer = PilotAlertTailer(post=recorder, clock=lambda: 0.0, out=out, err=io.StringIO())
    lines = [
        "plain worker log line\n",
        _observe_line(state="WATCH"),
        "PRE_A0_OBSERVE not-json-at-all\n",
        _observe_line(state="IMMINENT"),
    ]
    for line in lines:
        tailer.process_line(line)
    assert out.getvalue() == "".join(lines)


def test_malformed_json_after_marker_never_raises_and_never_posts() -> None:
    recorder = _Recorder()
    tailer = _tailer(recorder, clock=[0.0])
    tailer.process_line("PRE_A0_OBSERVE {broken json\n")
    tailer.process_line("PRE_A0_OBSERVE [1, 2, 3]\n")  # non-dict payload
    assert recorder.posts == []


def test_alerts_only_on_transition_into_imminent() -> None:
    recorder = _Recorder()
    clock = [1000.0]
    tailer = _tailer(recorder, clock=clock)
    tailer.process_line(_observe_line(state="WATCH"))
    assert recorder.posts == []
    tailer.process_line(_observe_line(state="IMMINENT"))
    assert len(recorder.posts) == 1
    # Still IMMINENT: same episode, no re-alert.
    clock[0] += 1.0
    tailer.process_line(_observe_line(state="IMMINENT"))
    assert len(recorder.posts) == 1


def test_cooldown_suppresses_re_alert_until_elapsed() -> None:
    recorder = _Recorder()
    clock = [1000.0]
    tailer = _tailer(recorder, clock=clock, cooldown_s=1800)
    tailer.process_line(_observe_line(state="IMMINENT"))
    # Drops back to WATCH, then IMMINENT again inside the cooldown window.
    clock[0] += 60.0
    tailer.process_line(_observe_line(state="WATCH"))
    tailer.process_line(_observe_line(state="IMMINENT"))
    assert len(recorder.posts) == 1
    # After the cooldown a fresh transition alerts again.
    clock[0] += 1800.0
    tailer.process_line(_observe_line(state="WATCH"))
    tailer.process_line(_observe_line(state="IMMINENT"))
    assert len(recorder.posts) == 2


def test_cooldown_is_per_symbol_and_direction() -> None:
    recorder = _Recorder()
    clock = [1000.0]
    tailer = _tailer(recorder, clock=clock, cooldown_s=1800)
    tailer.process_line(_observe_line(symbol="NVDA", state="IMMINENT"))
    tailer.process_line(_observe_line(symbol="AMD", state="IMMINENT"))
    assert len(recorder.posts) == 2


def test_hourly_budget_bounds_alert_volume() -> None:
    recorder = _Recorder()
    clock = [1000.0]
    tailer = _tailer(recorder, clock=clock, cooldown_s=1, max_alerts_per_hour=3)
    for index in range(6):
        clock[0] += 5.0
        tailer.process_line(_observe_line(symbol=f"SYM{index}", state="IMMINENT"))
    assert len(recorder.posts) == 3


def test_message_keeps_pilot_semantics() -> None:
    recorder = _Recorder()
    tailer = _tailer(recorder, clock=[0.0])
    tailer.process_line(_observe_line(state="IMMINENT"))
    assert len(recorder.posts) == 1
    message = recorder.posts[0]
    assert "PILOT" in message
    assert "NVDA" in message
    assert "IMMINENT" in message
    assert "keine Handlungsempfehlung" in message
    assert "%" not in message
    assert "bestätigtes A0" in message  # part of the negation "kein bestätigtes A0"
    assert "A0-Signal" not in message


def test_message_omits_probability_even_when_payload_is_calibrated() -> None:
    recorder = _Recorder()
    tailer = _tailer(recorder, clock=[0.0])
    tailer.process_line(
        _observe_line(
            state="IMMINENT",
            is_calibrated=True,
            calibrated_probability_by_horizon={"30": 0.42},
        )
    )
    assert len(recorder.posts) == 1
    assert "0.42" not in recorder.posts[0]
    assert "42" not in recorder.posts[0]
    assert "%" not in recorder.posts[0]


def test_message_handles_missing_eta_range() -> None:
    recorder = _Recorder()
    tailer = _tailer(recorder, clock=[0.0])
    tailer.process_line(_observe_line(state="IMMINENT", eta_low_s=None, eta_high_s=None))
    assert len(recorder.posts) == 1
    assert "ETA unbekannt" in recorder.posts[0]


def test_post_failure_never_breaks_passthrough() -> None:
    def _failing_post(_message: str) -> None:
        raise OSError("slack unreachable")

    out = io.StringIO()
    err = io.StringIO()
    tailer = PilotAlertTailer(post=_failing_post, clock=lambda: 0.0, out=out, err=err)
    line = _observe_line(state="IMMINENT")
    tailer.process_line(line)
    assert out.getvalue() == line
    assert "slack unreachable" in err.getvalue()


def test_build_from_env_is_fail_closed_without_explicit_gates() -> None:
    assert build_tailer_from_env({}, out=io.StringIO(), err=io.StringIO()) is None
    assert (
        build_tailer_from_env(
            {"RT_PRE_A0_PILOT": "1"},
            out=io.StringIO(),
            err=io.StringIO(),
        )
        is None
    )
    assert (
        build_tailer_from_env(
            {"RT_PRE_A0_PILOT_WEBHOOK_URL": "https://hooks.slack.com/services/x"},
            out=io.StringIO(),
            err=io.StringIO(),
        )
        is None
    )
    assert (
        build_tailer_from_env(
            {
                "RT_PRE_A0_PILOT": "1",
                "RT_PRE_A0_PILOT_WEBHOOK_URL": "http://hooks.slack.com/insecure",
            },
            out=io.StringIO(),
            err=io.StringIO(),
        )
        is None
    )


def test_build_from_env_rejects_invalid_budget_and_cooldown() -> None:
    base = {
        "RT_PRE_A0_PILOT": "1",
        "RT_PRE_A0_PILOT_WEBHOOK_URL": "https://hooks.slack.com/services/x",
    }
    assert (
        build_tailer_from_env(
            {**base, "RT_PRE_A0_PILOT_MAX_ALERTS_PER_HOUR": "0"},
            out=io.StringIO(),
            err=io.StringIO(),
        )
        is None
    )
    assert (
        build_tailer_from_env(
            {**base, "RT_PRE_A0_PILOT_COOLDOWN_S": "not-a-number"},
            out=io.StringIO(),
            err=io.StringIO(),
        )
        is None
    )


def test_build_from_env_accepts_valid_configuration() -> None:
    tailer = build_tailer_from_env(
        {
            "RT_PRE_A0_PILOT": "1",
            "RT_PRE_A0_PILOT_WEBHOOK_URL": "https://hooks.slack.com/services/x",
            "RT_PRE_A0_PILOT_COOLDOWN_S": "600",
            "RT_PRE_A0_PILOT_MAX_ALERTS_PER_HOUR": "5",
        },
        out=io.StringIO(),
        err=io.StringIO(),
    )
    assert tailer is not None
