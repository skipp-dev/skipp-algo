"""C13 EOD flatten + GTC exit legs (2026-08-18).

Background: the paper campaign placed DAY-tif bracket exits and disconnected;
the executor's client-side time stop never ran, so any position whose tp/sl
did not trigger intraday lost its protection at the bell and stayed open —
nine one-lot zombies accumulated since June and drove the ADR-0032 shadow
gate into permanent rejects. The fix has two halves that MUST both hold:

* exit legs are GTC (protection outlives the session), entries stay DAY;
* the EOD flatten cron closes the book before the bell and hands its fills
  to the nightly reconciliation so the cleanup explains itself.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from governance.portfolio_reconciliation import PortfolioFill
from scripts.c13_eod_flatten import flatten_paper_account, main
from scripts.execute_ibkr_watchlist import _apply_exit_tif

REPO = Path(__file__).resolve().parents[1]


# --- exit-leg tif -----------------------------------------------------------


def _leg(ref: str, tif: str = "DAY") -> SimpleNamespace:
    return SimpleNamespace(orderRef=ref, tif=tif)


def test_exit_legs_get_the_exit_tif_and_the_entry_keeps_day() -> None:
    orders = [_leg("smc-X-entry"), _leg("smc-X-tp"), _leg("smc-X-sl")]
    _apply_exit_tif(orders, "GTC")
    assert orders[0].tif == "DAY"
    assert orders[1].tif == "GTC"
    assert orders[2].tif == "GTC"


def test_trail_leg_is_an_exit_leg_too() -> None:
    orders = [_leg("smc-X-entry"), _leg("smc-X-tp"), _leg("smc-X-trail")]
    _apply_exit_tif(orders, "GTC")
    assert [o.tif for o in orders] == ["DAY", "GTC", "GTC"]


def test_none_exit_tif_changes_nothing() -> None:
    orders = [_leg("smc-X-entry"), _leg("smc-X-tp"), _leg("smc-X-sl")]
    _apply_exit_tif(orders, None)
    assert [o.tif for o in orders] == ["DAY", "DAY", "DAY"]


def test_place_order_intents_wires_the_exit_tif_onto_the_legs() -> None:
    """End-to-end through place_order_intents_with_ib: the entry rests DAY,
    both exit legs rest GTC. Kills a dropped ``_apply_exit_tif`` call site."""
    from datetime import date

    from scripts.execute_ibkr_watchlist import (
        IBKRConnectionConfig,
        IBKRExecutionConfig,
        IBKROrderIntent,
        place_order_intents_with_ib,
    )

    class BracketFakeIB:
        def __init__(self) -> None:
            self.placed: list = []
            self.qualifyContracts = self._qualify_contracts
            self.bracketOrder = self._bracket_order
            self.placeOrder = self._place_order

        def _qualify_contracts(self, contract):
            return [contract]

        def _bracket_order(self, *, action, quantity, limitPrice, takeProfitPrice, stopLossPrice):
            def _order(order_id, order_type, price_attr):
                return SimpleNamespace(
                    orderId=order_id,
                    permId=0,
                    orderRef="",
                    orderType=order_type,
                    action=action if order_type == "LMT" and order_id == 1 else "SELL",
                    lmtPrice=limitPrice,
                    auxPrice=stopLossPrice if order_type == "STP" else 0.0,
                    tif="",
                    outsideRth=False,
                    account="",
                )

            return [_order(1, "LMT", limitPrice), _order(2, "LMT", takeProfitPrice), _order(3, "STP", stopLossPrice)]

        def _place_order(self, contract, order):
            self.placed.append(order)
            return SimpleNamespace(order=order, orderStatus=SimpleNamespace(status="Submitted"))

        def sleep(self, seconds):
            return None

    intent = IBKROrderIntent(
        trade_date=date(2026, 8, 18),
        symbol="NVDA",
        watchlist_rank=1,
        level_tag="orb",
        quantity=1,
        entry_limit=100.0,
        take_profit=110.0,
        stop_loss=95.0,
        trailing_stop_pct=0.02,
        trailing_stop_anchor=100.0,
        premarket_last=100.0,
        gap_pct=1.0,
        tif="DAY",
        outside_rth=False,
        exit_mode="tp-stop",
        order_ref="smc-NVDA-2026-08-18-port7497",
    )
    ib = BracketFakeIB()
    result = place_order_intents_with_ib(
        ib,
        [intent],
        connection_cfg=IBKRConnectionConfig(),
        execution_cfg=IBKRExecutionConfig(exit_tif="GTC", ack_timeout_seconds=0.1),
    )
    tif_by_ref = {str(o.orderRef): str(o.tif) for o in ib.placed}
    assert tif_by_ref == {
        "smc-NVDA-2026-08-18-port7497-entry": "DAY",
        "smc-NVDA-2026-08-18-port7497-tp": "GTC",
        "smc-NVDA-2026-08-18-port7497-sl": "GTC",
    }
    assert result["placements"][0]["rested"] is True


def test_paper_driver_opts_into_gtc_exits() -> None:
    """The C13 paper submitter must pass exit_tif="GTC".

    Source-level pin: the wiring lives inside ``main()`` behind argument
    parsing; the behavioural half (legs actually flipped) is covered above.
    """
    source = (REPO / "scripts" / "run_smc_live_incubation.py").read_text(encoding="utf-8")
    assert 'IBKRWatchlistExecutionConfig(exit_tif="GTC")' in source


# --- flatten ---------------------------------------------------------------


class FakeIB:
    """Stateful paper-TWS double: positions close when their market order
    fills, working orders drain on reqGlobalCancel."""

    def __init__(
        self, *, positions=None, orders=(), cancel_works=True, positions_after_cancel=None
    ) -> None:
        self._positions = dict(positions or {})
        self._orders = list(orders)
        self._cancel_works = cancel_works
        self._positions_after_cancel = positions_after_cancel
        self.global_cancels = 0
        self.placed: list = []
        self.reqAllOpenOrders = self._req_all_open_orders
        self.reqGlobalCancel = self._req_global_cancel
        self.qualifyContracts = self._qualify_contracts
        self.placeOrder = self._place_order

    def _req_all_open_orders(self):
        return list(self._orders)

    def _req_global_cancel(self):
        self.global_cancels += 1
        if self._cancel_works:
            self._orders = []
        if self._positions_after_cancel is not None:
            self._positions = dict(self._positions_after_cancel)

    def positions(self, account=""):
        return [
            SimpleNamespace(
                contract=SimpleNamespace(symbol=symbol),
                position=quantity,
                account="DUP862066",
            )
            for symbol, quantity in self._positions.items()
            if quantity
        ]

    def _qualify_contracts(self, contract):
        return [contract]

    def _place_order(self, contract, order):
        self.placed.append(order)
        symbol = contract.symbol
        filled = abs(self._positions.get(symbol, 0.0))
        self._positions[symbol] = 0.0
        return SimpleNamespace(
            order=SimpleNamespace(orderRef=order.orderRef, orderId=len(self.placed)),
            orderStatus=SimpleNamespace(status="Filled", filled=filled, avgFillPrice=101.5),
        )

    def sleep(self, seconds):
        return None


def _working(symbol: str, ref: str) -> SimpleNamespace:
    return SimpleNamespace(
        contract=SimpleNamespace(symbol=symbol),
        order=SimpleNamespace(orderRef=ref, orderType="STP", account="DUP862066"),
        orderStatus=SimpleNamespace(status="PreSubmitted"),
    )


def test_flatten_cancels_then_closes_and_reports_flat() -> None:
    ib = FakeIB(
        positions={"NVDA": 9.0, "MSFT": -2.0},
        orders=[_working("NVDA", "smc-NVDA-2026-08-18-port7497-sl")],
    )
    report = flatten_paper_account(ib, account="DUP862066", trade_date="2026-08-18")
    assert ib.global_cancels == 1
    assert report["orders_after_cancel"] == 0
    assert {p["symbol"]: p["action"] for p in report["planned_closes"]} == {
        "NVDA": "SELL",
        "MSFT": "BUY",
    }
    assert report["flat"] is True
    assert report["unfilled"] == []
    assert all(o.tif == "DAY" and o.outsideRth is False for o in ib.placed)
    assert {o.orderRef for o in ib.placed} == {
        "smc-eod-flatten-2026-08-18-NVDA",
        "smc-eod-flatten-2026-08-18-MSFT",
    }


def test_close_plan_is_built_after_the_cancel_barrier() -> None:
    """CRITICAL (#4848 review): a bracket leg that fills inside the cancel
    window changes the position; a plan snapshotted BEFORE the barrier then
    over-sells the stale quantity and turns the long into a naked overnight
    short. The plan must come from the post-cancel broker state."""
    ib = FakeIB(
        positions={"NVDA": 9.0},
        orders=[_working("NVDA", "smc-NVDA-2026-08-18-port7497-sl")],
        positions_after_cancel={"NVDA": 8.0},  # sl leg filled 1 lot mid-window
    )
    report = flatten_paper_account(ib, account="DUP862066", trade_date="2026-08-18")
    assert [o.totalQuantity for o in ib.placed] == [8.0]
    assert report["planned_closes"] == [
        {"symbol": "NVDA", "quantity": 8.0, "action": "SELL"}
    ]
    assert report["flat"] is True


def test_partial_fill_stays_in_the_handover() -> None:
    """Important #5: the reconciliation must see the traded quantity even when
    the close order did not finish — dropping partials reddens the night."""

    class PartialFakeIB(FakeIB):
        def _place_order(self, contract, order):
            self.placed.append(order)
            self._positions[contract.symbol] = 6.0  # 3 of 9 traded
            return SimpleNamespace(
                order=SimpleNamespace(orderRef=order.orderRef, orderId=1),
                orderStatus=SimpleNamespace(status="Cancelled", filled=3.0, avgFillPrice=100.0),
            )

    ib = PartialFakeIB(positions={"NVDA": 9.0})
    report = flatten_paper_account(ib, account="DUP862066", trade_date="2026-08-18")
    assert report["fills"][0]["quantity"] == 3.0
    assert report["unfilled"] == [{"symbol": "NVDA", "status": "Cancelled", "filled": 3.0}]
    assert report["flat"] is False


def test_crash_mid_close_keeps_the_fills_already_won() -> None:
    """Important #6: an exception after the first close order must not lose
    that order's fill row — and must not escape as a traceback."""

    class CrashFakeIB(FakeIB):
        def _place_order(self, contract, order):
            if self.placed:
                raise RuntimeError("socket dropped")
            return super()._place_order(contract, order)

    ib = CrashFakeIB(positions={"AMD": 2.0, "NVDA": 9.0})
    report = flatten_paper_account(ib, account="DUP862066", trade_date="2026-08-18")
    assert "close loop aborted" in report["error"]
    assert len(report["fills"]) == 1
    assert report["flat"] is False


def test_cli_refuses_non_paper_account_even_on_gateway_port(monkeypatch, tmp_path) -> None:
    """Important #3: port 4002 passes assert_paper_account_if_paper_port, so
    the resolved account itself must be DU* — a live account is refused."""
    import scripts.c13_eod_flatten as mod

    class LiveFakeIB:
        def __init__(self) -> None:
            self.managedAccounts = lambda: ["U1234567"]

        def disconnect(self):
            return None

    monkeypatch.setattr(mod, "_connect", lambda *a, **k: LiveFakeIB())
    monkeypatch.setattr(mod, "assert_paper_account_if_paper_port", lambda ib, cfg: None)
    rc = mod.main(
        ["--port", "4002", "--date", "2026-08-18", "--fills-output", str(tmp_path / "f.json")]
    )
    assert rc == 1


def test_flatten_fills_round_trip_through_portfolio_fill() -> None:
    """The fills output must load as PortfolioFill rows — that is the contract
    run-c13-reconcile.sh relies on to explain the flatten's position deltas."""
    ib = FakeIB(positions={"NVDA": 9.0})
    report = flatten_paper_account(ib, account="DUP862066", trade_date="2026-08-18")
    rows = json.loads(json.dumps(report["fills"]))
    fills = [PortfolioFill(**row) for row in rows]
    assert fills[0].symbol == "NVDA"
    assert fills[0].side.value == "SELL"
    assert fills[0].quantity == pytest.approx(9.0)


def test_dry_run_places_nothing_and_cancels_nothing() -> None:
    ib = FakeIB(positions={"NVDA": 9.0}, orders=[_working("NVDA", "smc-x-sl")])
    report = flatten_paper_account(
        ib, account="DUP862066", trade_date="2026-08-18", dry_run=True
    )
    assert ib.global_cancels == 0
    assert ib.placed == []
    assert report["planned_closes"] and report["flat"] is False


def test_surviving_working_order_stops_the_flatten() -> None:
    ib = FakeIB(
        positions={"NVDA": 9.0},
        orders=[_working("NVDA", "smc-x-sl")],
        cancel_works=False,
    )
    report = flatten_paper_account(ib, account="DUP862066", trade_date="2026-08-18")
    assert "survived" in report["error"]
    assert ib.placed == []


def test_oversized_position_is_refused() -> None:
    ib = FakeIB(positions={"NVDA": 5000.0})
    report = flatten_paper_account(ib, account="DUP862066", trade_date="2026-08-18")
    assert "close cap" in report["error"]
    assert ib.placed == []


def test_empty_account_is_flat_without_orders() -> None:
    ib = FakeIB()
    report = flatten_paper_account(ib, account="DUP862066", trade_date="2026-08-18")
    assert report["flat"] is True
    assert ib.placed == []
    assert ib.global_cancels == 0


def test_cli_refuses_non_paper_port(tmp_path: Path) -> None:
    rc = main(
        [
            "--port",
            "7496",
            "--date",
            "2026-08-18",
            "--fills-output",
            str(tmp_path / "fills.json"),
        ]
    )
    assert rc == 1


# --- cron wiring ------------------------------------------------------------


def test_eod_flatten_cron_is_et_gated_and_writes_markers() -> None:
    source = (REPO / "automation" / "launchd" / "run-c13-eod-flatten.sh").read_text(
        encoding="utf-8"
    )
    assert 'c13_require_et_window "$REPO" 15 45 10 eod-flatten || exit 0' in source
    assert source.count('_write_marker "DEGRADED"') >= 3
    assert '_write_marker "SUCCESS"' in source
    assert "scripts.c13_eod_flatten" in source
    assert 'portfolio_fills_eod_${DATE}.json' in source


def test_reconcile_cron_hands_the_eod_fills_over() -> None:
    """The 2026-08-18 E5 lesson in reverse: a fills file that is computed but
    never appended to FILLS_ARGS silently reddens the reconciliation."""
    source = (REPO / "automation" / "launchd" / "run-c13-reconcile.sh").read_text(
        encoding="utf-8"
    )
    assert 'EOD_FLATTEN_FILLS="${REPO}/cache/live/portfolio_fills_eod_${DATE}.json"' in source
    assert '[[ -f "${EOD_FLATTEN_FILLS}" ]] && FILLS_ARGS+=(--fills "${EOD_FLATTEN_FILLS}")' in source


def test_eod_flatten_plist_covers_all_three_dst_candidate_hours() -> None:
    plist = (REPO / "automation" / "launchd" / "com.skippalgo.c13.eod-flatten.plist").read_text(
        encoding="utf-8"
    )
    assert "<string>/bin/bash</string>" in plist  # TCC: launchd + shebang trap
    assert "run-c13-eod-flatten.sh" in plist
    for hour in (20, 21, 22):
        assert f"<integer>{hour}</integer>" in plist
    assert plist.count("<key>Weekday</key>") == 15  # Mon-Fri x three candidates
