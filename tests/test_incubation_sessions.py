"""The incubation ledger must become §5-shaped sessions without inventing data.

``governance.execution_costs`` measures realized cost from the audit JSON that
``scripts/run_ibkr_open_execution.py --supervisor-json`` writes — and **no such
file has ever been written**: no job calls that script. The C8 paper track
record lives in ``cache/live/incubation_*.jsonl`` instead, written at submit
time and rewritten in place by the daily reconciler.

This adapter is the bridge, and every rule below exists because the honest
answer differs from the convenient one:

* a day with no ``reconciled_at`` anywhere is NOT provably unreconciled — the
  reconciler stamps only records whose entry filled — so dropping such days
  would remove misses only and inflate the fill rate; that is an explicit
  operator choice, never a default;
* ``submit_failed`` never reached the market at all;
* a stop exit has no limit reference, so it is a fee-only leg, while a
  take-profit exit carries one and is measured;
* an action the adapter was not taught is refused, never silently dropped;
* the direction is derived from the bracket and **refused** when the bracket
  does not describe a long, rather than assumed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from governance.execution_costs import extract_leg_costs
from governance.incubation_sessions import (
    IncubationConversionError,
    build_sessions,
    load_incubation_rows,
)


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "action": "filled",
        "entry_price": 200.0,
        "fill_price": 199.0,
        "filled_shares": 1.0,
        "intent_id": "smc-NVDA-2026-07-13-port7497",
        "phase": "paper",
        "quantity": 1,
        "reconciled_at": "2026-07-13T21:05:05+00:00",
        "size_scale": 0.1,
        "stop_loss": 190.0,
        "symbol": "NVDA",
        "take_profit": 220.0,
        "ts": "2026-07-13T13:28:06+00:00",
        "variant": "smc_orb_vwap_hold",
    }
    row.update(overrides)
    return row


def _write(tmp_path: Path, name: str, rows: list[dict[str, object]]) -> Path:
    path = tmp_path / name
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )
    return path


def test_a_filled_entry_carries_its_limit_and_its_fill(tmp_path: Path) -> None:
    path = _write(tmp_path, "incubation_2026-07-13.jsonl", [_row()])

    sessions, report = build_sessions(load_incubation_rows([path]))

    (session,) = sessions
    legs, n_entry_orders, n_entry_filled = extract_leg_costs([session])
    (leg,) = legs
    assert leg.symbol == "NVDA"
    assert leg.side == "BOT"
    assert leg.limit_price == 200.0
    assert leg.fill_vwap == 199.0
    assert leg.slippage_bps == pytest.approx(-50.0)  # filled below the limit
    assert (n_entry_orders, n_entry_filled) == (1, 1)
    assert report.sessions_used == 1


def test_an_unfilled_submission_on_a_reconciled_day_is_a_missed_entry(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path,
        "incubation_2026-07-14.jsonl",
        [
            _row(intent_id="smc-NVDA-2026-07-14-port7497"),
            _row(
                action="paper_submitted",
                intent_id="smc-AMD-2026-07-14-port7497",
                symbol="AMD",
                fill_price=None,
                filled_shares=None,
                reconciled_at=None,
            ),
        ],
    )

    sessions, _report = build_sessions(load_incubation_rows([path]))

    _legs, n_entry_orders, n_entry_filled = extract_leg_costs(sessions)
    assert (n_entry_orders, n_entry_filled) == (2, 1)


def test_a_failed_submission_never_becomes_an_order(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "incubation_2026-07-16.jsonl",
        [
            _row(intent_id="smc-NVDA-2026-07-16-port7497"),
            _row(
                action="submit_failed",
                intent_id="smc-AMD-2026-07-16-port7497",
                symbol="AMD",
                fill_price=None,
                filled_shares=None,
                reconciled_at=None,
            ),
            _row(
                action="audit_only",
                intent_id="smc-META-2026-07-16-port7497",
                symbol="META",
                fill_price=None,
                filled_shares=None,
                reconciled_at=None,
            ),
        ],
    )

    sessions, report = build_sessions(load_incubation_rows([path]))

    _legs, n_entry_orders, _filled = extract_leg_costs(sessions)
    assert n_entry_orders == 1
    assert report.rows_skipped_never_submitted == 2


def test_a_portfolio_risk_decision_row_is_evidence_not_an_order(tmp_path: Path) -> None:
    """The shadow risk gate's audit row must convert, not crash the adapter.

    ``run_smc_live_incubation`` writes one ``portfolio_risk_evaluated`` row per
    evaluated session — a statement about the whole book with no ``intent_id``
    and no bracket (top-level shape as in the live ledger; ``portfolio_risk``
    abbreviated). Until 2026-08-21 the adapter refused it as unknown, which
    turned every ``promotion-gate-daily`` run red from the first live
    evaluation onwards.
    """
    risk_row: dict[str, object] = {
        "ts": "2026-08-12T13:28:08.376721+00:00",
        "phase": "paper",
        "evidence_class": "PAPER",
        "action": "portfolio_risk_evaluated",
        "kill_switch_triggered": False,
        "portfolio_risk": {"verdict": "reject", "enforced": False},
    }
    path = _write(
        tmp_path,
        "incubation_2026-08-12.jsonl",
        [
            _row(
                intent_id="smc-NVDA-2026-08-12-port7497",
                ts="2026-08-12T13:28:06+00:00",
                reconciled_at="2026-08-12T21:05:05+00:00",
            ),
            risk_row,
        ],
    )

    sessions, report = build_sessions(load_incubation_rows([path]))

    _legs, n_entry_orders, _filled = extract_leg_costs(sessions)
    assert n_entry_orders == 1, "the risk row must not become an order"
    assert report.rows_skipped_never_submitted == 1


def test_a_stop_exit_adds_a_fee_only_leg_on_the_sell_side(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "incubation_2026-07-23.jsonl",
        [
            _row(
                action="stop_hit",
                intent_id="smc-AMZN-2026-07-23-port7497",
                symbol="AMZN",
                entry_price=244.85,
                fill_price=236.43,
                stop_loss=234.21,
                take_profit=266.13,
                close_price=234.2,
            )
        ],
    )

    sessions, _report = build_sessions(load_incubation_rows([path]))

    legs, _orders, _filled = extract_leg_costs(sessions)
    entry = next(leg for leg in legs if leg.order_ref.endswith("-entry"))
    exit_leg = next(leg for leg in legs if not leg.order_ref.endswith("-entry"))
    assert entry.side == "BOT"
    assert exit_leg.side == "SLD"
    assert exit_leg.fill_vwap == 234.2
    assert exit_leg.limit_price is None, "a stop exit has no limit reference"
    assert exit_leg.slippage_bps is None
    assert exit_leg.fee_bps > 0


def test_a_bracket_that_is_not_a_long_is_refused_rather_than_guessed(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path,
        "incubation_2026-07-13.jsonl",
        [_row(stop_loss=220.0, take_profit=190.0)],
    )

    with pytest.raises(IncubationConversionError, match="direction"):
        build_sessions(load_incubation_rows([path]))


def test_a_filled_row_without_a_fill_price_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, "incubation_2026-07-13.jsonl", [_row(fill_price=None)])

    with pytest.raises(IncubationConversionError, match="fill_price"):
        build_sessions(load_incubation_rows([path]))


def test_shares_come_from_the_reconciled_fill_not_the_intended_quantity(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, "incubation_2026-07-13.jsonl", [_row(quantity=5, filled_shares=2.0)])

    sessions, _report = build_sessions(load_incubation_rows([path]))

    legs, _orders, _filled = extract_leg_costs(sessions)
    assert legs[0].shares == 2.0


def test_one_session_per_trading_day(tmp_path: Path) -> None:
    first = _write(tmp_path, "incubation_2026-07-13.jsonl", [_row()])
    second = _write(
        tmp_path,
        "incubation_2026-07-14.jsonl",
        [_row(intent_id="smc-NVDA-2026-07-14-port7497", ts="2026-07-14T13:28:06+00:00")],
    )

    sessions, report = build_sessions(load_incubation_rows([first, second]))

    assert len(sessions) == 2
    assert report.sessions_used == 2
    assert [s["session_date"] for s in sessions] == ["2026-07-13", "2026-07-14"]


def test_every_order_ref_is_unique_across_a_session(tmp_path: Path) -> None:
    """Refs key the fill grouping; a collision would merge two trades' costs."""
    path = _write(
        tmp_path,
        "incubation_2026-07-13.jsonl",
        [
            _row(intent_id="smc-NVDA-2026-07-13-port7497"),
            _row(intent_id="smc-AMD-2026-07-13-port7497", symbol="AMD"),
            _row(
                action="stop_hit",
                intent_id="smc-META-2026-07-13-port7497",
                symbol="META",
                close_price=195.0,
            ),
        ],
    )

    sessions, _report = build_sessions(load_incubation_rows([path]))

    refs = [
        order["order_ref"]
        for session in sessions
        for placement in session["submission"]["placements"]
        for order in placement["orders"]
    ]
    assert len(refs) == len(set(refs))


