"""Unit tests for the ADR-0023 Stage-1 weekly judgement evaluator."""
from __future__ import annotations

from scripts.eval_magnitude_shadow_weekly import (
    detect_all_pass_red_flag,
    evaluate_family,
    evaluate_weekly,
    group_by_family,
    main,
    render_text,
    sparkline,
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


def _streak(family: str, statuses: list[str], **kw: float) -> list[dict[str, object]]:
    return [
        _row(date=f"2026-06-{i + 1:02d}", family=family, status=s, **kw)
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
    # 3 PASS clears k-of-n, but CI-low falls toward the 0.55 floor.
    rows = [
        _row(date="2026-06-01", family="BOS", status="PASS", ci_low=0.59),
        _row(date="2026-06-02", family="BOS", status="PASS", ci_low=0.57),
        _row(date="2026-06-03", family="BOS", status="PASS", ci_low=0.555),
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
    # all share date 2026-06-01
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
    assert "Stage-2 eligible: BOS" in text


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
    assert v["auc_window"] == [0.63, 0.63, 0.63]


def test_render_includes_sparkline_for_family():
    rows = _streak("BOS", ["PASS", "PASS", "PASS"], auc=0.62)
    text = render_text(evaluate_weekly(rows, k=2, n=4))
    # at least one block glyph appears in the rendered family line
    assert any(ch in text for ch in "▁▂▃▄▅▆▇█")


def test_render_shows_progress_for_incomplete_candidate():
    rows = _streak("BOS", ["PASS", "FAIL", "FAIL"])
    text = render_text(evaluate_weekly(rows, k=3, n=4))
    assert "Stage-2 progress: 1/3 PASS — needs 2 more" in text


def test_render_no_progress_line_for_eligible_candidate():
    rows = _streak("BOS", ["PASS", "PASS", "PASS"])
    text = render_text(evaluate_weekly(rows, k=2, n=4))
    assert "needs" not in text


def test_main_empty_ledger_returns_3(tmp_path):
    missing = tmp_path / "nope.jsonl"
    assert main(["--ledger", str(missing)]) == 3


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
