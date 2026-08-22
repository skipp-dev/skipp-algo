"""C13 end-of-day flatten — close every remaining paper position before the bell.

Why this exists (measured 2026-08-18): the paper campaign submits bracket sets
(entry + tp/sl) and disconnects. The executor's client-side time stop
(``execute_ibkr_watchlist`` ``--time-stop-after``) needs a session that stays
connected until it fires, which the short-lived C13 cron never keeps — so no
exit mechanism ever ran. Positions whose tp/sl did not trigger intraday
outlived their DAY bracket legs and accumulated as unprotected leftovers:
nine one-lot zombies built up since June, pushing the ADR-0032 shadow gate
into permanent ``projected_open_positions`` / ``risk_at_stop_coverage``
rejects (Grafana ``lo-portfolio-risk-rejection``).

This CLI is the missing exit half, fired by the
``com.skippalgo.c13.eod-flatten`` LaunchAgent inside the 15:45 ET gate window
(market still open, brackets had almost the full session to work):

1. ``reqGlobalCancel`` — drains ALL working orders, every client id. The
   bracket legs rest under the submitter's client id; a per-order
   ``cancelOrder`` from another client id is not proven to work, the global
   cancel is (live 2026-08-18: 10 legs → 0). Without this step the OCA sell
   legs would double-sell against the flatten orders below.
2. Market-close every non-zero position in the account (account-wide sweep:
   after the 2026-08-18 manual cleanup everything in this account is
   campaign-born, and an orphan from a previously failed flatten day must be
   caught here, not remembered by a human).
3. Write the fills as a ``PortfolioFill``-shaped JSON list so
   ``run-c13-reconcile.sh`` can hand them to ``reconcile_portfolio_shadow``
   — the flatten explains its own position deltas instead of reddening the
   nightly reconciliation.

Safety posture (same as the submit path): refuses non-paper ports, refuses
non-``DU*`` accounts via ``assert_paper_account_if_paper_port``, caps the
per-position size it is willing to close, and exits non-zero when anything
is left resting or open so the launchd wrapper writes a DEGRADED marker.

Exit codes: 0 = flat (including nothing-to-do), 1 = usage/config/connect
error, 2 = incomplete (orders survived the cancel, a position cap tripped,
a close order did not fill, or the account is not flat afterwards).
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.execute_ibkr_watchlist import (
    IBKRConnectionConfig,
    assert_paper_account_if_paper_port,
)
from scripts.smc_atomic_write import atomic_write_text
from scripts.us_equity_early_closes import close_time_et_hhmm

# TWS paper (7497) and IB Gateway paper (4002); everything else is refused.
PAPER_PORTS = frozenset({7497, 4002})

# A campaign lot is 1-9 shares; anything bigger in this account is foreign
# state a cron must not silently trade against. rc 2 hands it to the operator.
MAX_ABS_CLOSE_QUANTITY = 1000.0

_TERMINAL_ORDER_STATUSES = frozenset({"Filled", "Cancelled", "ApiCancelled", "Inactive"})


def close_guard_verdict(now_et: datetime) -> str | None:
    """Ablehnungsgrund, wenn der US-Kassamarkt fuer now_et bereits zu ist.

    Review 2026-08-18, Important #2: Nach dem Close kann der Flatten nichts
    mehr schliessen — reqGlobalCancel wuerde nur noch den GTC-Schutz toeten
    und die Positionen ungeschuetzt ueber Nacht legen (Halbtage 13:00 ET,
    verspaetete manuelle Laeufe). Vor dem Close: None = weitermachen.
    """
    close_hh, close_mm = close_time_et_hhmm(now_et.date())
    if (now_et.hour, now_et.minute) >= (close_hh, close_mm):
        return (
            f"market for {now_et.date().isoformat()} closed at "
            f"{close_hh:02d}:{close_mm:02d} ET — refusing to cancel GTC exits after the bell"
        )
    return None


def install_sigterm_clean_exit() -> None:
    """SIGTERM in ein SystemExit wandeln, damit ``finally`` noch laeuft.

    Der Wrapper hat seit 2026-08-22 einen Laufzeit-Waechter: haengt der Lauf
    (halbtoter TWS-Socket — am 21.8. 8 h 41 min lang), schiesst er ihn ab,
    sonst startet launchd den Job NIE wieder (kein zweiter Start eines noch
    laufenden Jobs). Ein hartes Signal wuerde aber ``ib.disconnect()``
    ueberspringen und clientId in TWS haengen lassen — der naechste Lauf
    scheiterte dann am Connect und der Waechter haette den Ausfall nur
    verschoben statt behoben. Darum: Signal -> SystemExit -> finally.
    """

    def _handler(signum: int, _frame: Any) -> None:
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, _handler)


def _connect(host: str, port: int, client_id: int, timeout: float) -> Any:
    from ib_async import IB  # deferred: keep module importable without ib_async

    ib = IB()
    ib.connect(host, port, clientId=client_id, timeout=timeout)
    return ib


def _live_orders(ib: Any, account: str) -> list[Any]:
    """All working orders of the account, across every client id."""
    trades = []
    for trade in ib.reqAllOpenOrders() or ():
        order = getattr(trade, "order", None)
        status = str(getattr(getattr(trade, "orderStatus", None), "status", ""))
        if order is None or status in _TERMINAL_ORDER_STATUSES:
            continue
        order_account = str(getattr(order, "account", "") or "")
        if order_account and order_account != account:
            continue
        trades.append(trade)
    return trades


def _open_positions(ib: Any, account: str) -> list[Any]:
    return [
        position
        for position in ib.positions(account)
        if abs(float(getattr(position, "position", 0.0) or 0.0)) > 0.0
    ]


def flatten_paper_account(
    ib: Any,
    *,
    account: str,
    trade_date: str,
    dry_run: bool = False,
    ack_timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    """Cancel every working order, then market-close every open position."""
    from ib_async import MarketOrder, Stock  # deferred, see _connect

    report: dict[str, Any] = {
        "account": account,
        "trade_date": trade_date,
        "dry_run": dry_run,
        "started_at": datetime.now(UTC).isoformat(),
        "orders_before": [],
        "orders_after_cancel": 0,
        "planned_closes": [],
        "fills": [],
        "unfilled": [],
        "flat": False,
    }

    orders_before = _live_orders(ib, account)
    report["orders_before"] = [
        {
            "symbol": str(getattr(getattr(t, "contract", None), "symbol", "")),
            "order_ref": str(getattr(t.order, "orderRef", "")),
            "order_type": str(getattr(t.order, "orderType", "")),
        }
        for t in orders_before
    ]

    def _plan_closes() -> list[dict[str, Any]] | None:
        """Close plan from the CURRENT broker state; None if a cap trips."""
        plans: list[dict[str, Any]] = []
        for position in _open_positions(ib, account):
            symbol = str(getattr(position.contract, "symbol", "")).strip().upper()
            quantity = float(position.position)
            if abs(quantity) > MAX_ABS_CLOSE_QUANTITY:
                report["error"] = (
                    f"position {symbol} quantity {quantity} exceeds the close cap "
                    f"{MAX_ABS_CLOSE_QUANTITY}; refusing to trade foreign state"
                )
                return None
            plans.append(
                {
                    "symbol": symbol,
                    "quantity": quantity,
                    "action": "SELL" if quantity > 0 else "BUY",
                }
            )
        return plans

    if dry_run:
        plans = _plan_closes()
        report["planned_closes"] = plans or []
        report["flat"] = plans == []
        return report

    if orders_before:
        ib.reqGlobalCancel()
        waited = 0.0
        while waited < 15.0 and _live_orders(ib, account):
            ib.sleep(1.0)
            waited += 1.0
    leftovers = _live_orders(ib, account)
    report["orders_after_cancel"] = len(leftovers)
    if leftovers:
        report["error"] = f"{len(leftovers)} working order(s) survived reqGlobalCancel"
        return report

    # Plan from the POST-cancel broker state, never before it. Review 2026-08-18
    # (#4848 critical): a bracket leg that fills inside the cancel window
    # changes the position; a plan snapshotted before the barrier then
    # over-sells the stale quantity and turns a long into a naked overnight
    # short (or leaves a fresh entry unplanned and unprotected).
    plans = _plan_closes()
    if plans is None:
        return report
    report["planned_closes"] = plans

    trades = []
    try:
        for plan in report["planned_closes"]:
            contract = Stock(plan["symbol"], "SMART", "USD")
            ib.qualifyContracts(contract)
            order = MarketOrder(plan["action"], abs(plan["quantity"]))
            order.tif = "DAY"
            order.outsideRth = False
            order.orderRef = f"smc-eod-flatten-{trade_date}-{plan['symbol']}"
            order.account = account
            trades.append((plan, ib.placeOrder(contract, order)))

        waited = 0.0
        while waited < ack_timeout_seconds:
            if all(
                str(trade.orderStatus.status) in _TERMINAL_ORDER_STATUSES
                for _, trade in trades
            ):
                break
            ib.sleep(1.0)
            waited += 1.0
    except Exception as exc:  # keep the fills already won — see below
        # A crash mid-close must not lose the fills of the orders that DID go
        # out: without their rows the nightly reconciliation sees unexplained
        # deltas on top of the failure (review 2026-08-18, Important #6).
        report["error"] = f"close loop aborted: {type(exc).__name__}: {exc}"

    for plan, trade in trades:
        status = str(trade.orderStatus.status)
        filled = float(trade.orderStatus.filled or 0.0)
        if filled > 0.0:
            # Partial fills stay in the handover (review 2026-08-18, Important
            # #5): the reconciliation must see the quantity that actually
            # traded, whatever the order status says.
            report["fills"].append(
                {
                    "execution_id": f"{trade.order.orderRef}-{int(trade.order.orderId)}",
                    "symbol": plan["symbol"],
                    "account": account,
                    "side": plan["action"],
                    "quantity": filled,
                    "price": float(trade.orderStatus.avgFillPrice or 0.0),
                }
            )
        if status != "Filled" or filled < abs(plan["quantity"]):
            report["unfilled"].append(
                {"symbol": plan["symbol"], "status": status, "filled": filled}
            )

    remaining = _open_positions(ib, account)
    if remaining and not report.get("error"):
        # Positions-Events koennen dem Terminal-Orderstatus um einen Takt
        # nachlaufen (Review Minor #9): einmal absetzen und neu lesen, bevor
        # ein Phantom-Rest ein falsches DEGRADED ausloest.
        ib.sleep(2.0)
        remaining = _open_positions(ib, account)
    report["flat"] = not report.get("error") and not remaining
    report["finished_at"] = datetime.now(UTC).isoformat()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7497)
    parser.add_argument("--client-id", type=int, default=74)
    parser.add_argument("--account", default=None)
    parser.add_argument("--date", required=True, help="Trade date YYYY-MM-DD (stamped into order refs and the fills file)")
    parser.add_argument("--fills-output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--ack-timeout-seconds", type=float, default=60.0)
    # Test-Hook (geborgte Uhr LIEFERN): ISO-Zeitstempel, ueberschreibt die
    # ET-Wanduhr fuer close_guard_verdict. Produktion laesst ihn weg.
    parser.add_argument("--now-et", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    install_sigterm_clean_exit()

    if args.port not in PAPER_PORTS:
        print(f"eod-flatten: refusing non-paper port {args.port}", file=sys.stderr)
        return 1

    now_et = (
        datetime.fromisoformat(args.now_et)
        if args.now_et
        else datetime.now(ZoneInfo("America/New_York"))
    )
    verdict = close_guard_verdict(now_et)
    if verdict and not args.dry_run:
        print(f"eod-flatten: {verdict}", file=sys.stderr)
        return 1

    try:
        ib = _connect(args.host, args.port, args.client_id, timeout=20.0)
    except Exception as exc:  # connection failure is a config/ops error, not incomplete
        print(f"eod-flatten: connect failed: {exc}", file=sys.stderr)
        return 1
    try:
        connection_cfg = IBKRConnectionConfig(
            host=args.host, port=args.port, client_id=args.client_id, account=args.account
        )
        assert_paper_account_if_paper_port(ib, connection_cfg)
        accounts = list(ib.managedAccounts() or [])
        account = args.account or (accounts[0] if len(accounts) == 1 else None)
        if not account or account not in accounts:
            print(
                f"eod-flatten: cannot resolve account (managed={accounts}, requested={args.account})",
                file=sys.stderr,
            )
            return 1
        # Unconditional paper guard on the RESOLVED account (review 2026-08-18,
        # Important #3): assert_paper_account_if_paper_port only bites on port
        # 7497, but this CLI also accepts Gateway-paper 4002 — a live account
        # reachable there must be refused here, not traded flat.
        if not account.startswith("DU"):
            print(
                f"eod-flatten: refusing non-paper account {account!r} (DU* required)",
                file=sys.stderr,
            )
            return 1

        report = flatten_paper_account(
            ib,
            account=account,
            trade_date=args.date,
            dry_run=args.dry_run,
            ack_timeout_seconds=args.ack_timeout_seconds,
        )
    finally:
        ib.disconnect()

    if not args.dry_run:
        atomic_write_text(
            json.dumps(report["fills"], indent=2, sort_keys=True) + "\n", args.fills_output
        )
    if args.report_output is not None:
        atomic_write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", args.report_output
        )

    print(
        f"eod-flatten: {len(report['planned_closes'])} position(s), "
        f"{len(report['fills'])} closed, {len(report['unfilled'])} unfilled, "
        f"flat={report['flat']} dry_run={report['dry_run']}"
    )
    if report.get("error"):
        print(f"eod-flatten: {report['error']}", file=sys.stderr)
        return 2
    if not report["flat"] and not args.dry_run:
        print("eod-flatten: account is NOT flat after close orders", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
