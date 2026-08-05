"""The Hold-Manager receiver must not do blocking I/O on the event loop.

``ingest_hold_manager_shadow`` is an ``async def``, so its body runs ON the
uvicorn event loop — the same loop that serves ``/{token}/smc_live``. Inside
it does two blocking things per request: ``_load_contract`` (stat + read +
json.loads, uncached) and ``_persist`` (sqlite3 connect + ``PRAGMA
synchronous = FULL`` + ``BEGIN IMMEDIATE`` + commit, i.e. an fsync on the
Railway volume, with a 5 s busy timeout under lock contention).

Measured 2026-08-05 against the real app under uvicorn: flooding this route
pushed ``/smc_live`` median latency from 1.0 ms to 9.6 ms (x9.4), while
flooding the SIBLING route in the same file — which is a plain ``def`` and
therefore threadpooled, opening the same SQLite file with a heavier query —
cost only x2.0. Same disk work, ~5x less impact once it is off the loop.

The invariant tested here is the thread, not the latency: latency assertions
are flaky on shared CI runners, but "which thread ran this" is exact.
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any

import pytest

from services.live_overlay_daemon import hold_manager_shadow_receiver as receiver


def _find_route(app_router: Any, path_fragment: str) -> Any:
    for route in app_router.routes:
        if path_fragment in getattr(route, "path", ""):
            return route
    raise AssertionError(f"route {path_fragment} not found")


@pytest.mark.parametrize("blocking_symbol", ["_load_contract", "_persist"])
def test_blocking_work_runs_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, blocking_symbol: str
) -> None:
    """Both blocking calls must land on a worker thread.

    The event-loop thread is captured inside the running loop; whichever
    thread the blocking helper observes must be a different one.
    """
    loop_thread: dict[str, int] = {}
    seen: dict[str, int] = {}

    real = getattr(receiver, blocking_symbol)

    def _spy(*args: Any, **kwargs: Any) -> Any:
        seen[blocking_symbol] = threading.get_ident()
        return real(*args, **kwargs)

    monkeypatch.setattr(receiver, blocking_symbol, _spy)
    monkeypatch.setattr(receiver.config, "hold_manager_shadow_accepting", lambda: True)
    monkeypatch.setattr(receiver, "_ledger_path", lambda: tmp_path / "ledger.sqlite3")
    # Auth is a real gate before the blocking work; satisfy it rather than
    # bypass it, so the call actually travels the production route.
    monkeypatch.setattr(
        receiver.config, "hold_manager_shadow_webhook_token", lambda: "t" * 40
    )
    monkeypatch.setattr(receiver, "_validate_contract", lambda *a, **k: None)
    monkeypatch.setattr(receiver, "_validate_event_time", lambda *a, **k: None)

    router = receiver.build_router(lambda a, b: True)
    endpoint = _find_route(router, "hold-manager-shadow").endpoint

    body = json.dumps(
        {
            "authToken": "t" * 40,
            "schemaVersion": 1,
            "requirementId": "R2",
            "channel": "hold",
            "mode": "shadow",
            "sourceSha256": "a" * 64,
            "scriptName": "SMC_Event_Overlay",
            "layout": "layout-1",
            "producer": "tradingview",
            "busSchema": 1,
            "symbol": "NASDAQ:NVDA",
            "timeframe": "5m",
            "barTime": "2026-08-05T14:30:00+00:00",
            "price": "100.5",
        }
    ).encode()

    class _Request:
        @property
        def headers(self) -> dict[str, str]:
            return {"content-type": "application/json"}

        async def stream(self) -> Any:
            yield body

    async def _drive() -> None:
        loop_thread["id"] = threading.get_ident()
        try:
            await endpoint(_Request())
        except Exception:
            # A later rejection is fine: the spy has already recorded which
            # thread the blocking helper ran on, which is all this asserts.
            pass

    asyncio.run(_drive())

    assert blocking_symbol in seen, (
        f"{blocking_symbol} was never reached — the test would prove nothing"
    )
    assert seen[blocking_symbol] != loop_thread["id"], (
        f"{blocking_symbol} ran on the event-loop thread — it blocks the same "
        f"loop that serves /{{token}}/smc_live"
    )


def test_the_sibling_state_route_stays_synchronous() -> None:
    """The read route is a plain ``def`` on purpose: FastAPI then runs it in
    the threadpool. Pinned so a future edit does not 'modernise' it into the
    same trap."""
    router = receiver.build_router(lambda a, b: True)
    state_route = _find_route(router, "hold-manager-shadow/state")
    assert not asyncio.iscoroutinefunction(state_route.endpoint), (
        "the state route must stay sync so FastAPI threadpools it"
    )
