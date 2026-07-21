"""PRE-A0 pilot alert tailer — read-only log filter with explicitly gated Slack egress.

This process is NOT the PRE-A0 ``notify`` path. The shadow worker keeps its
fail-closed contract (no notification imports, ``notify`` refused). The tailer
runs as a separate process behind the worker (``start.sh`` pipes the worker's
log stream through it), passes every line through unchanged, and — only when
the pilot env gates are set — posts the transition into IMMINENT to a dedicated
pilot Slack channel.

Pilot semantics (docs/pre_a0_rollout_runbook.md, "Pilot"):

- unconfirmed early warning: never an A0 claim, never confirmed wording,
- never a probability or percentage, even when the payload carries calibrated
  fields (the pilot runs on the degenerate bootstrap calibration, #3847),
- episode dedup via per-(symbol, direction) cooldown plus an hourly budget,
- fail-closed: missing/invalid configuration leaves a pure passthrough.

Env gates:

    RT_PRE_A0_PILOT=1                       master switch
    RT_PRE_A0_PILOT_WEBHOOK_URL             https Slack incoming webhook
    RT_PRE_A0_PILOT_COOLDOWN_S              default 1800
    RT_PRE_A0_PILOT_MAX_ALERTS_PER_HOUR     default 20
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any, TextIO

from open_prep.a0_rollout import AlertBudget

_MARKER = "PRE_A0_OBSERVE "
_POST_TIMEOUT_S = 10.0
_DISCLAIMER = (
    "Pilotbetrieb: unbestätigte Früherkennung, keine Handlungsempfehlung — "
    "kein bestätigtes A0, unkalibriert, ohne Wahrscheinlichkeit."
)


def post_to_slack(webhook_url: str, message: str) -> None:
    """POST one pilot message to the Slack incoming webhook."""
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps({"text": message}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_POST_TIMEOUT_S):
        pass


class PilotAlertTailer:
    """stdin->stdout passthrough that raises pilot alerts on IMMINENT transitions."""

    def __init__(
        self,
        *,
        post: Callable[[str], None],
        clock: Callable[[], float] = time.time,
        cooldown_s: float = 1800.0,
        max_alerts_per_hour: int = 20,
        out: TextIO = sys.stdout,
        err: TextIO = sys.stderr,
    ) -> None:
        self._post = post
        self._clock = clock
        self._cooldown_s = cooldown_s
        self._budget = AlertBudget(max_alerts_per_hour)
        self._out = out
        self._err = err
        self._last_state: dict[str, str] = {}
        self._last_alert_at: dict[tuple[str, str], float] = {}

    def process_line(self, line: str) -> None:
        """Echo the line unchanged, then evaluate it for a pilot alert."""
        self._out.write(line)
        self._out.flush()
        payload = self._parse(line)
        if payload is None:
            return
        symbol = str(payload.get("symbol", "")).strip().upper()
        state = str(payload.get("state", "")).strip().upper()
        direction = str(payload.get("direction", "")).strip().lower()
        if not symbol or not state:
            return
        previous = self._last_state.get(symbol)
        self._last_state[symbol] = state
        if state != "IMMINENT" or previous == "IMMINENT":
            return
        now = self._clock()
        episode_key = (symbol, direction)
        last_alert = self._last_alert_at.get(episode_key)
        if last_alert is not None and now - last_alert < self._cooldown_s:
            return
        if not self._budget.allow(now=now):
            self._err.write(f"pilot alert suppressed (hourly budget) for {symbol}\n")
            return
        self._last_alert_at[episode_key] = now
        message = self._format(payload, symbol=symbol, direction=direction)
        try:
            self._post(message)
        except (OSError, ValueError, TypeError) as error:
            self._err.write(f"pilot alert delivery failed for {symbol}: {error}\n")

    @staticmethod
    def _parse(line: str) -> dict[str, Any] | None:
        index = line.find(_MARKER)
        if index < 0:
            return None
        raw = line[index + len(_MARKER) :].strip()
        try:
            payload = json.loads(raw)
        except ValueError:
            return None
        if not isinstance(payload, dict) or payload.get("kind") != "PRE_A0":
            return None
        return payload

    @staticmethod
    def _format(payload: Mapping[str, Any], *, symbol: str, direction: str) -> str:
        eta_low = payload.get("eta_low_s")
        eta_high = payload.get("eta_high_s")
        if isinstance(eta_low, (int, float)) and isinstance(eta_high, (int, float)):
            eta = f"ETA ~{eta_low:.0f}–{eta_high:.0f}s"
        else:
            eta = "ETA unbekannt"
        arrow = {"up": "↑", "down": "↓"}.get(direction, direction or "?")
        return f"🧪 PRE-A0 PILOT · {symbol} {arrow} · IMMINENT · {eta}\n{_DISCLAIMER}"


def build_tailer_from_env(
    env: Mapping[str, str],
    *,
    out: TextIO = sys.stdout,
    err: TextIO = sys.stderr,
) -> PilotAlertTailer | None:
    """Fail-closed factory: any missing or invalid gate returns None (pure passthrough)."""
    if env.get("RT_PRE_A0_PILOT", "").strip() != "1":
        return None
    webhook = env.get("RT_PRE_A0_PILOT_WEBHOOK_URL", "").strip()
    if not webhook.startswith("https://"):
        err.write("pilot disabled: RT_PRE_A0_PILOT_WEBHOOK_URL missing or not https\n")
        return None
    try:
        cooldown_s = float(env.get("RT_PRE_A0_PILOT_COOLDOWN_S", "1800"))
        max_alerts = int(env.get("RT_PRE_A0_PILOT_MAX_ALERTS_PER_HOUR", "20"))
        if cooldown_s <= 0 or max_alerts <= 0:
            raise ValueError
    except ValueError:
        err.write("pilot disabled: invalid cooldown or alert budget\n")
        return None
    return PilotAlertTailer(
        post=lambda message: post_to_slack(webhook, message),
        cooldown_s=cooldown_s,
        max_alerts_per_hour=max_alerts,
        out=out,
        err=err,
    )


def main() -> None:
    tailer = build_tailer_from_env(os.environ)
    if tailer is None:
        for line in sys.stdin:
            sys.stdout.write(line)
            sys.stdout.flush()
        return
    for line in sys.stdin:
        tailer.process_line(line)


if __name__ == "__main__":
    main()
