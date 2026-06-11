"""Tests for scripts/evaluate_phase_criteria.py (stat-review F1/F6, 2026-06-10).

Covers:

* Structural completeness — every ``extra`` criterion string in any
  ``PHASE_*_CRITERIA`` must have a registered checker (F6: an unmapped
  string is a silent gate hole and therefore a test failure).
* Fail-closed semantics — ``passed=None`` (not machine-evaluable) must
  prevent ``all_passed``.
* Phase-C (``live_full``) must NEVER machine-pass: the Scale-Phase /
  Kelly marker is human-owned by design.
* Per-checker behaviour against synthetic drift/audit/watchdog inputs.
* The report-consumption gate used by ``run_smc_live_incubation``.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from scripts.evaluate_phase_criteria import (
    _EXTRA_CHECKERS,
    PHASE_EVAL_SCHEMA_VERSION,
    PRIOR_PHASE_FOR_ENTRY,
    evaluate_phase_criteria,
    load_and_validate_eval_report,
    main,
)
from scripts.run_smc_live_incubation import (
    PHASE_A_CRITERIA,
    PHASE_B_CRITERIA,
    PHASE_C_CRITERIA,
    PHASE_PASS_CRITERIA,
)

TODAY = date(2026, 6, 10)
PHASE_START_OK = TODAY - timedelta(days=120)


def _passing_phase_a_artifact(variant: str = "v1") -> dict:
    return {
        "variants": [
            {
                "variant": variant,
                "drift_score": 0.92,
                "verdict": "pass",
                "slippage_ks_p": 0.40,
                "slippage_ks_reference_type": "backtest_samples",
                "hr_in_bootstrap_ci": True,
                "live_max_dd": 0.05,
                "backtest_max_dd": 0.04,
            }
        ]
    }


def _closed_audit_records(n: int, *, variant: str = "v1", phase: str = "paper") -> list[dict]:
    return [
        {
            "variant": variant,
            "phase": phase,
            "action": "closed",
            "kill_switch_triggered": False,
        }
        for _ in range(n)
    ]


# ---------------------------------------------------------------------------
# F6 structural test — unmapped extra string == failure
# ---------------------------------------------------------------------------


def test_every_extra_criterion_has_a_registered_checker() -> None:
    for phase, criteria in PHASE_PASS_CRITERIA.items():
        for name in criteria.extra:
            assert name in _EXTRA_CHECKERS, (
                f"extra criterion {name!r} in PHASE_PASS_CRITERIA[{phase!r}] "
                "has no checker in _EXTRA_CHECKERS — silent gate hole "
                "(stat-review F6). Register a checker (passed=None is fine "
                "for human-owned criteria) in the same commit."
            )


def test_unmapped_extra_string_yields_unevaluable_not_pass() -> None:
    from dataclasses import replace

    criteria = replace(PHASE_A_CRITERIA, extra=("totally_unknown_criterion",))
    report = evaluate_phase_criteria(
        criteria,
        variant="v1",
        drift_artifact=_passing_phase_a_artifact(),
        audit_records=_closed_audit_records(25),
        phase_started=PHASE_START_OK,
        today=TODAY,
    )
    row = next(r for r in report.results if r.criterion == "totally_unknown_criterion")
    assert row.passed is None
    assert report.all_passed is False


# ---------------------------------------------------------------------------
# Fail-closed semantics
# ---------------------------------------------------------------------------


def test_phase_a_all_passing_inputs_pass() -> None:
    report = evaluate_phase_criteria(
        PHASE_A_CRITERIA,
        variant="v1",
        drift_artifact=_passing_phase_a_artifact(),
        audit_records=_closed_audit_records(25),
        phase_started=PHASE_START_OK,
        today=TODAY,
        # Stat-review S1 (#2674): Phase-A now requires the watchdog
        # severity — absent report fails closed.
        watchdog_report={"aggregate_severity": "green"},
    )
    failing = [r for r in report.results if r.passed is not True]
    assert report.all_passed is True, f"unexpected failures: {failing}"
    assert report.phase == "paper"


def test_missing_drift_artifact_fails_closed() -> None:
    report = evaluate_phase_criteria(
        PHASE_A_CRITERIA,
        variant="v1",
        drift_artifact=None,
        audit_records=_closed_audit_records(25),
        phase_started=PHASE_START_OK,
        today=TODAY,
    )
    assert report.all_passed is False
    by_name = {r.criterion: r for r in report.results}
    assert by_name["min_drift_score"].passed is None
    assert by_name["slippage_ks_pvalue_gt_0.05"].passed is None


def test_variant_absent_from_artifact_fails_closed() -> None:
    report = evaluate_phase_criteria(
        PHASE_A_CRITERIA,
        variant="other_variant",
        drift_artifact=_passing_phase_a_artifact("v1"),
        audit_records=_closed_audit_records(25, variant="other_variant"),
        phase_started=PHASE_START_OK,
        today=TODAY,
    )
    assert report.all_passed is False


def test_too_few_closed_trades_fails() -> None:
    report = evaluate_phase_criteria(
        PHASE_A_CRITERIA,
        variant="v1",
        drift_artifact=_passing_phase_a_artifact(),
        audit_records=_closed_audit_records(19),
        phase_started=PHASE_START_OK,
        today=TODAY,
    )
    by_name = {r.criterion: r for r in report.results}
    assert by_name["min_trades_closed"].passed is False
    assert report.all_passed is False


def test_open_or_other_phase_trades_do_not_count() -> None:
    records = (
        _closed_audit_records(10)  # countable
        + _closed_audit_records(10, phase="live_small")  # wrong phase
        + [
            {"variant": "v1", "phase": "paper", "action": "submitted"}
            for _ in range(10)
        ]  # not closed
    )
    report = evaluate_phase_criteria(
        PHASE_A_CRITERIA,
        variant="v1",
        drift_artifact=_passing_phase_a_artifact(),
        audit_records=records,
        phase_started=PHASE_START_OK,
        today=TODAY,
    )
    by_name = {r.criterion: r for r in report.results}
    assert by_name["min_trades_closed"].passed is False
    assert "trades_closed=10" in by_name["min_trades_closed"].detail


def test_min_phase_days_not_elapsed_fails() -> None:
    report = evaluate_phase_criteria(
        PHASE_A_CRITERIA,
        variant="v1",
        drift_artifact=_passing_phase_a_artifact(),
        audit_records=_closed_audit_records(25),
        phase_started=TODAY - timedelta(days=5),
        today=TODAY,
    )
    by_name = {r.criterion: r for r in report.results}
    assert by_name["min_phase_days"].passed is False


def test_drift_score_deviation_and_floor() -> None:
    artifact = _passing_phase_a_artifact()
    artifact["variants"][0]["drift_score"] = 0.60  # dev 0.40 > 0.30, < 0.70 floor
    report = evaluate_phase_criteria(
        PHASE_A_CRITERIA,
        variant="v1",
        drift_artifact=artifact,
        audit_records=_closed_audit_records(25),
        phase_started=PHASE_START_OK,
        today=TODAY,
    )
    by_name = {r.criterion: r for r in report.results}
    assert by_name["max_drift_score_deviation"].passed is False
    assert by_name["min_drift_score"].passed is False


def test_verdict_outside_allowlist_fails() -> None:
    artifact = _passing_phase_a_artifact()
    artifact["variants"][0]["verdict"] = "concerning"
    report = evaluate_phase_criteria(
        PHASE_A_CRITERIA,
        variant="v1",
        drift_artifact=artifact,
        audit_records=_closed_audit_records(25),
        phase_started=PHASE_START_OK,
        today=TODAY,
    )
    by_name = {r.criterion: r for r in report.results}
    assert by_name["require_drift_verdict_in"].passed is False


# ---------------------------------------------------------------------------
# Phase-B extra checkers
# ---------------------------------------------------------------------------


def _passing_phase_b_inputs() -> tuple[dict, list[dict], dict]:
    artifact = {
        "variants": [
            {
                "variant": "v1",
                "drift_score": 0.90,
                "verdict": "acceptable",
                "slippage_ks_p": 0.30,
                "slippage_ks_reference_type": "backtest_samples",
                "hr_in_bootstrap_ci": True,
                "live_max_dd": 0.05,
                "backtest_max_dd": 0.04,
            }
        ]
    }
    audit = _closed_audit_records(35, phase="live_small")
    # Stat-review S1 (#2674): aggregate_severity now feeds the
    # watchdog_status_not_red criterion.
    watchdog = {"window_complete": True, "aggregate_severity": "green"}
    return artifact, audit, watchdog


def test_phase_b_all_passing_inputs_pass() -> None:
    artifact, audit, watchdog = _passing_phase_b_inputs()
    report = evaluate_phase_criteria(
        PHASE_B_CRITERIA,
        variant="v1",
        drift_artifact=artifact,
        audit_records=audit,
        phase_started=PHASE_START_OK,
        today=TODAY,
        watchdog_report=watchdog,
    )
    failing = [r for r in report.results if r.passed is not True]
    assert report.all_passed is True, f"unexpected failures: {failing}"


def test_kill_switch_fired_in_phase_fails() -> None:
    artifact, audit, watchdog = _passing_phase_b_inputs()
    audit.append(
        {
            "variant": "v1",
            "phase": "live_small",
            "action": "halted",
            "kill_switch_triggered": True,
        }
    )
    report = evaluate_phase_criteria(
        PHASE_B_CRITERIA,
        variant="v1",
        drift_artifact=artifact,
        audit_records=audit,
        phase_started=PHASE_START_OK,
        today=TODAY,
        watchdog_report=watchdog,
    )
    by_name = {r.criterion: r for r in report.results}
    assert by_name["kill_switch_never_fired"].passed is False
    assert report.all_passed is False


def test_kill_switch_fired_in_other_phase_does_not_fail_b() -> None:
    artifact, audit, watchdog = _passing_phase_b_inputs()
    audit.append(
        {
            "variant": "v1",
            "phase": "paper",
            "action": "halted",
            "kill_switch_triggered": True,
        }
    )
    report = evaluate_phase_criteria(
        PHASE_B_CRITERIA,
        variant="v1",
        drift_artifact=artifact,
        audit_records=audit,
        phase_started=PHASE_START_OK,
        today=TODAY,
        watchdog_report=watchdog,
    )
    by_name = {r.criterion: r for r in report.results}
    assert by_name["kill_switch_never_fired"].passed is True


def test_max_dd_2x_violation_fails() -> None:
    artifact, audit, watchdog = _passing_phase_b_inputs()
    artifact["variants"][0]["live_max_dd"] = 0.09  # >= 2 * 0.04
    report = evaluate_phase_criteria(
        PHASE_B_CRITERIA,
        variant="v1",
        drift_artifact=artifact,
        audit_records=audit,
        phase_started=PHASE_START_OK,
        today=TODAY,
        watchdog_report=watchdog,
    )
    by_name = {r.criterion: r for r in report.results}
    assert by_name["max_dd_live_lt_2x_backtest"].passed is False


def test_zero_backtest_dd_is_degenerate_not_pass() -> None:
    artifact, audit, watchdog = _passing_phase_b_inputs()
    artifact["variants"][0]["backtest_max_dd"] = 0.0
    report = evaluate_phase_criteria(
        PHASE_B_CRITERIA,
        variant="v1",
        drift_artifact=artifact,
        audit_records=audit,
        phase_started=PHASE_START_OK,
        today=TODAY,
        watchdog_report=watchdog,
    )
    by_name = {r.criterion: r for r in report.results}
    assert by_name["max_dd_live_lt_2x_backtest"].passed is None
    assert report.all_passed is False


def test_synthetic_ks_reference_blocks_phase_b() -> None:
    artifact, audit, watchdog = _passing_phase_b_inputs()
    artifact["variants"][0]["slippage_ks_reference_type"] = "synthetic_normal"
    report = evaluate_phase_criteria(
        PHASE_B_CRITERIA,
        variant="v1",
        drift_artifact=artifact,
        audit_records=audit,
        phase_started=PHASE_START_OK,
        today=TODAY,
        watchdog_report=watchdog,
    )
    by_name = {r.criterion: r for r in report.results}
    assert by_name["slippage_ks_reference_backtest_samples"].passed is False


def test_missing_watchdog_report_fails_closed() -> None:
    artifact, audit, _ = _passing_phase_b_inputs()
    report = evaluate_phase_criteria(
        PHASE_B_CRITERIA,
        variant="v1",
        drift_artifact=artifact,
        audit_records=audit,
        phase_started=PHASE_START_OK,
        today=TODAY,
        watchdog_report=None,
    )
    by_name = {r.criterion: r for r in report.results}
    assert by_name["drift_window_complete"].passed is None
    assert report.all_passed is False


def test_incomplete_window_fails() -> None:
    artifact, audit, _ = _passing_phase_b_inputs()
    report = evaluate_phase_criteria(
        PHASE_B_CRITERIA,
        variant="v1",
        drift_artifact=artifact,
        audit_records=audit,
        phase_started=PHASE_START_OK,
        today=TODAY,
        watchdog_report={"window_complete": False},
    )
    by_name = {r.criterion: r for r in report.results}
    assert by_name["drift_window_complete"].passed is False


# ---------------------------------------------------------------------------
# Stat-review S1 (#2674) — watchdog aggregate severity gates promotion
# ---------------------------------------------------------------------------


def test_watchdog_red_blocks_promotion() -> None:
    artifact, audit, watchdog = _passing_phase_b_inputs()
    watchdog["aggregate_severity"] = "red"
    report = evaluate_phase_criteria(
        PHASE_B_CRITERIA,
        variant="v1",
        drift_artifact=artifact,
        audit_records=audit,
        phase_started=PHASE_START_OK,
        today=TODAY,
        watchdog_report=watchdog,
    )
    by_name = {r.criterion: r for r in report.results}
    assert by_name["watchdog_status_not_red"].passed is False
    assert report.all_passed is False


def test_watchdog_yellow_does_not_block() -> None:
    artifact, audit, watchdog = _passing_phase_b_inputs()
    watchdog["aggregate_severity"] = "yellow"
    report = evaluate_phase_criteria(
        PHASE_B_CRITERIA,
        variant="v1",
        drift_artifact=artifact,
        audit_records=audit,
        phase_started=PHASE_START_OK,
        today=TODAY,
        watchdog_report=watchdog,
    )
    by_name = {r.criterion: r for r in report.results}
    assert by_name["watchdog_status_not_red"].passed is True


def test_watchdog_severity_missing_fails_closed() -> None:
    artifact, audit, watchdog = _passing_phase_b_inputs()
    del watchdog["aggregate_severity"]
    report = evaluate_phase_criteria(
        PHASE_B_CRITERIA,
        variant="v1",
        drift_artifact=artifact,
        audit_records=audit,
        phase_started=PHASE_START_OK,
        today=TODAY,
        watchdog_report=watchdog,
    )
    by_name = {r.criterion: r for r in report.results}
    assert by_name["watchdog_status_not_red"].passed is None
    assert report.all_passed is False


def test_phase_a_missing_watchdog_report_fails_closed() -> None:
    report = evaluate_phase_criteria(
        PHASE_A_CRITERIA,
        variant="v1",
        drift_artifact=_passing_phase_a_artifact(),
        audit_records=_closed_audit_records(25),
        phase_started=PHASE_START_OK,
        today=TODAY,
        watchdog_report=None,
    )
    by_name = {r.criterion: r for r in report.results}
    assert by_name["watchdog_status_not_red"].passed is None
    assert report.all_passed is False


# ---------------------------------------------------------------------------
# Stat-review S5 (#2674) — synthetic KS reference is not machine-evaluable
# ---------------------------------------------------------------------------


def test_synthetic_ks_reference_makes_pvalue_criterion_unevaluable() -> None:
    artifact = _passing_phase_a_artifact()
    artifact["variants"][0]["slippage_ks_reference_type"] = "synthetic_normal"
    report = evaluate_phase_criteria(
        PHASE_A_CRITERIA,
        variant="v1",
        drift_artifact=artifact,
        audit_records=_closed_audit_records(25),
        phase_started=PHASE_START_OK,
        today=TODAY,
        watchdog_report={"aggregate_severity": "green"},
    )
    by_name = {r.criterion: r for r in report.results}
    row = by_name["slippage_ks_pvalue_gt_0.05"]
    assert row.passed is None
    assert "synthetic_normal" in row.detail
    assert report.all_passed is False


# ---------------------------------------------------------------------------
# Phase-C can never machine-pass
# ---------------------------------------------------------------------------


def test_phase_c_never_machine_passes_even_with_perfect_inputs() -> None:
    artifact, audit, watchdog = _passing_phase_b_inputs()
    audit = [dict(r, phase="live_full") for r in audit]
    report = evaluate_phase_criteria(
        PHASE_C_CRITERIA,
        variant="v1",
        drift_artifact=artifact,
        audit_records=audit,
        phase_started=PHASE_START_OK,
        today=TODAY,
        watchdog_report=watchdog,
    )
    assert report.all_passed is False
    by_name = {r.criterion: r for r in report.results}
    assert by_name["scale_phase_backlog_owns_kelly_sizing"].passed is None
    # The empty verdict allowlist is fail-closed too, not a free pass.
    assert by_name["require_drift_verdict_in"].passed is None


# ---------------------------------------------------------------------------
# Report consumption gate (run_smc_live_incubation wiring)
# ---------------------------------------------------------------------------


def _write_report(
    tmp_path: Path,
    *,
    phase: str = "paper",
    all_passed: bool = True,
    computed_at: str | None = None,
) -> Path:
    payload = {
        "schema_version": PHASE_EVAL_SCHEMA_VERSION,
        "phase": phase,
        "variant": "v1",
        "all_passed": all_passed,
        "computed_at": computed_at or datetime.now(UTC).isoformat(),
        "results": [
            {"criterion": "min_trades_closed", "passed": all_passed, "detail": "x"}
        ],
        "phase_promotion": "manual_signoff_only",
    }
    out = tmp_path / "phase_eval.json"
    out.write_text(json.dumps(payload), encoding="utf-8")
    return out


def test_load_and_validate_accepts_fresh_passing_paper_report(tmp_path: Path) -> None:
    path = _write_report(tmp_path, phase="paper", all_passed=True)
    payload = load_and_validate_eval_report(path, target_phase="live_small")
    assert payload["all_passed"] is True


def test_load_and_validate_rejects_failing_report(tmp_path: Path) -> None:
    path = _write_report(tmp_path, phase="paper", all_passed=False)
    with pytest.raises(SystemExit, match="all_passed"):
        load_and_validate_eval_report(path, target_phase="live_small")


def test_load_and_validate_rejects_wrong_phase(tmp_path: Path) -> None:
    path = _write_report(tmp_path, phase="paper", all_passed=True)
    with pytest.raises(SystemExit, match="live_small"):
        load_and_validate_eval_report(path, target_phase="live_full")


def test_load_and_validate_rejects_stale_report(tmp_path: Path) -> None:
    stale = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    path = _write_report(tmp_path, phase="paper", all_passed=True, computed_at=stale)
    with pytest.raises(SystemExit, match="days old"):
        load_and_validate_eval_report(path, target_phase="live_small")


def test_load_and_validate_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="unreadable"):
        load_and_validate_eval_report(
            tmp_path / "nope.json", target_phase="live_small"
        )


def test_load_and_validate_rejects_wrong_variant(tmp_path: Path) -> None:
    """W3-3: cross-variant report substitution must be refused."""
    path = _write_report(tmp_path, phase="paper", all_passed=True)
    # Report has variant="v1" (set by _write_report); caller trades "v2".
    with pytest.raises(SystemExit, match="variant"):
        load_and_validate_eval_report(
            path, target_phase="live_small", expected_variants=["v2"]
        )


def test_load_and_validate_rejects_non_traded_variant_multi(
    tmp_path: Path,
) -> None:
    """W3-3: multi-variant runs still refuse a non-traded variant."""
    path = _write_report(tmp_path, phase="paper", all_passed=True)
    # Report has variant="v1"; traded variants are v2 and v3.
    with pytest.raises(SystemExit, match="variant"):
        load_and_validate_eval_report(
            path, target_phase="live_small", expected_variants=["v2", "v3"]
        )


def test_load_and_validate_accepts_matching_variant(tmp_path: Path) -> None:
    """W3-3: correct variant passes without error."""
    path = _write_report(tmp_path, phase="paper", all_passed=True)
    payload = load_and_validate_eval_report(
        path, target_phase="live_small", expected_variants=["v1"]
    )
    assert payload["variant"] == "v1"


def test_load_and_validate_accepts_member_variant_multi(tmp_path: Path) -> None:
    """W3-3: membership in the traded set is sufficient (multi-variant)."""
    path = _write_report(tmp_path, phase="paper", all_passed=True)
    payload = load_and_validate_eval_report(
        path, target_phase="live_small", expected_variants=["v2", "v1"]
    )
    assert payload["variant"] == "v1"


def test_load_and_validate_skips_variant_check_when_none(tmp_path: Path) -> None:
    """Backward compat: expected_variants=None (or empty) skips the check."""
    path = _write_report(tmp_path, phase="paper", all_passed=True)
    payload = load_and_validate_eval_report(
        path, target_phase="live_small", expected_variants=None
    )
    assert payload["all_passed"] is True
    payload = load_and_validate_eval_report(
        path, target_phase="live_small", expected_variants=[]
    )
    assert payload["all_passed"] is True


def test_prior_phase_mapping_covers_both_live_phases() -> None:
    assert PRIOR_PHASE_FOR_ENTRY == {
        "live_small": "paper",
        "live_full": "live_small",
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_writes_report_and_exit_code_reflects_pass(tmp_path: Path) -> None:
    drift = tmp_path / "drift.json"
    drift.write_text(json.dumps(_passing_phase_a_artifact()), encoding="utf-8")
    audit = tmp_path / "audit.jsonl"
    audit.write_text(
        "\n".join(json.dumps(r) for r in _closed_audit_records(25)),
        encoding="utf-8",
    )
    # Stat-review S1 (#2674): Phase-A now requires the watchdog severity.
    watchdog = tmp_path / "watchdog.json"
    watchdog.write_text(
        json.dumps({"aggregate_severity": "green"}), encoding="utf-8"
    )
    out = tmp_path / "eval.json"
    rc = main(
        [
            "--criteria-phase",
            "paper",
            "--variant",
            "v1",
            "--drift-json",
            str(drift),
            "--audit-jsonl",
            str(audit),
            "--watchdog-json",
            str(watchdog),
            "--phase-started",
            PHASE_START_OK.isoformat(),
            "--today",
            TODAY.isoformat(),
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["all_passed"] is True
    assert payload["phase"] == "paper"
    assert payload["phase_promotion"] == "manual_signoff_only"


def test_cli_exit_1_on_failing_criteria(tmp_path: Path) -> None:
    drift = tmp_path / "drift.json"
    drift.write_text(json.dumps(_passing_phase_a_artifact()), encoding="utf-8")
    audit = tmp_path / "audit.jsonl"
    audit.write_text("", encoding="utf-8")
    out = tmp_path / "eval.json"
    rc = main(
        [
            "--criteria-phase",
            "paper",
            "--variant",
            "v1",
            "--drift-json",
            str(drift),
            "--audit-jsonl",
            str(audit),
            "--phase-started",
            PHASE_START_OK.isoformat(),
            "--today",
            TODAY.isoformat(),
            "--output",
            str(out),
        ]
    )
    assert rc == 1
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["all_passed"] is False
