"""Tests for scripts/plan_2_8_q4_gate_evaluator.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.plan_2_8_q4_gate_evaluator import (
    evaluate_gate,
    main,
    render_markdown,
)


def _bundle(**kwargs) -> dict:
    base = {
        "buckets": [
            {"key": "RTH/NORMAL/LONG",  "hr_baseline": 0.60, "hr_candidate": 0.65, "n_events": 50},
            {"key": "RTH/NORMAL/SHORT", "hr_baseline": 0.58, "hr_candidate": 0.63, "n_events": 40},
            {"key": "ETH/HIGH-VOL/LONG", "hr_baseline": 0.55, "hr_candidate": 0.56, "n_events": 35},
        ],
        "brier_baseline": 0.20,
        "brier_candidate": 0.21,
    }
    base.update(kwargs)
    return base


def test_all_three_gates_pass_happy_path() -> None:
    verdict = evaluate_gate(_bundle())
    assert verdict["overall"] == "pass"
    assert verdict["gates"]["G1_uplift"]["passed"] is True
    assert verdict["gates"]["G1_uplift"]["uplift_bucket_count"] == 2
    assert verdict["gates"]["G2_brier"]["passed"] is True
    assert verdict["gates"]["G3_min_events"]["passed"] is True


def test_g1_fails_when_only_one_bucket_uplifts() -> None:
    bundle = _bundle(buckets=[
        {"key": "A", "hr_baseline": 0.60, "hr_candidate": 0.65, "n_events": 50},
        {"key": "B", "hr_baseline": 0.60, "hr_candidate": 0.61, "n_events": 50},
        {"key": "C", "hr_baseline": 0.60, "hr_candidate": 0.60, "n_events": 50},
    ])
    verdict = evaluate_gate(bundle)
    assert verdict["overall"] == "fail"
    assert verdict["gates"]["G1_uplift"]["passed"] is False
    assert verdict["gates"]["G1_uplift"]["uplift_bucket_count"] == 1


def test_g2_fails_when_brier_regresses_above_threshold() -> None:
    verdict = evaluate_gate(_bundle(brier_candidate=0.25))
    assert verdict["overall"] == "fail"
    assert verdict["gates"]["G2_brier"]["passed"] is False
    assert verdict["gates"]["G2_brier"]["brier_regression"] == pytest.approx(0.05)


def test_g2_passes_when_brier_improves() -> None:
    verdict = evaluate_gate(_bundle(brier_candidate=0.18))
    assert verdict["gates"]["G2_brier"]["passed"] is True


def test_g3_fails_when_any_bucket_below_threshold() -> None:
    bundle = _bundle(buckets=[
        {"key": "A", "hr_baseline": 0.60, "hr_candidate": 0.65, "n_events": 50},
        {"key": "B", "hr_baseline": 0.60, "hr_candidate": 0.65, "n_events": 10},
        {"key": "C", "hr_baseline": 0.60, "hr_candidate": 0.65, "n_events": 50},
    ])
    verdict = evaluate_gate(bundle)
    assert verdict["overall"] == "fail"
    g3 = verdict["gates"]["G3_min_events"]
    assert g3["passed"] is False
    assert g3["under_threshold_buckets"] == ["B"]


def test_bucket_delta_pp_sign_correct() -> None:
    verdict = evaluate_gate(_bundle(buckets=[
        {"key": "A", "hr_baseline": 0.70, "hr_candidate": 0.65, "n_events": 50},
    ]))
    assert verdict["buckets"][0]["delta_pp"] == pytest.approx(-0.05)
    assert verdict["buckets"][0]["uplift_ok"] is False


def test_custom_thresholds_affect_outcome() -> None:
    bundle = _bundle(buckets=[
        {"key": "A", "hr_baseline": 0.60, "hr_candidate": 0.61, "n_events": 50},
        {"key": "B", "hr_baseline": 0.60, "hr_candidate": 0.62, "n_events": 50},
    ])
    # Tight 3pp threshold: both fail.
    verdict = evaluate_gate(bundle, uplift_min_pp=0.03)
    assert verdict["gates"]["G1_uplift"]["uplift_bucket_count"] == 0
    # Loose 1pp threshold: both pass.
    verdict = evaluate_gate(bundle, uplift_min_pp=0.01)
    assert verdict["gates"]["G1_uplift"]["uplift_bucket_count"] == 2


def test_invalid_threshold_rejected() -> None:
    with pytest.raises(ValueError):
        evaluate_gate(_bundle(), uplift_min_buckets=0)
    with pytest.raises(ValueError):
        evaluate_gate(_bundle(), min_events_per_bucket=-1)


def test_bundle_shape_rejected() -> None:
    with pytest.raises(ValueError):
        evaluate_gate({"buckets": "not a list"})
    with pytest.raises(ValueError):
        evaluate_gate({"buckets": ["not a dict"]})


def test_render_markdown_contains_all_sections() -> None:
    verdict = evaluate_gate(_bundle())
    md = render_markdown(verdict)
    assert "# Plan 2.8 Q4-Gate verdict" in md
    assert "`pass`" in md
    assert "## Gates" in md
    assert "## Brier" in md
    assert "## Buckets" in md


def test_cli_reads_bundle_and_writes_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(_bundle()), encoding="utf-8")
    out = tmp_path / "verdict.json"
    rc = main([
        "--bundle", str(bundle_path),
        "--output", str(out),
    ])
    assert rc == 0
    verdict = json.loads(out.read_text(encoding="utf-8"))
    assert verdict["overall"] == "pass"
    stdout = capsys.readouterr().out
    assert "Q4-Gate verdict" in stdout


def test_cli_json_format(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(_bundle()), encoding="utf-8")
    rc = main([
        "--bundle", str(bundle_path),
        "--format", "json",
    ])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["overall"] == "pass"


def test_cli_invalid_bundle_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle_path = tmp_path / "bad.json"
    bundle_path.write_text("{ not json", encoding="utf-8")
    rc = main(["--bundle", str(bundle_path)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "ERROR" in err
