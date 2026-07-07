"""Tests for scripts/reconcile_incubation_fills.py (C13 reconcile-fills stage)."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts.reconcile_incubation_fills import (
    legs_by_intent,
    main,
    reconcile_records,
    summarize_fills,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fill(order_ref: str, shares: float, price: float) -> SimpleNamespace:
    return SimpleNamespace(
        execution=SimpleNamespace(orderRef=order_ref, shares=shares, price=price)
    )


def _record(intent_id: str, action: str = "paper_submitted", **extra) -> dict:
    rec = {
        "intent_id": intent_id,
        "action": action,
        "entry_price": 100.0,
        "fill_price": None,
        "stop_loss": 95.0,
        "take_profit": 110.0,
        "quantity": 2,
        "symbol": "TEST",
    }
    rec.update(extra)
    return rec


# ---------------------------------------------------------------------------
# summarize_fills
# ---------------------------------------------------------------------------


def test_summarize_fills_weighted_average_over_partials():
    fills = [
        _fill("smc-A-entry", 1, 100.0),
        _fill("smc-A-entry", 3, 104.0),
    ]
    out = summarize_fills(fills)
    assert out["smc-A-entry"]["shares"] == 4
    assert out["smc-A-entry"]["avg_price"] == 103.0


def test_summarize_fills_skips_unusable_executions():
    fills = [
        _fill("", 1, 100.0),  # no orderRef
        _fill("smc-A-entry", 0, 100.0),  # zero shares
        _fill("smc-A-entry", 1, 0.0),  # zero price
        SimpleNamespace(execution=None),  # no execution at all
    ]
    assert summarize_fills(fills) == {}


def test_summarize_fills_rejects_non_finite_inputs():
    # NaN/inf pass the ``<= 0`` guard (all NaN comparisons are False) and would
    # otherwise produce a NaN avg_price that gets written as non-standard JSON
    # ``NaN`` and crashes the downstream backfill. Drop them like any unusable
    # fill so the record stays honestly unfilled.
    assert summarize_fills([_fill("smc-A-entry", 2, float("nan"))]) == {}
    assert summarize_fills([_fill("smc-A-entry", float("inf"), 100.0)]) == {}
    assert summarize_fills([_fill("smc-A-entry", 2, float("-inf"))]) == {}
    # A good fill alongside a corrupt one still summarizes; the bad one drops.
    out = summarize_fills(
        [_fill("smc-A-entry", 2, float("nan")), _fill("smc-A-entry", 2, 100.0)]
    )
    assert out == {"smc-A-entry": {"shares": 2.0, "avg_price": 100.0}}


def test_summarize_fills_rejects_overflowing_notional():
    # shares and price are each finite but their product overflows to inf
    # (1e308 * 1e308), which would poison avg_price and write non-standard JSON
    # ``Infinity`` — the same failure class the finite guards above prevent.
    assert summarize_fills([_fill("smc-A-entry", 1e308, 1e308)]) == {}
    # A finite-product fill for the same ref still summarizes; the overflow drops.
    out = summarize_fills(
        [_fill("smc-A-entry", 1e308, 1e308), _fill("smc-A-entry", 2, 100.0)]
    )
    assert out == {"smc-A-entry": {"shares": 2.0, "avg_price": 100.0}}


# ---------------------------------------------------------------------------
# legs_by_intent
# ---------------------------------------------------------------------------


def test_legs_by_intent_groups_bracket_suffixes():
    by_ref = {
        "smc-NVDA-2026-07-06-port7497-entry": {"shares": 1.0, "avg_price": 194.9},
        "smc-NVDA-2026-07-06-port7497-tp": {"shares": 1.0, "avg_price": 216.2},
        "smc-PLTR-2026-07-06-port7497-entry": {"shares": 1.0, "avg_price": 129.4},
    }
    legs = legs_by_intent(by_ref)
    assert set(legs["smc-NVDA-2026-07-06-port7497"]) == {"entry", "tp"}
    assert set(legs["smc-PLTR-2026-07-06-port7497"]) == {"entry"}


def test_legs_by_intent_ignores_foreign_refs():
    legs = legs_by_intent(
        {
            "unrelated-manual-order": {"shares": 1.0, "avg_price": 5.0},
            "smc-A-2026-07-06-flatten": {"shares": 1.0, "avg_price": 5.0},
        }
    )
    assert legs == {}


# ---------------------------------------------------------------------------
# reconcile_records
# ---------------------------------------------------------------------------


def test_entry_fill_stamps_filled_with_size_usd():
    records = [_record("smc-A")]
    legs = {"smc-A": {"entry": {"shares": 2.0, "avg_price": 101.5}}}
    out, counts = reconcile_records(records, legs)
    rec = out[0]
    assert rec["action"] == "filled"
    assert rec["fill_price"] == 101.5
    assert rec["size_usd"] == 203.0  # avg_price * quantity(2)
    assert counts == {"reconcilable": 1, "entry_filled": 1, "closed": 0, "duplicate_skipped": 0}


def test_tp_exit_closes_as_tp_hit():
    records = [_record("smc-A")]
    legs = {
        "smc-A": {
            "entry": {"shares": 2.0, "avg_price": 100.0},
            "tp": {"shares": 2.0, "avg_price": 110.2},
        }
    }
    out, counts = reconcile_records(records, legs)
    assert out[0]["action"] == "tp_hit"
    assert out[0]["close_price"] == 110.2
    assert counts["closed"] == 1


def test_sl_and_trail_exits_close_as_stop_hit():
    for exit_leg in ("sl", "trail"):
        records = [_record("smc-A")]
        legs = {
            "smc-A": {
                "entry": {"shares": 2.0, "avg_price": 100.0},
                exit_leg: {"shares": 2.0, "avg_price": 94.8},
            }
        }
        out, _ = reconcile_records(records, legs)
        assert out[0]["action"] == "stop_hit", exit_leg
        assert out[0]["close_price"] == 94.8


def test_audit_only_and_closed_records_never_touched():
    records = [
        _record("smc-A", action="audit_only"),
        _record("smc-B", action="tp_hit", close_price=110.0),
        _record("smc-C", action="submit_failed"),
    ]
    legs = {
        "smc-A": {"entry": {"shares": 2.0, "avg_price": 100.0}},
        "smc-B": {"entry": {"shares": 2.0, "avg_price": 100.0}},
        "smc-C": {"entry": {"shares": 2.0, "avg_price": 100.0}},
    }
    out, counts = reconcile_records(records, legs)
    assert [r["action"] for r in out] == ["audit_only", "tp_hit", "submit_failed"]
    assert counts == {"reconcilable": 0, "entry_filled": 0, "closed": 0, "duplicate_skipped": 0}


def test_filled_record_upgrades_to_closed_on_rerun():
    """Idempotent re-run: a record that only reached ``filled`` earlier
    upgrades once the exit leg has executions."""
    records = [_record("smc-A", action="filled", fill_price=100.0, size_usd=200.0)]
    legs = {
        "smc-A": {
            "entry": {"shares": 2.0, "avg_price": 100.0},
            "sl": {"shares": 2.0, "avg_price": 94.9},
        }
    }
    out, _ = reconcile_records(records, legs)
    assert out[0]["action"] == "stop_hit"


def test_exit_without_entry_left_for_inspection():
    records = [_record("smc-A")]
    legs = {"smc-A": {"tp": {"shares": 2.0, "avg_price": 110.0}}}
    out, counts = reconcile_records(records, legs)
    assert out[0]["action"] == "paper_submitted"
    assert counts["entry_filled"] == 0


def test_unfilled_intent_stays_paper_submitted():
    records = [_record("smc-A")]
    out, counts = reconcile_records(records, {})
    assert out[0]["action"] == "paper_submitted"
    assert out[0]["fill_price"] is None
    assert counts == {"reconcilable": 1, "entry_filled": 0, "closed": 0, "duplicate_skipped": 0}


# ---------------------------------------------------------------------------
# Duplicate intent_ids (same-day retry after a DEGRADED run)
# ---------------------------------------------------------------------------


def _dup_legs() -> dict:
    return legs_by_intent(
        summarize_fills(
            [_fill("smc-A-entry", 2, 101.0), _fill("smc-A-tp", 2, 110.0)]
        )
    )


def test_duplicate_intent_stamps_only_the_newest_record():
    """A same-day retry re-submits the SAME intent_ids; one IB fill must not
    be copied onto every duplicate (that would inflate the C8 fill/closed
    counts N-fold — root-caused 2026-07-07)."""
    records = [
        _record("smc-A", ts="2026-07-07T07:28:00+00:00"),   # phantom morning submit
        _record("smc-A", ts="2026-07-07T13:40:00+00:00"),   # retry that actually rests
    ]
    out, counts = reconcile_records(records, _dup_legs())
    assert out[0]["action"] == "paper_submitted"  # superseded: untouched
    assert out[0]["fill_price"] is None
    assert out[1]["action"] == "tp_hit"           # newest: stamped + closed
    assert out[1]["fill_price"] == 101.0
    assert counts["closed"] == 1
    assert counts["duplicate_skipped"] == 1


def test_duplicate_intent_rerun_is_idempotent_on_the_same_winner():
    # After run 1 the winner is closed (tp_hit); run 2 must keep skipping the
    # old duplicate instead of drifting the fills onto it.
    records = [
        _record("smc-A", ts="2026-07-07T07:28:00+00:00"),
        _record("smc-A", ts="2026-07-07T13:40:00+00:00"),
    ]
    legs = _dup_legs()
    out, _ = reconcile_records(records, legs)
    out, counts = reconcile_records(out, legs)
    assert out[0]["fill_price"] is None
    assert out[0]["action"] == "paper_submitted"
    assert out[1]["action"] == "tp_hit"
    assert counts["duplicate_skipped"] == 1


def test_duplicate_tie_on_ts_prefers_later_file_order():
    # Records are appended chronologically; identical ts -> the later row wins.
    records = [
        _record("smc-A", ts="2026-07-07T13:40:00+00:00"),
        _record("smc-A", ts="2026-07-07T13:40:00+00:00"),
    ]
    out, counts = reconcile_records(records, _dup_legs())
    assert out[0]["fill_price"] is None
    assert out[1]["fill_price"] == 101.0
    assert counts["duplicate_skipped"] == 1


def test_audit_only_record_never_steals_the_stamp():
    # A newer audit-only re-run (no --place-paper-orders) is not stampable and
    # must not shadow the real submission that owns the resting bracket.
    records = [
        _record("smc-A", ts="2026-07-07T07:28:00+00:00"),
        _record("smc-A", action="audit_only", ts="2026-07-07T13:40:00+00:00"),
    ]
    out, counts = reconcile_records(records, _dup_legs())
    assert out[0]["action"] == "tp_hit"      # real submission stamped
    assert out[1]["action"] == "audit_only"  # untouched
    assert counts["duplicate_skipped"] == 0


# ---------------------------------------------------------------------------
# CLI (paths that must not require an IBKR connection)
# ---------------------------------------------------------------------------


def test_cli_refuses_non_paper_port(tmp_path: Path, capsys):
    audit = tmp_path / "incubation.jsonl"
    audit.write_text(json.dumps(_record("smc-A")) + "\n")
    rc = main(["--audit", str(audit), "--port", "7496"])
    assert rc == 1
    assert "not a paper port" in capsys.readouterr().err


def test_cli_missing_audit_file_is_error(tmp_path: Path, capsys):
    rc = main(["--audit", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "not found" in capsys.readouterr().err


def test_cli_malformed_jsonl_fails_closed(tmp_path: Path, capsys):
    audit = tmp_path / "incubation.jsonl"
    audit.write_text('{"action": "paper_submitted"\nnot-json\n')
    rc = main(["--audit", str(audit)])
    assert rc == 1
    assert "malformed" in capsys.readouterr().err


def test_cli_audit_only_day_exits_zero_without_ibkr(tmp_path: Path, capsys):
    """A day with no submitted intents must succeed WITHOUT any IBKR
    connection (the deferred import must not even run)."""
    audit = tmp_path / "incubation.jsonl"
    audit.write_text(json.dumps(_record("smc-A", action="audit_only")) + "\n")
    rc = main(["--audit", str(audit)])
    assert rc == 0
    assert "nothing to reconcile" in capsys.readouterr().out
