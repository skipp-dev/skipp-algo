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
from scripts.c13_eod_flatten import close_guard_verdict, flatten_paper_account, main
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
    # 2026-08-19 (Review Important #2): 15 45 -> dynamisches Ziel aus dem
    # Fruehschluss-Kalender; die Ziel-Herkunft pinnt
    # test_flatten_wrapper_targets_the_days_close_from_the_calendar.
    assert 'c13_require_et_window "$REPO" "${TARGET_HH}" "${TARGET_MM}" 10 eod-flatten || exit 0' in source
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


def test_eod_flatten_plist_covers_both_dst_candidate_brackets() -> None:
    plist = (REPO / "automation" / "launchd" / "com.skippalgo.c13.eod-flatten.plist").read_text(
        encoding="utf-8"
    )
    assert "<string>/bin/bash</string>" in plist  # TCC: launchd + shebang trap
    assert "run-c13-eod-flatten.sh" in plist
    # 2026-08-19 (Review Important #2): 15 -> 30 Eintraege — zweite Kandidaten-
    # Klammer 17/18/19 Uhr lokal fuer das 12:45-ET-Ziel an Halbtagen.
    for hour in (17, 18, 19, 20, 21, 22):
        assert f"<integer>{hour}</integer>" in plist
    assert plist.count("<key>Weekday</key>") == 30  # Mon-Fri x six candidates


def test_every_plist_candidate_reaches_the_gate_for_both_calendar_cases() -> None:
    """Die 30 Feuerzeiten der Plist gegen das ET-Ziel + die Gate-Toleranz rechnen.

    2026-08-19 (Doppelgaenger K2): gepinnt waren nur die sechs STUNDEN. Die
    Minute (30x ``45``) haing an keinem Waechter, obwohl sie mit
    ``_FLATTEN_LEAD_MINUTES`` (Ziel = Close - 15) und der Gate-Toleranz (10 min
    in run-c13-eod-flatten.sh) EINE Wahrheit bildet: setzt jemand das Lead auf
    30, wird das Ziel 15:30 ET, die Plist feuert weiter :45, ``diff=15 > tol=10``
    — und das Gate no-optet JEDEN Tag stumm (nur stderr, kein Marker, kein
    DEGRADED). Der Flatten faellt lautlos aus, der Zombie-Generator ist zurueck.

    Dieser Test leitet die Wahrheit ab statt sie zu wiederholen: er liest die
    Minuten aus der Plist, das Ziel aus ``flatten_target_et_hhmm`` und die
    Toleranz aus dem Wrapper, und verlangt fuer BEIDE Kalenderfaelle (Regeltag
    und 13:00-ET-Halbtag), dass mindestens eine Kandidaten-Minute im Fenster
    liegt — und zwar in jeder der drei DST-Verschiebungen (+5/+6/+7 h).
    """
    import re
    from datetime import date as date_type

    from scripts.us_equity_early_closes import EARLY_CLOSES_ET_1300, flatten_target_et_hhmm

    plist = (REPO / "automation" / "launchd" / "com.skippalgo.c13.eod-flatten.plist").read_text(
        encoding="utf-8"
    )
    wrapper = (REPO / "automation" / "launchd" / "run-c13-eod-flatten.sh").read_text(
        encoding="utf-8"
    )

    gate = re.search(r'c13_require_et_window\s+"\$REPO"\s+\S+\s+\S+\s+(\d+)\s+eod-flatten', wrapper)
    assert gate, "Gate-Aufruf in run-c13-eod-flatten.sh nicht gefunden"
    tolerance = int(gate.group(1))

    minutes = {int(m) for m in re.findall(r"<key>Minute</key>\s*<integer>(\d+)</integer>", plist)}
    assert minutes, "Keine Minute in der Plist gefunden — Regex gebrochen?"

    regular_day = date_type(2026, 8, 19)
    assert regular_day not in EARLY_CLOSES_ET_1300
    assert EARLY_CLOSES_ET_1300, "Halbtags-Kalender leer — Fall waere unbelegt"
    early_day = sorted(EARLY_CLOSES_ET_1300)[0]

    for day, label in ((regular_day, "Regeltag"), (early_day, "Halbtag")):
        target_hh, target_mm = flatten_target_et_hhmm(day)
        # Die lokale Stunde ist DST-abhaengig (+5/+6/+7), die MINUTE nicht —
        # deshalb entscheidet allein sie ueber |now - target| des Gates.
        hits = [mm for mm in minutes if abs(mm - target_mm) <= tolerance]
        assert hits, (
            f"{label}: Ziel {target_hh:02d}:{target_mm:02d} ET, Toleranz {tolerance} min, "
            f"Plist-Minuten {sorted(minutes)} — keine Kandidaten-Minute im Fenster: "
            "das Gate no-optet jeden Tag stumm"
        )


# --- Halbtage / After-Close-Sperre (Review 2026-08-18 Important #2) ---------


