"""Tests for scripts/build_evidence_freshness_snapshot.py (pure functions)."""

from __future__ import annotations

from scripts.build_evidence_freshness_snapshot import (
    FILLS_TARGET,
    SAMPLES_TARGET,
    build_snapshot,
    summarize_fills,
    summarize_ledger,
)

# --------------------------------------------------------------------------- #
# per-family usable samples (the real §2/§5 progress, 2026-07-06)
# --------------------------------------------------------------------------- #


def test_samples_target_is_40_per_family():
    # §5 reads FamilyEvent records; MIN_TRADES = MIN_OOS_SAMPLES = 40 / family.
    assert SAMPLES_TARGET == 40


def test_summarize_ledger_extracts_per_family_usable_samples():
    rows = [
        {"date": "2026-07-08", "family": "BOS", "n_oos": 16, "plane": "1D"},
        {"date": "2026-07-08", "family": "SWEEP", "n_oos": 9, "plane": "1D"},
        {"date": "2026-07-07", "family": "BOS", "n_oos": 3, "plane": "1D"},  # older, ignored
    ]
    out = summarize_ledger(rows)
    assert out["usable_samples"] == {"BOS": 16, "SWEEP": 9}


def test_build_snapshot_samples_section_tags_classification():
    rows = [
        {"date": "2026-07-08", "family": "BOS", "n_oos": 16, "plane": "1D"},
        {"date": "2026-07-08", "family": "SWEEP", "n_oos": 9, "plane": "1D"},
        {"date": "2026-07-08", "family": "FVG", "n_oos": 10, "plane": "1D"},
        {"date": "2026-07-08", "family": "OB", "n_oos": 4, "plane": "1D"},
    ]
    snap = build_snapshot(
        ledger_rows=rows,
        incubation_records=[],
        audit_commit_date="2026-07-08",
        newest_incubation_date="2026-07-08",
        wsh_date="",
        wsh_status="",
        generated_at_unix=1_783_000_000.0,
    )
    s = snap["samples"]
    assert s["target"] == 40
    assert s["per_family"]["BOS"] == {"usable": 16, "classification": "operational"}
    assert s["per_family"]["SWEEP"] == {"usable": 9, "classification": "proof_of_concept_15m"}
    assert s["per_family"]["FVG"]["classification"] == "control"
    # All four families always present (missing → 0), so the panel never has a gap.
    assert set(s["per_family"]) == {"BOS", "SWEEP", "FVG", "OB"}


def test_build_snapshot_samples_missing_family_defaults_to_zero():
    rows = [{"date": "2026-07-08", "family": "BOS", "n_oos": 5, "plane": "1D"}]
    snap = build_snapshot(
        ledger_rows=rows,
        incubation_records=[],
        audit_commit_date="",
        newest_incubation_date="",
        wsh_date="",
        wsh_status="",
        generated_at_unix=1_783_000_000.0,
    )
    assert snap["samples"]["per_family"]["SWEEP"]["usable"] == 0


def test_build_snapshot_samples_clamped_to_target():
    """On a MEASURED row n_oos is the OOS fold size (hundreds/thousands), not
    the accumulation count. Clamp to 40 so the gauge reads '40/40 = at the
    bar' instead of a confusing '2370/40' (post-review finding)."""
    rows = [{"date": "2026-07-08", "family": "BOS", "n_oos": 2370, "plane": "1D", "status": "PASS"}]
    snap = build_snapshot(
        ledger_rows=rows,
        incubation_records=[],
        audit_commit_date="",
        newest_incubation_date="",
        wsh_date="",
        wsh_status="",
        generated_at_unix=1_783_000_000.0,
    )
    assert snap["samples"]["per_family"]["BOS"]["usable"] == SAMPLES_TARGET == 40


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
    assert out == {
        "filled_cumulative": 3,
        "closed_cumulative": 2,
        "submit_failed_cumulative": 0,
    }


def test_summarize_fills_counts_submit_failed():
    # A placed-but-dead bracket (every leg cancelled/rejected) records
    # submit_failed — the specific "submits are dying" signal (2026-07-08).
    records = [
        {"action": "submit_failed", "fill_price": None},
        {"action": "submit_failed", "fill_price": None},
        {"action": "paper_submitted", "fill_price": None},
        {"action": "tp_hit", "fill_price": 101.0, "close_price": 110.0},
    ]
    out = summarize_fills(records)
    assert out["submit_failed_cumulative"] == 2
    assert out["filled_cumulative"] == 1
    assert out["closed_cumulative"] == 1


def test_summarize_fills_rejects_zero_and_bool_fill_price():
    records = [
        {"action": "filled", "fill_price": 0.0},
        {"action": "filled", "fill_price": True},  # bool must not count as a price
        {"action": "filled", "fill_price": -5.0},
    ]
    assert summarize_fills(records)["filled_cumulative"] == 0


def test_summarize_fills_empty():
    assert summarize_fills([]) == {
        "filled_cumulative": 0,
        "closed_cumulative": 0,
        "submit_failed_cumulative": 0,
    }


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
    assert snap["fills"]["submit_failed_cumulative"] == 0
    assert snap["fills"]["target"] == FILLS_TARGET
    assert snap["fills"]["newest_incubation_date"] == "2026-07-06"
    assert snap["wsh"] == {"newest_date": "2026-06-23", "status": "degraded:no-events"}
    # No behind-commits reading passed -> known=0 so the stale-checkout alert
    # stays silent rather than falsely green.
    assert snap["submitter"] == {"submit_code_behind_commits": 0, "known": 0}


