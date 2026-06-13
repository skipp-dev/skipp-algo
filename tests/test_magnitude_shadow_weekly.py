"""Unit tests for the ADR-0023 Stage-1 weekly judgement evaluator."""
from __future__ import annotations

from datetime import date, timedelta

from scripts.eval_magnitude_shadow_weekly import (
    detect_all_pass_red_flag,
    evaluate_demotions,
    evaluate_family,
    evaluate_weekly,
    group_by_family,
    main,
    render_text,
    sparkline,
    stage2_status_line,
    weekly_evaluations,
)


def _row(
    *,
    date: str,
    family: str,
    status: str,
    auc: float = 0.62,
    ci_low: float = 0.59,
) -> dict[str, object]:
    return {
        "date": date,
        "family": family,
        "status": status,
        "magnitude_auc": auc,
        "auc_ci_low": ci_low,
    }


# Monday anchoring the synthetic streaks. Statuses in ``_streak`` are spaced
# one ISO week apart so that one status == one weekly evaluation (handover
# §4.4); same-week collapse behaviour is exercised by the dedicated
# ``weekly_evaluations`` tests further down.
_WEEK0 = date(2026, 5, 11)


def _streak(family: str, statuses: list[str], **kw: float) -> list[dict[str, object]]:
    return [
        _row(
            date=str(_WEEK0 + timedelta(weeks=i)),
            family=family,
            status=s,
            **kw,
        )
        for i, s in enumerate(statuses)
    ]


# ---- group_by_family ----------------------------------------------------


def test_group_by_family_sorts_by_date():
    rows = [
        _row(date="2026-06-03", family="BOS", status="PASS"),
        _row(date="2026-06-01", family="BOS", status="FAIL"),
        _row(date="2026-06-02", family="SWEEP", status="PASS"),
    ]
    grouped = group_by_family(rows)
    assert set(grouped) == {"BOS", "SWEEP"}
    assert [r["date"] for r in grouped["BOS"]] == ["2026-06-01", "2026-06-03"]


def test_group_by_family_ignores_rows_without_family():
    grouped = group_by_family([{"date": "2026-06-01", "status": "PASS"}])
    assert grouped == {}


# ---- evaluate_family ----------------------------------------------------


def test_candidate_meets_k_of_n_is_eligible():
    rows = _streak("BOS", ["PASS", "FAIL", "PASS", "PASS"])
    v = evaluate_family("BOS", rows, k=3, n=4)
    assert v["role"] == "candidate"
    assert v["pass_count"] == 3
    assert v["meets_k_of_n"] is True
    assert v["healthy"] is True
    assert v["stage2_eligible"] is True


def test_candidate_below_k_is_not_eligible():
    rows = _streak("BOS", ["PASS", "FAIL", "FAIL", "PASS"])
    v = evaluate_family("BOS", rows, k=3, n=4)
    assert v["pass_count"] == 2
    assert v["meets_k_of_n"] is False
    assert v["stage2_eligible"] is False


def test_candidate_ci_low_trending_to_floor_blocks_eligibility():
    # 3 weekly PASSes clear k-of-n, but CI-low falls toward the 0.55 floor.
    rows = [
        _row(date="2026-05-18", family="BOS", status="PASS", ci_low=0.59),
        _row(date="2026-05-25", family="BOS", status="PASS", ci_low=0.57),
        _row(date="2026-06-01", family="BOS", status="PASS", ci_low=0.555),
    ]
    v = evaluate_family("BOS", rows, k=2, n=4)
    assert v["meets_k_of_n"] is True
    assert v["ci_low_trending_to_floor"] is True
    assert v["healthy"] is False
    assert v["stage2_eligible"] is False


def test_window_truncates_to_trailing_n():
    rows = _streak("BOS", ["FAIL", "FAIL", "PASS", "PASS", "PASS"])
    v = evaluate_family("BOS", rows, k=3, n=3)
    assert v["window_size"] == 3
    assert v["pass_count"] == 3
    assert v["meets_k_of_n"] is True


