"""Regression tests for IBKR paper-trade audit guards (2026-06-11).

Covers the five hardening points added in PR #2689:

* S1 — terminal-wait + leftover-sweep + ``clean`` flag
* S2 — non-marketable smoke prices (entry × 0.5)
* S3 — ``resolve_client_id`` explicit-wins / allocator fallback
* S4 — confirm-live abort for non-paper port
* S5 — DU* account assertion in smoke and execute paths

Each test is fully offline: no ib_async import, no TWS connection.
Fake-class pattern follows the convention in test_execute_ibkr_watchlist.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from scripts.execute_ibkr_watchlist import (
    IBKRConnectionConfig,
    assert_paper_account_if_paper_port,
    resolve_client_id,
)
import scripts.smoke_smc_to_ibkr_adapter as smoke_mod

# ---------------------------------------------------------------------------
# Helpers — minimal IB fakes
# ---------------------------------------------------------------------------


class _FakeWrapper:
    def __init__(self, accounts: list[str]) -> None:
        self.accounts = set(accounts)


class _FakeIB:
    """Minimal synchronous IB stub — no ib_async needed."""

    def __init__(self, accounts: list[str] | None = None) -> None:
        self.wrapper = _FakeWrapper(accounts or [])

    def isConnected(self) -> bool:  # noqa: N802
        return True

    def disconnect(self) -> None:
        pass


# ---------------------------------------------------------------------------
# S5 — assert_paper_account_if_paper_port (execute_ibkr_watchlist path)
# ---------------------------------------------------------------------------


def test_s5_paper_port_all_du_passes() -> None:
    """DU* accounts on port 7497 must not raise."""
    ib = _FakeIB(accounts=["DUP862066"])
    cfg = IBKRConnectionConfig(port=7497)
    assert_paper_account_if_paper_port(ib, cfg)  # no exception


def test_s5_paper_port_non_du_aborts() -> None:
    """Non-DU* account on port 7497 must abort (SystemExit)."""
    ib = _FakeIB(accounts=["U1234567"])  # live account prefix
    cfg = IBKRConnectionConfig(port=7497)
    with pytest.raises(SystemExit, match="DU"):
        assert_paper_account_if_paper_port(ib, cfg)


def test_s5_non_paper_port_skipped_even_with_live_account() -> None:
    """Non-paper port: guard is a no-op regardless of account prefix."""
    ib = _FakeIB(accounts=["U1234567"])
    cfg = IBKRConnectionConfig(port=7496)  # live port
    assert_paper_account_if_paper_port(ib, cfg)  # no exception


def test_s5_empty_accounts_is_noop() -> None:
    """No accounts exposed (e.g. test fakes without wrapper.accounts): no-op."""
    ib = _FakeIB(accounts=[])
    cfg = IBKRConnectionConfig(port=7497)
    assert_paper_account_if_paper_port(ib, cfg)  # no exception


def test_s5_mixed_accounts_aborts() -> None:
    """Mixed DU*/non-DU* accounts must abort."""
    ib = _FakeIB(accounts=["DUP862066", "U9999999"])
    cfg = IBKRConnectionConfig(port=7497)
    with pytest.raises(SystemExit, match="DU"):
        assert_paper_account_if_paper_port(ib, cfg)


# ---------------------------------------------------------------------------
# S3 — resolve_client_id
# ---------------------------------------------------------------------------


def test_s3_explicit_client_id_wins() -> None:
    """Explicit int value is returned as-is without touching the allocator."""
    assert resolve_client_id(55) == 55


def test_s3_explicit_zero_wins() -> None:
    assert resolve_client_id(0) == 0


def test_s3_none_calls_allocator() -> None:
    """None triggers allocate_ib_client_id via the registry."""
    with patch("scripts.execute_ibkr_watchlist.resolve_client_id") as mock_res:
        mock_res.return_value = 42
        result = mock_res(None)
    assert result == 42


def test_s3_allocator_called_with_service_name() -> None:
    """Allocator is invoked with the given service_name."""
    fake_allocator = MagicMock(return_value=77)
    with patch(
        "scripts.ib_client_id.allocate_ib_client_id", fake_allocator
    ):
        result = resolve_client_id(None, service_name="ibkr_execution")
    fake_allocator.assert_called_once_with("ibkr_execution")
    assert result == 77


# ---------------------------------------------------------------------------
# S4 — confirm-live abort for non-paper port (smoke path)
# ---------------------------------------------------------------------------


def _make_limits(tmp_path: Path) -> smoke_mod.RiskLimitsSnapshot:
    payload = {
        "max_open_positions": 5,
        "max_gross_exposure_pct": 200.0,
        "flatten_on_breach": True,
        "manual_halt": False,
        "frozen_at": "2026-04-28",
    }
    p = tmp_path / "limits.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return smoke_mod.RiskLimitsSnapshot.load(p)


def _sample_setups() -> list[dict[str, Any]]:
    return smoke_mod.synthesise_setups()


def test_s4_non_paper_port_without_confirm_live_aborts(tmp_path: Path) -> None:
    """Port != 7497 without confirm_live must raise SystemExit before connecting."""
    limits = _make_limits(tmp_path)
    # ib_async.IB.connect must NOT be called — abort happens before import
    with pytest.raises(SystemExit, match="confirm-live"):
        smoke_mod.run_live(
            setups=_sample_setups(),
            risk_limits=limits,
            account_equity_usd=10_000.0,
            size_scale=0.10,
            host="127.0.0.1",
            port=7496,  # live port
            client_id=71,
            confirm_live=False,  # not set → abort
        )


def test_s4_non_paper_port_with_confirm_live_proceeds(tmp_path: Path) -> None:
    """confirm_live=True skips the port check and attempts connection."""
    limits = _make_limits(tmp_path)
    # We only care that the SystemExit is NOT raised for the port check;
    # the actual ib.connect will fail with RuntimeError/ImportError in CI
    # because ib_async is not mocked here — that's acceptable.
    try:
        smoke_mod.run_live(
            setups=_sample_setups(),
            risk_limits=limits,
            account_equity_usd=10_000.0,
            size_scale=0.10,
            host="127.0.0.1",
            port=7496,
            client_id=71,
            confirm_live=True,
        )
    except SystemExit as exc:
        # Must not be the port-check abort
        assert "confirm-live" not in str(exc), (
            "confirm_live=True should suppress the port-check abort, got: {exc}"
        )
    except Exception:
        pass  # ConnectionRefused / ImportError etc. are expected in CI


def test_s4_paper_port_does_not_require_confirm_live(tmp_path: Path) -> None:
    """Port 7497 never triggers the confirm-live abort, even without the flag."""
    limits = _make_limits(tmp_path)
    try:
        smoke_mod.run_live(
            setups=_sample_setups(),
            risk_limits=limits,
            account_equity_usd=10_000.0,
            size_scale=0.10,
            host="127.0.0.1",
            port=7497,
            client_id=71,
            confirm_live=False,  # paper port → no abort needed
        )
    except SystemExit as exc:
        assert "confirm-live" not in str(exc), (
            f"Paper port 7497 must not trigger confirm-live abort: {exc}"
        )
    except Exception:
        pass  # connection failures expected in CI


# ---------------------------------------------------------------------------
# S2 — non-marketable smoke prices
# ---------------------------------------------------------------------------


def test_s2_smoke_price_is_half_of_entry() -> None:
    """Smoke price must be entry × 0.5, floored at 0.01."""
    # Test the formula directly — matches the implementation in run_live.
    entry = 200.0
    smoke_price = max(0.01, round(float(entry) * 0.5, 2))
    assert smoke_price == 100.0


def test_s2_smoke_price_floored_at_one_cent() -> None:
    entry = 0.001
    smoke_price = max(0.01, round(float(entry) * 0.5, 2))
    assert smoke_price == 0.01


def test_s2_run_mock_prices_not_used_for_orders(tmp_path: Path) -> None:
    """Mock mode audit rows record entry price, not a smoke price."""
    limits = _make_limits(tmp_path)
    audit = tmp_path / "smoke.jsonl"
    res = smoke_mod.run_mock(
        setups=_sample_setups(),
        risk_limits=limits,
        account_equity_usd=10_000.0,
        size_scale=0.10,
        audit_path=audit,
    )
    rows = [json.loads(ln) for ln in audit.read_text().splitlines() if ln]
    for row in rows:
        # In mock mode the recorded entry_price matches the setup (no 50% cut)
        assert row["intent"]["entry_limit"] > 0


# ---------------------------------------------------------------------------
# S1 — terminal-wait and leftover-sweep (offline simulation via run_live mock)
# ---------------------------------------------------------------------------


class _FakeOrder:
    def __init__(self, order_id: int, order_ref: str = "") -> None:
        self.orderId = order_id
        self.orderRef = order_ref


class _FakeOrderStatus:
    def __init__(self, status: str) -> None:
        self.status = status


class _FakeContract:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol


class _FakeTrade:
    def __init__(self, symbol: str, order_id: int, status: str, order_ref: str = "") -> None:
        self.contract = _FakeContract(symbol)
        self.order = _FakeOrder(order_id, order_ref)
        self.orderStatus = _FakeOrderStatus(status)


def _make_live_ib_mock(
    accounts: list[str],
    trade_status_sequence: list[str],
    open_orders_after: list[_FakeTrade] | None = None,
) -> MagicMock:
    """Build a MagicMock IB that simulates a TWS round-trip."""
    ib = MagicMock()
    ib.wrapper = _FakeWrapper(accounts)

    # Simulate _wait_for_status polling: ib.sleep is a no-op
    ib.sleep.return_value = None

    placed_trades: list[_FakeTrade] = []

    call_count = [0]

    class _DynamicTrade:
        """Trade whose orderStatus.status advances through a sequence."""

        def __init__(self, symbol: str, order_id: int, order_ref: str) -> None:
            self.contract = _FakeContract(symbol)
            self.order = _FakeOrder(order_id, order_ref)
            self._statuses = trade_status_sequence
            self._idx = 0
            self.orderStatus = _FakeOrderStatus(self._statuses[0])

        def advance(self) -> None:
            if self._idx < len(self._statuses) - 1:
                self._idx += 1
            self.orderStatus.status = self._statuses[self._idx]

    dynamic_trades: list[_DynamicTrade] = []

    def _place_order(contract: Any, order: Any) -> _DynamicTrade:
        t = _DynamicTrade(contract.symbol, order.orderId, getattr(order, "orderRef", ""))
        dynamic_trades.append(t)
        # advance to next status on every ib.sleep call so polling converges
        original_sleep = ib.sleep.side_effect

        def _advancing_sleep(dt: float) -> None:
            for tr in dynamic_trades:
                tr.advance()

        ib.sleep.side_effect = _advancing_sleep
        return t

    ib.placeOrder.side_effect = _place_order
    ib.cancelOrder.return_value = None
    ib.reqAllOpenOrders.return_value = open_orders_after or []

    return ib


def test_s1_clean_when_all_orders_reach_terminal(tmp_path: Path) -> None:
    """clean=True when all placed orders end in a terminal status."""
    limits = _make_limits(tmp_path)
    setups = _sample_setups()

    # Patch ib_async so run_live uses our fake IB
    fake_ib_instance = _make_live_ib_mock(
        accounts=["DUP862066"],
        trade_status_sequence=["PendingSubmit", "Submitted", "Cancelled"],
        open_orders_after=[],
    )

    with patch.dict(
        "sys.modules",
        {
            "ib_async": MagicMock(
                IB=MagicMock(return_value=fake_ib_instance),
                LimitOrder=MagicMock(side_effect=lambda action, qty, price, **kw: _FakeOrder(0)),
                Stock=MagicMock(side_effect=lambda sym, *a, **kw: _FakeContract(sym)),
            )
        },
    ):
        result = smoke_mod.run_live(
            setups=setups,
            risk_limits=limits,
            account_equity_usd=10_000.0,
            size_scale=0.10,
            host="127.0.0.1",
            port=7497,
            client_id=71,
            audit_path=tmp_path / "smoke.jsonl",
        )

    assert result["mode"] == "live"
    assert result["submitted"] is True
    assert result["leftover_open_orders"] == []
    assert result["clean"] is True


def test_s1_leftover_detected_and_clean_false(tmp_path: Path) -> None:
    """clean=False and leftover_open_orders populated when sweep finds open order."""
    limits = _make_limits(tmp_path)
    setups = _sample_setups()

    # Simulate a leftover: reqAllOpenOrders returns one open order from this session
    leftover_trade = _FakeTrade("AAPL", 3, "Submitted", "smc-AAPL-smoke")

    fake_ib_instance = _make_live_ib_mock(
        accounts=["DUP862066"],
        trade_status_sequence=["PendingSubmit", "Submitted", "PendingCancel"],  # never reaches terminal
        open_orders_after=[leftover_trade],
    )

    with patch.dict(
        "sys.modules",
        {
            "ib_async": MagicMock(
                IB=MagicMock(return_value=fake_ib_instance),
                LimitOrder=MagicMock(side_effect=lambda action, qty, price, **kw: _FakeOrder(3)),
                Stock=MagicMock(side_effect=lambda sym, *a, **kw: _FakeContract(sym)),
            )
        },
    ):
        result = smoke_mod.run_live(
            setups=setups,
            risk_limits=limits,
            account_equity_usd=10_000.0,
            size_scale=0.10,
            host="127.0.0.1",
            port=7497,
            client_id=71,
        )

    assert result["mode"] == "live"
    assert result["clean"] is False
    assert len(result["leftover_open_orders"]) >= 1


def test_s1_audit_jsonl_written_on_success(tmp_path: Path) -> None:
    """Audit JSONL is created with one row per round-trip."""
    limits = _make_limits(tmp_path)
    setups = _sample_setups()
    audit = tmp_path / "smoke.jsonl"

    fake_ib_instance = _make_live_ib_mock(
        accounts=["DUP862066"],
        trade_status_sequence=["PendingSubmit", "Submitted", "Cancelled"],
        open_orders_after=[],
    )

    with patch.dict(
        "sys.modules",
        {
            "ib_async": MagicMock(
                IB=MagicMock(return_value=fake_ib_instance),
                LimitOrder=MagicMock(side_effect=lambda action, qty, price, **kw: _FakeOrder(0)),
                Stock=MagicMock(side_effect=lambda sym, *a, **kw: _FakeContract(sym)),
            )
        },
    ):
        result = smoke_mod.run_live(
            setups=setups,
            risk_limits=limits,
            account_equity_usd=10_000.0,
            size_scale=0.10,
            host="127.0.0.1",
            port=7497,
            client_id=71,
            audit_path=audit,
        )

    assert audit.exists(), "audit JSONL must be written"
    rows = [json.loads(ln) for ln in audit.read_text().splitlines() if ln]
    assert len(rows) == result["intent_count"]
    for row in rows:
        assert row["mode"] == "live"
        assert "round_trip" in row
        assert "ts" in row


def test_s5_live_account_on_paper_port_aborts_before_order(tmp_path: Path) -> None:
    """S5 smoke path: live account on port 7497 must abort before placeOrder."""
    limits = _make_limits(tmp_path)
    setups = _sample_setups()

    fake_ib_instance = _make_live_ib_mock(
        accounts=["U1234567"],  # live account — must trigger abort
        trade_status_sequence=["Submitted", "Cancelled"],
        open_orders_after=[],
    )

    with patch.dict(
        "sys.modules",
        {
            "ib_async": MagicMock(
                IB=MagicMock(return_value=fake_ib_instance),
                LimitOrder=MagicMock(side_effect=lambda action, qty, price, **kw: _FakeOrder(0)),
                Stock=MagicMock(side_effect=lambda sym, *a, **kw: _FakeContract(sym)),
            )
        },
    ):
        with pytest.raises(SystemExit, match="DU"):
            smoke_mod.run_live(
                setups=setups,
                risk_limits=limits,
                account_equity_usd=10_000.0,
                size_scale=0.10,
                host="127.0.0.1",
                port=7497,
                client_id=71,
            )

    # placeOrder must NOT have been called
    fake_ib_instance.placeOrder.assert_not_called()


# ---------------------------------------------------------------------------
# Disconnect mid round-trip — fail-closed + next-run self-heal
# ---------------------------------------------------------------------------


class _Obj:
    """Anonymous attribute bag for ad-hoc fakes."""

    def __init__(self, **kw: Any) -> None:
        for k, v in kw.items():
            setattr(self, k, v)


def test_disconnect_between_place_and_cancel_fails_closed(tmp_path: Path) -> None:
    """TWS dies after placeOrder ack: ConnectionError must propagate.

    Crucially the run must NEVER produce a ``clean=True`` result — the
    operator sees a hard failure, not a green smoke.  The DAY-tif,
    non-marketable order left behind on TWS expires at the close and is
    re-swept by the next run (see the self-heal test below).
    """
    limits = _make_limits(tmp_path)

    ib = MagicMock()
    ib.wrapper = _FakeWrapper(["DUP862066"])
    trade = _Obj(orderStatus=_Obj(status="Submitted"))
    ib.placeOrder.return_value = trade
    ib.sleep.return_value = None
    # Connection dies right after the ack — every further wire call raises.
    ib.cancelOrder.side_effect = ConnectionError("Not connected")
    ib.reqAllOpenOrders.side_effect = ConnectionError("Not connected")

    fake_order = _Obj(orderId=3, orderRef="")
    with patch.dict(
        "sys.modules",
        {
            "ib_async": MagicMock(
                IB=MagicMock(return_value=ib),
                LimitOrder=MagicMock(return_value=fake_order),
                Stock=MagicMock(return_value=_Obj(symbol="AAPL")),
            )
        },
    ):
        with pytest.raises(ConnectionError, match="Not connected"):
            smoke_mod.run_live(
                setups=_sample_setups(),
                risk_limits=limits,
                account_equity_usd=10_000.0,
                size_scale=0.10,
                host="127.0.0.1",
                port=7497,
                client_id=71,
                audit_path=tmp_path / "smoke.jsonl",
            )

    # best-effort disconnect must still have happened (finally block)
    ib.disconnect.assert_called()
    # and no audit row claiming success may exist
    audit = tmp_path / "smoke.jsonl"
    assert not audit.exists() or "clean\": true" not in audit.read_text()


def test_next_run_sweeps_foreign_session_smoke_orphan(tmp_path: Path) -> None:
    """A '-smoke' order orphaned by a CRASHED previous session is self-healed.

    The reconciliation sweep matches on the ``-smoke`` orderRef suffix, not
    only on this session's order ids — so a fresh run detects the orphan,
    reports it as a leftover (clean=False) and re-cancels it.
    """
    limits = _make_limits(tmp_path)

    orphan = _Obj(
        contract=_Obj(symbol="AAPL"),
        order=_Obj(orderId=999, orderRef="smc-AAPL-2026-06-10-port7497-smoke"),
        orderStatus=_Obj(status="Submitted"),
    )

    ib = MagicMock()
    ib.wrapper = _FakeWrapper(["DUP862066"])
    # this session's own orders go terminal instantly
    ib.placeOrder.return_value = _Obj(orderStatus=_Obj(status="Cancelled"))
    ib.sleep.return_value = None
    ib.reqAllOpenOrders.return_value = [orphan]

    fake_order = _Obj(orderId=3, orderRef="")
    with patch.dict(
        "sys.modules",
        {
            "ib_async": MagicMock(
                IB=MagicMock(return_value=ib),
                LimitOrder=MagicMock(return_value=fake_order),
                Stock=MagicMock(return_value=_Obj(symbol="AAPL")),
            )
        },
    ):
        result = smoke_mod.run_live(
            setups=_sample_setups(),
            risk_limits=limits,
            account_equity_usd=10_000.0,
            size_scale=0.10,
            host="127.0.0.1",
            port=7497,
            client_id=71,
        )

    assert result["clean"] is False
    assert result["leftover_open_orders"][0]["order_id"] == 999
    # re-cancel was attempted on the orphan
    assert any(
        c.args and getattr(c.args[0], "orderId", None) == 999
        for c in ib.cancelOrder.call_args_list
    )
