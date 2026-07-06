"""Tests for scripts/build_evidence_freshness_snapshot.py (pure functions)."""
from __future__ import annotations

from scripts.build_evidence_freshness_snapshot import (
    FILLS_TARGET,
    build_snapshot,
    summarize_fills,
    summarize_ledger,
)

# --------------------------------------------------------------------------- #
# summarize_ledger
# --------------------------------------------------------------------------- #


def test_summarize_ledger_empty():
    out = summarize_ledger([])
    assert out == {"newest_date": "", "plane": "", "rows": 0, "candidate_pass": 0}


def test_summarize_ledger_picks_newest_date_and_plane():
    rows = [
        {"date": "2026-07-05", "family": "BOS", "status": "PASS", "plane": "1D"},
        {"date": "2026-07-06", "family": "BOS", "status": "PASS", "plane": "1D"},
        {"date": "2026-07-06", "family": "SWEEP", "status": "PASS", "plane": "1D"},
        {"date": "2026-07-06", "family": "FVG", "status": "FAIL", "plane": "1D"},
    ]
    out = summarize_ledger(rows)
    assert out["newest_date"] == "2026-07-06"
    assert out["plane"] == "1D"
    assert out["rows"] == 4
    # Only candidate families (BOS/SWEEP) that PASS on the newest date count.
    assert out["candidate_pass"] == 2


def test_summarize_ledger_legacy_seed_rows_default_to_15m():
    rows = [{"date": "2026-06-11", "family": "BOS", "status": "PASS"}]
    assert summarize_ledger(rows)["plane"] == "15m"


def test_summarize_ledger_ignores_control_family_pass():
    rows = [
        {"date": "2026-07-06", "family": "FVG", "status": "PASS", "plane": "1D"},
        {"date": "2026-07-06", "family": "OB", "passes": True, "plane": "1D"},
    ]
    assert summarize_ledger(rows)["candidate_pass"] == 0


def test_summarize_ledger_malformed_dates_skipped():
    rows = [
        {"date": "not-a-date", "family": "BOS", "status": "PASS"},
        {"date": "2026-07-06", "family": "BOS", "status": "PASS", "plane": "1D"},
    ]
    assert summarize_ledger(rows)["newest_date"] == "2026-07-06"


# --------------------------------------------------------------------------- #
# summarize_fills
# --------------------------------------------------------------------------- #


def test_summarize_fills_counts_filled_and_closed():
    records = [
        {"action": "paper_submitted", "fill_price": None},  # neither
        {"action": "filled", "fill_price": 100.0},  # filled, not closed
        {"action": "tp_hit", "fill_price": 101.0, "close_price": 110.0},  # both
        {"action": "stop_hit", "fill_price": 99.0, "close_price": 95.0},  # both
        {"action": "audit_only", "fill_price": None},  # neither
    ]
    out = summarize_fills(records)
    assert out == {"filled_cumulative": 3, "closed_cumulative": 2}


def test_summarize_fills_rejects_zero_and_bool_fill_price():
    records = [
        {"action": "filled", "fill_price": 0.0},
        {"action": "filled", "fill_price": True},  # bool must not count as a price
        {"action": "filled", "fill_price": -5.0},
    ]
    assert summarize_fills(records)["filled_cumulative"] == 0


def test_summarize_fills_empty():
    assert summarize_fills([]) == {"filled_cumulative": 0, "closed_cumulative": 0}


# --------------------------------------------------------------------------- #
# build_snapshot
# --------------------------------------------------------------------------- #


def test_build_snapshot_shape():
    snap = build_snapshot(
        ledger_rows=[{"date": "2026-06-11", "family": "BOS", "status": "PASS"}],
        incubation_records=[{"action": "tp_hit", "fill_price": 100.0}],
        audit_commit_date="2026-06-12",
        newest_incubation_date="2026-07-06",
        wsh_date="2026-06-23",
        wsh_status="degraded:no-events",
        generated_at_unix=1_751_800_000.0,
    )
    assert snap["generated_at_unix"] == 1_751_800_000.0
    assert snap["ledger"]["newest_date"] == "2026-06-11"
    assert snap["ledger"]["plane"] == "15m"
    assert snap["audit_branch"]["last_commit_date"] == "2026-06-12"
    assert snap["fills"]["closed_cumulative"] == 1
    assert snap["fills"]["target"] == FILLS_TARGET
    assert snap["fills"]["newest_incubation_date"] == "2026-07-06"
    assert snap["wsh"] == {"newest_date": "2026-06-23", "status": "degraded:no-events"}