def test_inconclusive_not_counted_as_pass():
    rows = _streak("BOS", ["INCONCLUSIVE", "INCONCLUSIVE", "PASS", "PASS"])
    v = evaluate_family("BOS", rows, k=3, n=4)
    assert v["inconclusive_count"] == 2
    assert v["pass_count"] == 2
    assert v["meets_k_of_n"] is False


def test_control_healthy_when_stays_below_bar():
    rows = _streak("FVG", ["FAIL", "FAIL", "FAIL", "FAIL"])
    v = evaluate_family("FVG", rows, k=3, n=4)
    assert v["role"] == "control"
    assert v["healthy"] is True
    assert v["stage2_eligible"] is False


def test_control_passing_is_unhealthy():
    rows = _streak("OB", ["FAIL", "PASS", "FAIL", "FAIL"])
    v = evaluate_family("OB", rows, k=3, n=4)
    assert v["pass_count"] == 1
    assert v["healthy"] is False
    assert v["stage2_eligible"] is False


# ---- red flag -----------------------------------------------------------


def test_all_pass_red_flag_fires_on_latest_date():
    rows = (
        _streak("BOS", ["PASS"])
        + _streak("SWEEP", ["PASS"])
        + _streak("FVG", ["PASS"])
        + _streak("OB", ["PASS"])
    )
    # all share the _WEEK0 date
    assert detect_all_pass_red_flag(rows) is True


def test_red_flag_does_not_fire_with_a_fail():
    rows = [
        _row(date="2026-06-01", family="BOS", status="PASS"),
        _row(date="2026-06-01", family="FVG", status="FAIL"),
    ]
    assert detect_all_pass_red_flag(rows) is False


def test_red_flag_needs_two_families():
    rows = [_row(date="2026-06-01", family="BOS", status="PASS")]
    assert detect_all_pass_red_flag(rows) is False


def test_red_flag_only_considers_latest_date():
    rows = [
        _row(date="2026-06-01", family="BOS", status="PASS"),
        _row(date="2026-06-01", family="FVG", status="PASS"),
        _row(date="2026-06-02", family="BOS", status="PASS"),
        _row(date="2026-06-02", family="FVG", status="FAIL"),
    ]
    assert detect_all_pass_red_flag(rows) is False


# ---- evaluate_weekly ----------------------------------------------------


def test_evaluate_weekly_collects_eligible_candidates():
    rows = (
        _streak("BOS", ["PASS", "PASS", "PASS", "PASS"])
        + _streak("SWEEP", ["PASS", "FAIL", "FAIL", "PASS"])
        + _streak("FVG", ["FAIL", "FAIL", "FAIL", "FAIL"])
    )
    report = evaluate_weekly(rows, k=3, n=4)
    assert report["stage2_eligible"] == ["BOS"]
    assert report["all_pass_red_flag"] is False
    assert set(report["families"]) == {"BOS", "SWEEP", "FVG"}


def test_red_flag_zeroes_eligibility():
    rows = (
        _streak("BOS", ["PASS", "PASS", "PASS"])
        + _streak("SWEEP", ["PASS", "PASS", "PASS"])
        + _streak("FVG", ["PASS", "PASS", "PASS"])
        + _streak("OB", ["PASS", "PASS", "PASS"])
    )
    report = evaluate_weekly(rows, k=2, n=4)
    assert report["all_pass_red_flag"] is True
    assert report["stage2_eligible"] == []


# ---- render + main ------------------------------------------------------


def test_render_text_mentions_families_and_eligibility():
    rows = _streak("BOS", ["PASS", "PASS", "PASS", "PASS"])
    text = render_text(evaluate_weekly(rows, k=3, n=4))
    assert "BOS" in text
    assert "eligible to arm Stage 2: BOS" in text


# ---- sparkline ----------------------------------------------------------


def test_sparkline_empty_series_is_empty():
    assert sparkline([]) == ""


def test_sparkline_length_matches_series():
    assert len(sparkline([0.5, 0.6, 0.7])) == 3


def test_sparkline_monotonic_values_are_non_decreasing_glyphs():
    blocks = "▁▂▃▄▅▆▇█"
    spark = sparkline([0.50, 0.60, 0.70])
    assert spark[0] == blocks[0]
    assert spark[-1] == blocks[-1]
    ranks = [blocks.index(ch) for ch in spark]
    assert ranks == sorted(ranks)