def test_build_snapshot_includes_portfolio_shadow_integrity_and_reconciliation() -> None:
    ts = "2026-08-08T13:28:00+00:00"
    incubation = [
        {
            "ts": ts,
            "phase": "paper",
            "action": "portfolio_risk_evaluated",
            "portfolio_risk": {
                "verdict": "allow",
                "reasons": [],
                "snapshot_age_seconds": 3.5,
                "max_snapshot_age_seconds": 120.0,
                "projection": {
                    "candidate_gross_pct": 5.0,
                    "projected_gross_pct": 15.0,
                    "correlation_coverage_pct": 100.0,
                },
            },
        },
        {"ts": ts, "phase": "paper", "action": "paper_submitted"},
    ]
    reconciliations = [
        {
            "after_captured_at": "2026-08-08T21:05:00+00:00",
            "max_abs_quantity_delta": 0.0,
            "reconciled": True,
        }
    ]

    snap = build_snapshot(
        ledger_rows=[],
        incubation_records=incubation,
        audit_commit_date="2026-08-08",
        newest_incubation_date="2026-08-08",
        wsh_date="",
        wsh_status="",
        generated_at_unix=1_783_000_000.0,
        portfolio_reconciliations=reconciliations,
    )

    portfolio = snap["portfolio_shadow"]
    assert portfolio["risk_relevant_sessions_observed"] == 1
    assert portfolio["risk_relevant_sessions_missing_reconciliation"] == 0
    assert portfolio["submission_attempts_without_prior_evaluation"] == 0
    assert portfolio["newest_risk_relevant_session"] == "2026-08-08"
    assert portfolio["verdict_counts"] == {"allow": 1}
    assert portfolio["latest_snapshot_age_seconds"] == 3.5
    assert portfolio["latest_snapshot_max_age_seconds"] == 120.0
    assert portfolio["latest_reconciliation_max_abs_quantity_delta"] == 0.0
    assert portfolio["latest_reconciliation_reconciled"] is True


def test_build_snapshot_submitter_behind_commits():
    # A published reading surfaces as known=1 with the count carried through.
    snap = build_snapshot(
        ledger_rows=[],
        incubation_records=[],
        audit_commit_date="2026-07-08",
        newest_incubation_date="2026-07-08",
        wsh_date="",
        wsh_status="",
        generated_at_unix=1_751_800_000.0,
        submit_code_behind_commits=3,
    )
    assert snap["submitter"] == {"submit_code_behind_commits": 3, "known": 1}
    # Zero-but-known (Mac fully deployed) must still read as known so the alert
    # can evaluate — distinct from "never published".
    snap_zero = build_snapshot(
        ledger_rows=[],
        incubation_records=[],
        audit_commit_date="2026-07-08",
        newest_incubation_date="2026-07-08",
        wsh_date="",
        wsh_status="",
        generated_at_unix=1_751_800_000.0,
        submit_code_behind_commits=0,
    )
    assert snap_zero["submitter"] == {"submit_code_behind_commits": 0, "known": 1}


def test_audit_branch_freshness_ignores_commercial_campaign_commits(
    tmp_path, monkeypatch
):
    """A campaign-report commit (Databento-only producer) must NOT refresh the
    TWS-chain freeze signal — an unscoped `git log -1` re-armed the invisible
    2026-06-12 freeze once the commercial-shadow driver started committing up
    to 6x/day (Grenzgänger-Sweep B1, 2026-08-18)."""
    import subprocess as sp

    from scripts.build_evidence_freshness_snapshot import (
        _audit_branch_last_commit_date,
    )

    repo = tmp_path / "repo"
    repo.mkdir()

    def _run(*args, date=None):
        env = {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t.invalid",
            "PATH": "/usr/bin:/bin",
        }
        if date is not None:
            env["GIT_AUTHOR_DATE"] = f"{date}T12:00:00Z"
            env["GIT_COMMITTER_DATE"] = f"{date}T12:00:00Z"
        sp.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True)

    _run("init", "-q", "-b", "audit")
    incubation = repo / "cache" / "live" / "incubation_2026-08-14.jsonl"
    incubation.parent.mkdir(parents=True)
    incubation.write_text("{}\n", encoding="utf-8")
    _run("add", "-A")
    _run("commit", "-q", "-m", "chore(c13): phase-a audit", date="2026-08-14")

    report = repo / "cache" / "live" / "commercial_campaign" / "campaign_report.json"
    report.parent.mkdir(parents=True)
    report.write_text("{}\n", encoding="utf-8")
    _run("add", "-A")
    _run("commit", "-q", "-m", "chore(c13): commercial shadow", date="2026-08-18")

    monkeypatch.chdir(repo)
    # The newest COMMIT is the campaign report (2026-08-18); the freshness
    # signal must still report the TWS-session artifact date.
    assert _audit_branch_last_commit_date("audit") == "2026-08-14"

    fills = repo / "cache" / "live" / "reconciled_fills_2026-08-19.json"
    fills.write_text("{}\n", encoding="utf-8")
    _run("add", "-A")
    _run("commit", "-q", "-m", "chore(c13): reconciled fills", date="2026-08-19")
    assert _audit_branch_last_commit_date("audit") == "2026-08-19"