def test_a_take_profit_exit_is_a_limit_bearing_leg(tmp_path: Path) -> None:
    """`tp_hit` is what the reconciler writes when the winner closes.

    It was silently dropped by the first cut — matching neither the submitted
    nor the never-submitted vocabulary, so it vanished from the sessions AND
    from the exclusion report, taking the fill-rate numerator with it. It is
    also the only exit the estimator can measure slippage on (`-tp` is its one
    limit-bearing exit suffix).
    """
    path = _write(
        tmp_path,
        "incubation_2026-07-13.jsonl",
        [_row(action="tp_hit", close_price=219.0)],
    )

    sessions, report = build_sessions(load_incubation_rows([path]))

    legs, n_entry_orders, n_entry_filled = extract_leg_costs(sessions)
    exit_leg = next(leg for leg in legs if leg.order_ref.endswith("-tp"))
    assert (n_entry_orders, n_entry_filled) == (1, 1)
    assert exit_leg.side == "SLD"
    assert exit_leg.limit_price == 220.0  # the take_profit the order carried
    assert exit_leg.slippage_bps is not None
    assert report.exit_fills == 1


def test_an_action_it_does_not_know_is_refused_not_ignored(tmp_path: Path) -> None:
    """A vocabulary the adapter has not been taught must never vanish."""
    path = _write(tmp_path, "incubation_2026-07-13.jsonl", [_row(action="flattened")])

    with pytest.raises(IncubationConversionError, match="unknown action"):
        build_sessions(load_incubation_rows([path]))