def test_sparkline_clamps_out_of_range():
    blocks = "▁▂▃▄▅▆▇█"
    # values below lo and above hi clamp to the extreme glyphs
    assert sparkline([0.10, 0.99]) == blocks[0] + blocks[-1]


def test_sparkline_non_numeric_renders_gap():
    spark = sparkline([0.6, None, "x", True])
    assert spark[1] == "·"
    assert spark[2] == "·"
    # bool is excluded even though it is an int subclass
    assert spark[3] == "·"


def test_sparkline_nan_renders_gap():
    spark = sparkline([0.6, float("nan"), 0.65])
    assert len(spark) == 3
    assert spark[1] == "·"
    # Surrounding real values must still render as blocks
    assert spark[0] in "▁▂▃▄▅▆▇█"
    assert spark[2] in "▁▂▃▄▅▆▇█"


def test_sparkline_rejects_bad_range():
    import pytest

    with pytest.raises(ValueError):
        sparkline([0.6], lo=0.7, hi=0.5)


# ---- auc_window + Stage-2 progress render -------------------------------


def test_evaluate_family_exposes_auc_window():
    rows = _streak("BOS", ["PASS", "FAIL", "PASS"], auc=0.63)
    v = evaluate_family("BOS", rows, k=2, n=4)
    # 4-week calendar window, oldest week has no data → None padding slot.
    assert v["auc_window"] == [None, 0.63, 0.63, 0.63]


def test_render_includes_sparkline_for_family():
    rows = _streak("BOS", ["PASS", "PASS", "PASS"], auc=0.62)
    text = render_text(evaluate_weekly(rows, k=2, n=4))
    # at least one block glyph appears in the rendered family line
    assert any(ch in text for ch in "▁▂▃▄▅▆▇█")


def test_render_shows_progress_for_incomplete_candidate():
    rows = _streak("BOS", ["PASS", "FAIL", "FAIL"])
    text = render_text(evaluate_weekly(rows, k=3, n=4))
    assert "Stage-2 progress: 1/3 weekly PASS — needs 2 more" in text


def test_render_no_progress_line_for_eligible_candidate():
    rows = _streak("BOS", ["PASS", "PASS", "PASS"])
    text = render_text(evaluate_weekly(rows, k=2, n=4))
    assert "needs" not in text


def test_main_empty_ledger_returns_3(tmp_path):
    missing = tmp_path / "nope.jsonl"
    assert main(["--ledger", str(missing)]) == 3


def test_main_corrupt_ledger_returns_1(tmp_path, capsys):
    """W7-1: a malformed ledger line must fail the weekly judgement loudly
    (rc 1), not silently shrink the vote set — dropped rows could flip a
    strict weekly majority or keep a demotion window permanently partial."""
    ledger = tmp_path / "led.jsonl"
    ledger.write_text(
        '{"date": "2026-06-01", "family": "BOS", "status": "PASS"}\n'
        "not json\n",
        encoding="utf-8",
    )
    assert main(["--ledger", str(ledger)]) == 1
    assert "malformed ledger line" in capsys.readouterr().err


def test_main_writes_and_returns_0(tmp_path, capsys):
    import json

    ledger = tmp_path / "ledger.jsonl"
    rows = _streak("BOS", ["PASS", "PASS", "PASS", "PASS"])
    ledger.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    rc = main(["--ledger", str(ledger), "--k", "3", "--n", "4"])
    assert rc == 0
    assert "BOS" in capsys.readouterr().out


def test_main_red_flag_returns_2(tmp_path):
    import json

    ledger = tmp_path / "ledger.jsonl"
    rows = [
        _row(date="2026-06-01", family="BOS", status="PASS"),
        _row(date="2026-06-01", family="SWEEP", status="PASS"),
        _row(date="2026-06-01", family="FVG", status="PASS"),
        _row(date="2026-06-01", family="OB", status="PASS"),
    ]
    ledger.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert main(["--ledger", str(ledger), "--k", "1", "--n", "4"]) == 2