def test_close_guard_allows_before_and_refuses_after_the_bell() -> None:
    """Geborgte Uhr geliefert: beide Seiten der Grenze, beide Kalenderfaelle."""
    from datetime import datetime

    # Normaltag: Close 16:00 ET.
    assert close_guard_verdict(datetime(2026, 8, 19, 15, 59)) is None
    verdict_regular = close_guard_verdict(datetime(2026, 8, 19, 16, 0))
    assert verdict_regular is not None and "16:00" in verdict_regular

    # Halbtag (Freitag nach Thanksgiving): Close 13:00 ET — ein 15:45-Lauf
    # waere hier genau die Inversion, die der Review beschrieb.
    assert close_guard_verdict(datetime(2026, 11, 27, 12, 44)) is None
    verdict_half = close_guard_verdict(datetime(2026, 11, 27, 13, 0))
    assert verdict_half is not None and "13:00" in verdict_half
    assert close_guard_verdict(datetime(2026, 11, 27, 15, 45)) is not None


def test_main_refuses_after_close_before_touching_the_broker(tmp_path, capsys) -> None:
    """Nach dem Bell: rc 1 VOR jedem Connect — reqGlobalCancel darf den
    GTC-Schutz nicht mehr anfassen. Kein FakeIB noetig: der Lauf endet vor
    dem Broker, sonst wuerde der Connect hier laut scheitern."""
    rc = main(
        [
            "--date",
            "2026-11-27",
            "--fills-output",
            str(tmp_path / "fills.json"),
            "--now-et",
            "2026-11-27T13:05:00",
        ]
    )
    assert rc == 1
    assert "refusing to cancel GTC exits after the bell" in capsys.readouterr().err
    assert not (tmp_path / "fills.json").exists()


def test_flatten_wrapper_targets_the_days_close_from_the_calendar() -> None:
    """Die Shell fragt die Python-Single-Source nach dem Gate-Ziel, statt
    Datumslisten zu replizieren (Doppelgaenger-Regel)."""
    source = (REPO / "automation" / "launchd" / "run-c13-eod-flatten.sh").read_text(
        encoding="utf-8"
    )
    assert '-m scripts.us_equity_early_closes --date "${ET_DATE}"' in source
    assert 'c13_require_et_window "$REPO" "${TARGET_HH}" "${TARGET_MM}" 10 eod-flatten' in source
    # Das venv-Preflight MUSS vor dem Gate stehen, sonst gibt es kein Python
    # fuer den Kalender.
    assert source.index('source "${VENV}/bin/activate"') < source.index("c13_require_et_window")


# --- Marker-Konsument + E5-Nachschaerfung (Review Important #4 / Minor #11) --


def test_reconcile_cron_consumes_the_flatten_marker() -> None:
    """Ein Handelstag ohne SUCCESS-Flatten-Marker degradiert die Abstimmung —
    vorher konnte der Flatten-Cron tagelang still scheitern (kein Konsument)."""
    source = (REPO / "automation" / "launchd" / "run-c13-reconcile.sh").read_text(
        encoding="utf-8"
    )
    assert 'EOD_FLATTEN_MARKER="${REPO}/cache/live/.eod_flatten_status_${DATE}"' in source
    assert "grep -q '^SUCCESS' \"${EOD_FLATTEN_MARKER}\"" in source
    assert "eod-flatten-missing-or-degraded" in source
    # Die Degradierung faellt am ENDE (Telemetrie + Push laufen durch, R6-
    # Muster) — nicht als Early-Exit vor der Abstimmung.
    assert source.index("eod-flatten-missing-or-degraded") > source.index("push_to_data_branch")


def test_reconcile_e5_guard_measures_reconcile_outputs_not_the_flatten() -> None:
    """Minor #11: die (auch leere) EOD-Flatten-Datei darf den 'keine Fills
    trotz Audit'-Zweig nicht satt machen — der misst die beiden
    reconcile_incubation_fills-Ausgaben."""
    source = (REPO / "automation" / "launchd" / "run-c13-reconcile.sh").read_text(
        encoding="utf-8"
    )
    assert "_reconcile_fills_present=0" in source
    assert '{ FILLS_ARGS+=(--fills "${PORTFOLIO_FILLS}"); _reconcile_fills_present=1; }' in source
    assert '{ FILLS_ARGS+=(--fills "${COMMERCIAL_FILLS}"); _reconcile_fills_present=1; }' in source
    assert '[[ "${_reconcile_fills_present}" -eq 0 ]]' in source


# --- Settle-Recheck (Review Minor #9) ---------------------------------------


def test_flat_verdict_waits_out_a_lagging_position_event() -> None:
    """Position-Events koennen dem Terminal-Orderstatus nachlaufen: der erste
    Rest-Read nach dem Close-Loop liefert noch die stale Position, erst nach
    dem Absetzen die Wahrheit. Ohne Recheck: falsches DEGRADED."""

    class LaggingFakeIB(FakeIB):
        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)
            self._stale_final_reads = 1

        def positions(self, account=""):
            real = super().positions(account)
            if not real and self.placed and self._stale_final_reads > 0:
                self._stale_final_reads -= 1
                return [
                    SimpleNamespace(
                        contract=SimpleNamespace(symbol="NVDA"),
                        position=9.0,
                        account="DUP862066",
                    )
                ]
            return real

    ib = LaggingFakeIB(positions={"NVDA": 9.0})
    report = flatten_paper_account(ib, account="DUP862066", trade_date="2026-08-18")
    assert report["fills"] and report["fills"][0]["symbol"] == "NVDA"
    assert report["flat"] is True, (
        "the settle recheck must re-read positions after the lag settles "
        f"instead of declaring a phantom leftover: {report}"
    )
