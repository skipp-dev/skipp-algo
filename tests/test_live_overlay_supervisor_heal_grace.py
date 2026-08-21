"""The supervisor must not break the recovery it just started.

Measured 2026-08-05 by driving the real ``_run_supervisor_loop`` against a
simulated feed: the heal cadence (30 s) is shorter than the minimum recovery
time (``_RECONNECT_DELAY_SECS`` = 10 s to reconnect, then up to one full
60 s ``ohlcv-1m`` interval before the first bar can arrive), and ``stalled``
is derived from ``last_bar_age_secs()`` alone, which cannot fall until a bar
arrives. So heal #2 and #3 each destroyed the freshly reconnected client that
would have cleared the stall, and a SINGLE transient stall escalated to
``os._exit(1)`` whenever the first bar landed more than 20 s after the
reconnect — roughly one in three, since Databento emits at minute close.

The cost is not abstract: OPS.md records that a restart wipes the bar cache
and requested symbols need ~20 min to re-accumulate rolling depth, and
``cache.py`` has no persistence at all. squeeze_on / ats_zscore /
flow_rel_vol are blank for that whole window.

Escalation itself stays intact — a feed that is genuinely dead must still
reach the platform restart. These tests pin both halves.
"""

from __future__ import annotations

import types
from typing import Any

import pytest


def _drive(
    monkeypatch: pytest.MonkeyPatch, first_bar_delay: float, max_cycles: int = 40
) -> dict[str, Any]:
    """Run the REAL supervisor loop against a simulated feed on a fake clock.

    The feed starts stalled. Every heal breaks the connection; the feed then
    reconnects after ``_RECONNECT_DELAY_SECS`` and delivers its first bar
    ``first_bar_delay`` seconds later, after which bars flow every second.
    """
    import services.live_overlay_daemon.feed as feed_mod

    state: dict[str, Any] = {
        "now": 200.0,  # 200 s since the last bar => already past the stall threshold
        "last_bar": 0.0,
        "reconnect_at": None,
        "bar_due": None,
        "streaming": False,
        "heals": 0,
        "exited": False,
    }

    def advance(seconds: float) -> None:
        end = state["now"] + seconds
        while state["now"] < end and not state["exited"]:
            state["now"] += 1.0
            if state["reconnect_at"] is not None and state["now"] >= state["reconnect_at"]:
                state["reconnect_at"] = None
                state["bar_due"] = state["now"] + first_bar_delay
            if state["bar_due"] is not None and state["now"] >= state["bar_due"]:
                state["bar_due"] = None
                state["streaming"] = True
            if state["streaming"]:
                state["last_bar"] = state["now"]

    class _Stop:
        def __init__(self) -> None:
            self.cycles = 0

        def wait(self, seconds: float) -> bool:
            self.cycles += 1
            advance(seconds)
            return self.cycles >= max_cycles or state["exited"]

        def is_set(self) -> bool:
            return False

    def _break() -> None:
        state["heals"] += 1
        state["streaming"] = False
        state["bar_due"] = None
        state["reconnect_at"] = state["now"] + feed_mod._RECONNECT_DELAY_SECS
        # Mirrors _supervisor_break_stalled_client() -> bool. Returning None
        # reads as "no client was broken", which makes the supervisor refund the
        # heal attempt (`heal_attempts -= 1`) — the counter never grows, nothing
        # ever escalates, and last_heal_at stays 0 so the grace window never
        # arms either. This stub breaks a client, so it must say so.
        return True

    monkeypatch.setattr(feed_mod, "time", types.SimpleNamespace(monotonic=lambda: state["now"]))
    monkeypatch.setattr(feed_mod, "last_bar_age_secs", lambda: state["now"] - state["last_bar"])
    monkeypatch.setattr(feed_mod, "_supervisor_break_stalled_client", _break)
    monkeypatch.setattr(
        feed_mod, "_escalate_to_platform_restart", lambda: state.__setitem__("exited", True)
    )
    monkeypatch.setattr(
        feed_mod,
        "worker_liveness",
        lambda: {
            "live_feed": True,
            "ingest_processor": True,
            "overlay_refresh": True,
            "flow_refresh": True,
        },
    )
    monkeypatch.setattr(feed_mod.market_hours, "is_us_regular_session_open", lambda: True)
    monkeypatch.setattr(feed_mod, "_inc_metric", lambda *a, **k: None)
    feed_mod._fatal_config_error.clear()
    # 2026-08-20: auch DIESEN Modulzustand zuruecksetzen, sonst borgt der Test
    # die Uhr eines fremden Tests.
    #
    # Der Treiber stellt die Zeit auf 200.0. ``_run_supervisor_loop`` liest aber
    # ``_runtime["reconnect_wait_until"]``, und der ECHTE Reconnect-Pfad
    # (feed.py, ``_runtime[...] = time.monotonic() + delay``) schreibt dort einen
    # Wert der ECHTEN Uhr — auf einer Maschine mit Uptime also Hunderttausende.
    # Gegen unsere 200.0 liegt der in ferner Zukunft, ``_grace_deadline`` laeuft
    # nie ab, es wird nie geheilt und nie eskaliert.
    #
    # Gemessen am 20.8.: im SERIELLEN Volllauf fielen dadurch alle fuenf Tests
    # dieser Datei, waehrend sie allein und unter ``-n 4`` gruen sind — unter
    # xdist landet der Verursacher meist in einem anderen Worker. Die PR-Lane
    # faehrt die volle Suite SERIELL innerhalb jedes Shards (ci.yml:
    # ``--splits 4 --group N``, ohne ``-n``), dort ist die Reihenfolge also
    # wieder scharf; und jede Neuaufzeichnung von ``.test_durations`` verschiebt
    # die Shard-Zuschnitte. Genau nachgestellt mit einem Plugin, das nichts
    # weiter tut als diesen einen Schluessel zu setzen.
    monkeypatch.setitem(feed_mod._runtime, "reconnect_wait_until", 0.0)

    feed_mod._run_supervisor_loop(_Stop())
    return state