def test_main_rejects_k_greater_than_n(tmp_path):
    assert main(["--ledger", str(tmp_path / "x.jsonl"), "--k", "5", "--n", "4"]) == 1


# ---- stage2_status_line (handover §4.5) ----------------------------------


def _full_week_rows():
    return (
        _streak("BOS", ["PASS", "FAIL", "PASS", "PASS"])
        + _streak("SWEEP", ["PASS", "PASS", "PASS", "PASS"])
        + _streak("FVG", ["FAIL", "FAIL", "FAIL", "FAIL"])
        + _streak("OB", ["FAIL", "FAIL", "FAIL", "FAIL"])
    )


def test_stage2_status_line_matches_handover_format():
    report = evaluate_weekly(_full_week_rows(), k=3, n=4)
    line = stage2_status_line(report)
    assert line == (
        "Stage-2 exit status: BOS 3/4 ✓, SWEEP 4/4 ✓, "
        "FVG 0/4 (control), OB 0/4 (control) "
        "→ eligible to arm Stage 2: BOS, SWEEP"
    )


def test_stage2_status_line_marks_failing_candidate():
    rows = (
        _streak("BOS", ["PASS", "FAIL", "FAIL", "FAIL"])
        + _streak("FVG", ["FAIL", "FAIL", "FAIL", "FAIL"])
    )
    line = stage2_status_line(evaluate_weekly(rows, k=3, n=4))
    assert "BOS 1/4 ✗" in line
    assert line.endswith("→ eligible to arm Stage 2: none")


def test_stage2_status_line_rendered_in_text_report():
    text = render_text(evaluate_weekly(_full_week_rows(), k=3, n=4))
    assert "Stage-2 exit status: " in text
    assert "eligible to arm Stage 2: BOS, SWEEP" in text


# ---- evaluate_demotions (handover §5 item 7) -------------------------------


def test_full_window_kofn_failure_demotes_armed_family():
    rows = _streak("BOS", ["FAIL", "FAIL", "PASS", "FAIL"])
    report = evaluate_weekly(rows, k=3, n=4)
    demotions = evaluate_demotions(report, frozenset({"BOS"}))
    assert [d["family"] for d in demotions] == ["BOS"]
    assert "1/4 PASS (need 3)" in demotions[0]["reason"]


def test_partial_window_never_demotes():
    # Only 2 of 4 window slots filled — thin evidence is not a regression.
    rows = _streak("BOS", ["FAIL", "FAIL"])
    report = evaluate_weekly(rows, k=3, n=4)
    assert evaluate_demotions(report, frozenset({"BOS"})) == []


def test_absent_family_never_demotes():
    rows = _streak("BOS", ["PASS", "PASS", "PASS", "PASS"])
    report = evaluate_weekly(rows, k=3, n=4)
    assert evaluate_demotions(report, frozenset({"SWEEP"})) == []


def test_unarmed_family_never_demotes():
    rows = _streak("BOS", ["FAIL", "FAIL", "FAIL", "FAIL"])
    report = evaluate_weekly(rows, k=3, n=4)
    assert evaluate_demotions(report, frozenset()) == []


def test_red_flag_suspends_demotion():
    rows = (
        _streak("BOS", ["FAIL", "FAIL", "FAIL", "PASS"])
        + _streak("SWEEP", ["PASS", "PASS", "PASS", "PASS"])
    )
    report = evaluate_weekly(rows, k=3, n=4)
    assert report["all_pass_red_flag"] is True
    # BOS fails k-of-n over a full window but the artifact flag suspends it.
    assert evaluate_demotions(report, frozenset({"BOS"})) == []


def test_healthy_armed_family_not_demoted():
    rows = _streak("BOS", ["PASS", "FAIL", "PASS", "PASS"])
    report = evaluate_weekly(rows, k=3, n=4)
    assert evaluate_demotions(report, frozenset({"BOS"})) == []


# ---- main: policy / demotions / output -------------------------------------


def _write_policy(path, families):
    import json

    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "stage": 2 if families else 1,
                "armed_families": sorted(families),
                "k": 3,
                "n": 4,
                "history": [],
            }
        ),
        encoding="utf-8",
    )