def test_days_without_fill_evidence_count_as_misses_by_default(tmp_path: Path) -> None:
    """"No `reconciled_at`" does NOT mean "never reconciled".

    The reconciler stamps only records whose ENTRY filled, so a day it
    processed with zero fills is indistinguishable from a day it never saw.
    Skipping such days silently removes only misses and inflates the fill
    rate — the one bar the real data has to clear — so the default counts
    them, and dropping them is an explicit operator choice.
    """
    rows = [
        _row(
            action="paper_submitted",
            intent_id=f"smc-X{i}-2026-07-07-port7497",
            ts="2026-07-07T13:28:06+00:00",
            fill_price=None,
            filled_shares=None,
            reconciled_at=None,
        )
        for i in range(5)
    ]
    path = _write(tmp_path, "incubation_2026-07-07.jsonl", rows)

    sessions, report = build_sessions(load_incubation_rows([path]))

    _legs, n_entry_orders, n_entry_filled = extract_leg_costs(sessions)
    assert (n_entry_orders, n_entry_filled) == (5, 0)
    assert report.rows_without_fill_evidence == 5
    assert report.sessions_skipped_unreconciled == 0

    skipped_sessions, skipped_report = build_sessions(
        load_incubation_rows([path]), unreconciled_days="skip"
    )
    assert skipped_sessions == []
    assert skipped_report.sessions_skipped_unreconciled == 1


def test_the_report_counts_what_it_actually_emitted(tmp_path: Path) -> None:
    """The report is the published artefact; it must not drift from the data."""
    path = _write(
        tmp_path,
        "incubation_2026-07-13.jsonl",
        [
            _row(intent_id="smc-A-2026-07-13-port7497"),
            _row(action="tp_hit", intent_id="smc-B-2026-07-13-port7497", close_price=219.0),
            _row(
                action="paper_submitted",
                intent_id="smc-C-2026-07-13-port7497",
                fill_price=None,
                filled_shares=None,
                reconciled_at=None,
            ),
            _row(action="submit_failed", intent_id="smc-D-2026-07-13-port7497"),
        ],
    )

    _sessions, report = build_sessions(load_incubation_rows([path]))

    assert report.entry_orders == 3
    assert report.entry_fills == 2
    assert report.exit_fills == 1
    assert report.rows_used == 3
    assert report.rows_skipped_never_submitted == 1


def test_a_fill_discloses_which_timestamp_it_carries(tmp_path: Path) -> None:
    path = _write(tmp_path, "incubation_2026-07-13.jsonl", [_row()])

    sessions, _report = build_sessions(load_incubation_rows([path]))

    (fill,) = sessions[0]["supervisor"]["final"]["fills"]
    assert fill["time"] == "2026-07-13T21:05:05+00:00"
    assert fill["time_source"] == "reconciled_at"


def test_a_ts_that_is_not_a_date_is_refused(tmp_path: Path) -> None:
    """The session date becomes a filename; it never leaves its directory."""
    path = _write(tmp_path, "incubation_bad.jsonl", [_row(ts="../../../etc/passwd")])

    with pytest.raises(IncubationConversionError, match="session date"):
        build_sessions(load_incubation_rows([path]))