@pytest.mark.parametrize("first_bar_delay", [0.0, 21.0, 45.0, 59.0])
def test_a_single_transient_stall_never_escalates_while_the_feed_recovers(
    monkeypatch: pytest.MonkeyPatch, first_bar_delay: float
) -> None:
    """Across the whole first-bar latency range Databento can produce (0..60 s,
    it emits at minute close), one heal plus patience must be enough."""
    state = _drive(monkeypatch, first_bar_delay)
    assert not state["exited"], (
        f"a single transient stall escalated to a process restart although the "
        f"feed recovered {first_bar_delay}s after the reconnect — the bar cache "
        f"is wiped for ~20 min for nothing"
    )
    assert state["heals"] == 1, (
        f"expected exactly one heal, got {state['heals']}: every further break "
        f"destroys the connection that is about to clear the stall"
    )


def test_a_feed_that_never_recovers_still_escalates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The grace period must not disarm escalation — a genuinely dead feed has
    to reach the platform restart, just later than before."""
    state = _drive(monkeypatch, first_bar_delay=10_000.0, max_cycles=200)
    assert state["exited"], "a permanently dead feed must still escalate"
    assert state["heals"] == pytest.approx(3, abs=1), (
        f"escalation should follow the documented {3} attempts, saw {state['heals']}"
    )


def test_a_leftover_reconnect_window_does_not_disarm_this_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Die Isolation selbst festnageln, nicht nur herstellen.

    Ohne den ``reconnect_wait_until``-Reset in ``_drive`` erbt dieser Treiber die
    ECHTE Uhr eines fremden Tests, und alle fuenf Zusicherungen dieser Datei
    werden lautlos vakuum: die Heilkarenz laeuft nie ab, es wird nie geheilt,
    nie eskaliert — und ``assert state["exited"]`` scheitert mit einer Begruendung,
    die auf den falschen Verdaechtigen zeigt.

    Diese Probe setzt genau den Zustand, den der echte Reconnect-Pfad
    hinterlaesst (``time.monotonic() + delay``, feed.py), und verlangt dasselbe
    Urteil wie ohne ihn. Nimmt jemand den Reset wieder heraus, wird sie rot.
    """
    import time as real_time

    import services.live_overlay_daemon.feed as feed_mod

    feed_mod._runtime["reconnect_wait_until"] = real_time.monotonic() + 30.0
    try:
        state = _drive(monkeypatch, first_bar_delay=10_000.0, max_cycles=200)
    finally:
        feed_mod._runtime["reconnect_wait_until"] = 0.0
    assert state["exited"], (
        "ein stehengebliebenes reconnect_wait_until aus einem FREMDEN Test hat "
        "die Eskalation entwaffnet — _drive setzt den Modulzustand nicht mehr "
        "zurueck, und damit sind alle Zusicherungen dieser Datei vakuum"
    )