def _write_ledger(path, rows):
    import json

    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_main_apply_demotions_rewrites_policy_and_returns_4(tmp_path):
    import json

    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, _streak("BOS", ["FAIL", "FAIL", "FAIL", "FAIL"]))
    policy = tmp_path / "policy.json"
    _write_policy(policy, ["BOS"])
    rc = main(
        [
            "--ledger", str(ledger),
            "--policy", str(policy),
            "--apply-demotions",
        ]
    )
    assert rc == 4
    payload = json.loads(policy.read_text(encoding="utf-8"))
    assert payload["armed_families"] == []
    assert payload["stage"] == 1
    assert payload["history"][-1]["action"] == "demote"
    assert payload["history"][-1]["family"] == "BOS"


def test_main_without_apply_reports_pending_and_returns_0(tmp_path, capsys):
    import json

    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, _streak("BOS", ["FAIL", "FAIL", "FAIL", "FAIL"]))
    policy = tmp_path / "policy.json"
    _write_policy(policy, ["BOS"])
    rc = main(["--ledger", str(ledger), "--policy", str(policy)])
    assert rc == 0
    assert "DEMOTION PENDING: BOS" in capsys.readouterr().out
    # Policy file untouched without the flag.
    assert json.loads(policy.read_text(encoding="utf-8"))["armed_families"] == [
        "BOS"
    ]


def test_main_missing_policy_file_is_unarmed_default(tmp_path, capsys):
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, _streak("BOS", ["FAIL", "FAIL", "FAIL", "FAIL"]))
    rc = main(
        [
            "--ledger", str(ledger),
            "--policy", str(tmp_path / "missing.json"),
            "--apply-demotions",
        ]
    )
    assert rc == 0  # nothing armed → nothing to demote
    assert "DEMOTION" not in capsys.readouterr().out


def test_main_malformed_policy_returns_1(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, _streak("BOS", ["PASS"]))
    policy = tmp_path / "policy.json"
    policy.write_text("{broken", encoding="utf-8")
    assert main(["--ledger", str(ledger), "--policy", str(policy)]) == 1


def test_main_output_writes_report_json(tmp_path):
    import json

    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, _streak("BOS", ["PASS", "PASS", "PASS", "PASS"]))
    policy = tmp_path / "policy.json"
    _write_policy(policy, ["BOS"])
    out = tmp_path / "report.json"
    rc = main(
        [
            "--ledger", str(ledger),
            "--policy", str(policy),
            "--output", str(out),
        ]
    )
    assert rc == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["armed_families"] == ["BOS"]
    assert report["demotions"] == []
    assert report["demotions_applied"] is False
    assert report["stage2_eligible"] == ["BOS"]


def test_main_red_flag_takes_priority_over_demotion_exit(tmp_path):
    # Red flag suspends demotion entirely, so exit is 2 and policy untouched.
    import json

    rows = [
        _row(date="2026-06-01", family="BOS", status="PASS"),
        _row(date="2026-06-01", family="SWEEP", status="PASS"),
        _row(date="2026-06-01", family="FVG", status="PASS"),
        _row(date="2026-06-01", family="OB", status="PASS"),
    ]
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, rows)
    policy = tmp_path / "policy.json"
    _write_policy(policy, ["BOS", "SWEEP"])
    rc = main(
        [
            "--ledger", str(ledger),
            "--policy", str(policy),
            "--apply-demotions",
            "--k", "1", "--n", "1",
        ]
    )
    assert rc == 2
    assert json.loads(policy.read_text(encoding="utf-8"))["armed_families"] == [
        "BOS",
        "SWEEP",
    ]


def test_render_text_lists_armed_families():
    report = evaluate_weekly(_full_week_rows(), k=3, n=4)
    report["armed_families"] = ["BOS", "SWEEP"]
    text = render_text(report)
    assert "Stage-2 armed (strict magnitude): BOS, SWEEP" in text


# ---- ISO-week bucketing (handover §4.4: weekly evaluations, not daily) -----


