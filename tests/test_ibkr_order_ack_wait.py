"""Phantom-order regression: the paper submitter must wait for IB to ACKNOWLEDGE
orders before the caller disconnects.

Root cause (2026-07-08): ``place_order_intents`` did placeOrder -> disconnect
with no event-loop pump, so ib_async never flushed the transmit=True bracket
leg — orders were recorded ``paper_submitted`` but never rested at IB and never
filled (0 C8 fills). ``place_order_intents_with_ib`` now pumps the loop until
every order reaches an acknowledged status and records that true status.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from scripts.execute_ibkr_watchlist import (
    IBKRConnectionConfig,
    IBKROrderIntent,
    _await_order_acknowledgements,
    place_order_intents_with_ib,
    pump_event_loop_until,
)


class _Status:
    def __init__(self, status: str) -> None:
        self.status = status


class _Trade:
    def __init__(self, status: str) -> None:
        self.orderStatus = _Status(status)


class _Order:
    def __init__(self, ref: str, oid: int) -> None:
        self.orderRef = ref
        self.orderId = oid
        self.permId = 0
        self.orderType = "LMT"
        self.action = "BUY"
        self.lmtPrice = 10.0
        self.auxPrice = None
        self.transmit = False


def _intent() -> IBKROrderIntent:
    return IBKROrderIntent(
        trade_date=date(2026, 7, 8), symbol="AAA", watchlist_rank=1, level_tag="L1",
        quantity=1, entry_limit=10.0, take_profit=12.0, stop_loss=9.0,
        trailing_stop_pct=0.0, trailing_stop_anchor=0.0, premarket_last=10.0,
        gap_pct=0.0, tif="DAY", outside_rth=False, exit_mode="tp-stop",
        order_ref="smc-2026-07-08-AAA-L1",
    )


# --------------------------------------------------------------------------- #
# pump_event_loop_until (the shared helper both paths delegate to)
# --------------------------------------------------------------------------- #
def test_pump_returns_true_without_sleeping_when_predicate_already_true() -> None:
    class _IB:
        slept = 0

        def sleep(self, _s: float) -> None:  # pragma: no cover
            self.slept += 1

    ib = _IB()
    assert pump_event_loop_until(ib, lambda: True, timeout_seconds=5.0) is True
    assert ib.slept == 0


def test_pump_runs_loop_until_predicate_flips() -> None:
    state = {"n": 0}

    class _IB:
        def sleep(self, _s: float) -> None:
            state["n"] += 1

    ib = _IB()
    assert pump_event_loop_until(ib, lambda: state["n"] >= 3, timeout_seconds=5.0, poll_seconds=0.1) is True
    assert state["n"] == 3


def test_pump_returns_false_on_timeout() -> None:
    class _IB:
        def sleep(self, _s: float) -> None:
            pass

    assert pump_event_loop_until(_IB(), lambda: False, timeout_seconds=0.3, poll_seconds=0.1) is False


# --------------------------------------------------------------------------- #
# _await_order_acknowledgements
# --------------------------------------------------------------------------- #
def test_await_returns_immediately_when_already_acked() -> None:
    trades = [_Trade("PreSubmitted"), _Trade("Submitted")]

    class _IB:
        slept = 0

        def sleep(self, _s: float) -> None:  # pragma: no cover - must not run
            self.slept += 1

    ib = _IB()
    assert _await_order_acknowledgements(ib, trades, timeout_seconds=5.0) is True
    assert ib.slept == 0  # no pumping needed


def test_await_pumps_loop_until_ib_acknowledges() -> None:
    """Trades start PendingSubmit; the event loop (sleep) flips them to
    PreSubmitted — the wait must pump until then, not before, not forever."""
    trades = [_Trade("PendingSubmit"), _Trade("PendingSubmit")]

    class _IB:
        def __init__(self) -> None:
            self.calls = 0

        def sleep(self, _s: float) -> None:
            self.calls += 1
            if self.calls >= 2:  # IB acks after a couple of loop turns
                for t in trades:
                    t.orderStatus.status = "PreSubmitted"

    ib = _IB()
    assert _await_order_acknowledgements(ib, trades, timeout_seconds=5.0, poll_seconds=0.1) is True
    assert ib.calls == 2


def test_await_times_out_when_never_acknowledged() -> None:
    trades = [_Trade("PendingSubmit")]

    class _IB:
        def sleep(self, _s: float) -> None:
            pass  # IB never acks (the phantom-order failure mode)

    assert _await_order_acknowledgements(_IB(), trades, timeout_seconds=0.5, poll_seconds=0.1) is False
    assert trades[0].orderStatus.status == "PendingSubmit"  # true status preserved


# --------------------------------------------------------------------------- #
# place_order_intents_with_ib records the ACKNOWLEDGED status
# --------------------------------------------------------------------------- #
def test_place_records_acknowledged_status_not_transient() -> None:
    placed: list[_Trade] = []

    class _IB:
        def __init__(self) -> None:
            self.pumped = False

        def qualifyContracts(self, _c: Any) -> None: ...

        def bracketOrder(self, **_kw: Any) -> list[_Order]:
            return [_Order("smc-AAA-entry", 1), _Order("smc-AAA-tp", 2), _Order("smc-AAA-sl", 3)]

        def placeOrder(self, _contract: Any, _order: Any) -> _Trade:
            t = _Trade("PendingSubmit")  # transient at placeOrder time
            placed.append(t)
            return t

        def sleep(self, _s: float) -> None:
            # Loop runs -> IB acknowledges the whole bracket.
            self.pumped = True
            for t in placed:
                t.orderStatus.status = "PreSubmitted"

    out = place_order_intents_with_ib(
        _IB(), [_intent()],
        connection_cfg=IBKRConnectionConfig(),
        execution_cfg=_exec_cfg_tp_stop(),
    )
    statuses = [o["status"] for p in out["placements"] for o in p["orders"]]
    # All three legs recorded as acknowledged, NOT the transient PendingSubmit.
    assert statuses == ["PreSubmitted", "PreSubmitted", "PreSubmitted"], statuses


def _exec_cfg_tp_stop() -> Any:
    from scripts.execute_ibkr_watchlist import IBKRExecutionConfig

    return IBKRExecutionConfig(exit_mode="tp-stop", ack_timeout_seconds=5.0)