def _days(family: str, statuses: list[str], *, start: date) -> list[dict[str, object]]:
    """Consecutive *daily* rows (1-day spacing) starting at ``start``."""
    return [
        _row(date=str(start + timedelta(days=i)), family=family, status=s)
        for i, s in enumerate(statuses)
    ]


def test_same_week_daily_rows_collapse_to_one_weekly_evaluation():
    # THE cold-start regression: 4 PASS days within a single ISO week are ONE
    # weekly evaluation, not 4 — a freshly seeded ledger must not be able to
    # clear k-of-n (and thereby claim Stage-2 eligibility) within days.
    rows = _days("BOS", ["PASS", "PASS", "PASS", "PASS"], start=_WEEK0)
    v = evaluate_family("BOS", rows, k=3, n=4)
    assert v["pass_count"] == 1
    assert v["window_size"] == 1
    assert v["meets_k_of_n"] is False
    assert v["stage2_eligible"] is False


def test_cold_start_single_week_never_demotes():
    # Mirror image of the regression above: 4 FAIL days in one week are ONE
    # measurable weekly evaluation — far from the full n-week evidence the
    # auto-demotion rule requires.
    rows = _days("BOS", ["FAIL", "FAIL", "FAIL", "FAIL"], start=_WEEK0)
    report = evaluate_weekly(rows, k=3, n=4)
    assert report["families"]["BOS"]["window_size"] == 1
    assert evaluate_demotions(report, frozenset({"BOS"})) == []


def test_weekly_tie_counts_as_fail():
    # 1 PASS + 1 FAIL in the same week: no strict majority → FAIL.
    rows = _days("BOS", ["PASS", "FAIL"], start=_WEEK0)
    weeks = weekly_evaluations(rows, anchor_monday=_WEEK0, n=1)
    assert weeks[0]["status"] == "FAIL"
    assert weeks[0]["pass_days"] == 1
    assert weeks[0]["fail_days"] == 1


def test_same_day_rerun_votes_once_in_weekly_majority():
    """W7-3: the ledger merge key includes ``events_hash``, so a same-day
    re-run against refreshed events leaves TWO rows for that calendar date.
    Counting both would let one day vote twice and flip a tie (FAIL) into a
    strict majority (PASS) out of a single trading day's evidence."""
    monday = str(_WEEK0)
    rows = [
        _row(date=monday, family="BOS", status="PASS"),
        _row(date=monday, family="BOS", status="PASS"),  # re-run, new hash
        _row(date=str(_WEEK0 + timedelta(days=1)), family="BOS", status="FAIL"),
    ]
    weeks = weekly_evaluations(rows, anchor_monday=_WEEK0, n=1)
    assert weeks[0]["pass_days"] == 1
    assert weeks[0]["fail_days"] == 1
    assert weeks[0]["status"] == "FAIL"  # tie, not a fabricated majority


def test_same_day_rerun_latest_row_wins():
    """W7-3 tie-break: within one date the latest ledger row (later list
    position, same rule as ``latest_rows_by_family``) supplies both the
    day's vote and the week's AUC numbers."""
    monday = str(_WEEK0)
    rows = [
        _row(date=monday, family="BOS", status="FAIL", auc=0.55, ci_low=0.49),
        _row(date=monday, family="BOS", status="PASS", auc=0.66, ci_low=0.61),
    ]
    weeks = weekly_evaluations(rows, anchor_monday=_WEEK0, n=1)
    assert weeks[0]["pass_days"] == 1
    assert weeks[0]["fail_days"] == 0
    assert weeks[0]["status"] == "PASS"
    assert weeks[0]["magnitude_auc"] == 0.66
    assert weeks[0]["auc_ci_low"] == 0.61


def test_weekly_strict_pass_majority_passes():
    rows = _days("BOS", ["PASS", "PASS", "PASS", "FAIL", "FAIL"], start=_WEEK0)
    weeks = weekly_evaluations(rows, anchor_monday=_WEEK0, n=1)
    assert weeks[0]["status"] == "PASS"


def test_inconclusive_only_week_is_inconclusive():
    rows = _days("BOS", ["INCONCLUSIVE", "INCONCLUSIVE"], start=_WEEK0)
    weeks = weekly_evaluations(rows, anchor_monday=_WEEK0, n=1)
    assert weeks[0]["status"] == "INCONCLUSIVE"


def test_empty_calendar_week_is_inconclusive_padding():
    # Data in W20 and W22, outage in W21: the gap week still consumes a
    # window slot as INCONCLUSIVE — it can never count toward k.
    rows = [
        _row(date=str(_WEEK0), family="BOS", status="PASS"),
        _row(date=str(_WEEK0 + timedelta(weeks=2)), family="BOS", status="PASS"),
    ]
    weeks = weekly_evaluations(
        rows, anchor_monday=_WEEK0 + timedelta(weeks=2), n=3
    )
    assert [w["status"] for w in weeks] == ["PASS", "INCONCLUSIVE", "PASS"]
    v = evaluate_family("BOS", rows, k=3, n=3)
    assert v["pass_count"] == 2
    assert v["inconclusive_count"] == 1
    assert v["meets_k_of_n"] is False


def test_week_uses_latest_daily_numbers():
    rows = [
        _row(date=str(_WEEK0), family="BOS", status="PASS", auc=0.61, ci_low=0.56),
        _row(
            date=str(_WEEK0 + timedelta(days=2)),
            family="BOS",
            status="PASS",
            auc=0.64,
            ci_low=0.60,
        ),
    ]
    weeks = weekly_evaluations(rows, anchor_monday=_WEEK0, n=1)
    assert weeks[0]["magnitude_auc"] == 0.64
    assert weeks[0]["auc_ci_low"] == 0.60


def test_week_labels_are_iso_formatted():
    rows = [_row(date=str(_WEEK0), family="BOS", status="PASS")]
    weeks = weekly_evaluations(rows, anchor_monday=_WEEK0, n=2)
    assert [w["week"] for w in weeks] == ["2026-W19", "2026-W20"]


def test_global_anchor_pads_stale_family():
    # SWEEP's feed stopped two weeks before BOS's latest row: judged on the
    # ledger-wide anchor, its recent weeks are INCONCLUSIVE padding — stale
    # passes cannot silently keep a family eligible-looking forever.
    rows = (
        _streak("BOS", ["PASS", "PASS", "PASS", "PASS"])
        + _streak("SWEEP", ["PASS", "PASS"])
    )
    report = evaluate_weekly(rows, k=3, n=4)
    sweep = report["families"]["SWEEP"]
    assert sweep["pass_count"] == 2
    assert sweep["inconclusive_count"] == 2
    assert sweep["stage2_eligible"] is False


def test_malformed_dates_are_skipped_not_fatal():
    rows = [
        _row(date="not-a-date", family="BOS", status="PASS"),
        _row(date=str(_WEEK0), family="BOS", status="PASS"),
    ]
    v = evaluate_family("BOS", rows, k=1, n=1)
    assert v["pass_count"] == 1


def test_latest_fields_ignore_malformed_dates():
    # A malformed date sorts lexicographically after ISO dates ("n" > "2");
    # latest_* must come from the newest PARSEABLE row, not raw-string max.
    rows = [
        _row(date=str(_WEEK0), family="BOS", status="PASS", auc=0.63),
        _row(date="not-a-date", family="BOS", status="FAIL", auc=0.10),
    ]
    v = evaluate_family("BOS", rows, k=1, n=1)
    assert v["latest_date"] == str(_WEEK0)
    assert v["latest_status"] == "PASS"
    assert v["latest_auc"] == 0.63


def test_report_latest_date_and_red_flag_ignore_malformed_dates():
    rows = (
        _streak("BOS", ["PASS"])
        + _streak("SWEEP", ["FAIL"])
        + [_row(date="zzzz-99-99", family="FVG", status="PASS")]
    )
    report = evaluate_weekly(rows, k=1, n=1)
    assert report["latest_date"] == str(_WEEK0)
    # Red flag judged on the parseable latest date (PASS+FAIL → no flag),
    # not on the lone malformed-date PASS row.
    assert report["all_pass_red_flag"] is False
