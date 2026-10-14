"""Unit tests for the ADR-0023 §5 E[PnL]-after-cost secondary check."""
from __future__ import annotations

import json

from governance.epnl_after_cost import (
    EPNL_CI_FLOOR,
    MIN_TRADES,
    evaluate_family_epnl,
    rank_weights,
)
from scripts.run_epnl_after_cost_gate import (
    _verdict_exit_code,
    build_report,
    main,
)

# ---- rank_weights -------------------------------------------------------


def test_rank_weights_mean_is_one():
    w = rank_weights([5.0, 1.0, 3.0, 9.0, 2.0])
    assert abs(sum(w) / len(w) - 1.0) < 1e-12


def test_rank_weights_monotone_in_score():
    scores = [10.0, 1.0, 5.0]
    w = rank_weights(scores)
    # highest score gets the largest weight, lowest the smallest
    assert w[0] == max(w)
    assert w[1] == min(w)


def test_rank_weights_ties_share_average():
    w = rank_weights([2.0, 2.0, 1.0, 3.0])
    # the two tied 2.0 scores get identical weights
    assert w[0] == w[1]


def test_rank_weights_empty_and_singleton():
    assert rank_weights([]) == []
    assert rank_weights([7.0]) == [1.0]


# ---- evaluate_family_epnl: sizing earns its keep ------------------------


def _aligned(n: int):
    """Scores ascending, returns ascending → positive score/return covariance."""
    scores = [float(i) for i in range(n)]
    returns = [(i - n / 2) / 1000.0 for i in range(n)]
    return scores, returns


def test_sizing_lifts_negative_equal_mean_to_pass():
    scores, returns = _aligned(60)
    r = evaluate_family_epnl("BOS", scores, returns, n_bootstrap=300, seed=11)
    assert r.verdict == "PASS"
    assert r.passes is True
    assert r.sizing_uplift > 0
    assert r.sized_ci_low > EPNL_CI_FLOOR
    assert r.fail_reasons == ()


def test_uniform_returns_have_zero_uplift():
    scores = [float(i) for i in range(50)]
    returns = [0.002] * 50  # constant → sizing cannot add value
    r = evaluate_family_epnl("SWEEP", scores, returns, n_bootstrap=200, seed=3)
    assert abs(r.sizing_uplift) < 1e-9
    # constant positive return is profitable at equal weight and sized
    assert r.sized_profitable is True
    assert r.verdict == "PASS"


def test_unprofitable_family_fails_epnl_floor():
    # returns uncorrelated with score and centred below zero
    scores = [float(i % 5) for i in range(50)]
    returns = [-0.003] * 50
    r = evaluate_family_epnl("FVG", scores, returns, n_bootstrap=200, seed=9)
    assert r.sized_profitable is False
    assert "epnl_floor" in r.fail_reasons
    assert r.verdict == "FAIL"


def test_anti_correlated_scores_are_value_destructive():
    # high score → low return: sizing concentrates on the losers
    n = 60
    scores = [float(i) for i in range(n)]
    returns = [(n / 2 - i) / 1000.0 for i in range(n)]
    r = evaluate_family_epnl("BOS", scores, returns, n_bootstrap=200, seed=5)
    assert r.sizing_uplift < 0
    assert "sizing_destructive" in r.fail_reasons
    assert r.verdict == "FAIL"


def test_thin_family_is_inconclusive():
    scores, returns = _aligned(MIN_TRADES - 1)
    r = evaluate_family_epnl("BOS", scores, returns, n_bootstrap=50, seed=1)
    assert r.verdict == "INCONCLUSIVE"
    assert r.min_sample_pass is False
    assert r.passes is False
    assert "min_sample" in r.fail_reasons


def test_length_mismatch_raises():
    try:
        evaluate_family_epnl("BOS", [1.0, 2.0], [0.1])
    except ValueError:
        return
    raise AssertionError("expected ValueError on mismatched lengths")


def test_result_is_deterministic_under_seed():
    scores, returns = _aligned(60)
    a = evaluate_family_epnl("BOS", scores, returns, n_bootstrap=200, seed=42)
    b = evaluate_family_epnl("BOS", scores, returns, n_bootstrap=200, seed=42)
    assert a.sized_ci_low == b.sized_ci_low
    assert a.sized_ci_high == b.sized_ci_high


# ---- build_report / CLI -------------------------------------------------


def _events(family: str, n: int, *, aligned: bool):
    """Minimal FamilyEvent records the calibration extractor can score.

    We rely on extract_family_calibration_samples to pull scores/returns; for a
    unit test we instead drive build_report through a monkeypatched extractor.
    """
    return [{"family": family, "i": i} for i in range(n)]


def test_build_report_tags_roles_and_verdict(monkeypatch):
    import scripts.run_epnl_after_cost_gate as gate

    scores, returns = _aligned(60)

    def fake_samples(events, *, cost_bps):
        return {
            "BOS": {"scores": scores, "returns": returns},
            "FVG": {"scores": scores, "returns": [-0.003] * 60},
        }

    monkeypatch.setattr(gate, "extract_family_calibration_samples", fake_samples)
    report = build_report([{"family": "BOS"}], n_boot=200, seed=7)

    assert report["results"]["BOS"]["role"] == "candidate"
    assert report["results"]["FVG"]["role"] == "control"
    assert report["results"]["BOS"]["passes"] is True
    assert report["candidates_passed"] == ["BOS"]
    assert _verdict_exit_code(report) == 0


def test_verdict_exit_codes():
    assert _verdict_exit_code({"candidates_measured": [], "candidates_passed": []}) == 3
    assert (
        _verdict_exit_code({"candidates_measured": ["BOS"], "candidates_passed": []})
        == 2
    )
    assert (
        _verdict_exit_code(
            {"candidates_measured": ["BOS"], "candidates_passed": ["BOS"]}
        )
        == 0
    )


def test_main_empty_events_returns_1(tmp_path):
    empty = tmp_path / "events.json"
    empty.write_text("[]")
    assert main([str(empty)]) == 1


def test_main_writes_report_and_exit_code(tmp_path, monkeypatch, capsys):
    import scripts.run_epnl_after_cost_gate as gate

    scores, returns = _aligned(60)

    def fake_samples(events, *, cost_bps):
        return {"BOS": {"scores": scores, "returns": returns}}

    monkeypatch.setattr(gate, "extract_family_calibration_samples", fake_samples)

    events_path = tmp_path / "events.json"
    events_path.write_text(json.dumps([{"family": "BOS"}]))
    out_path = tmp_path / "report.json"

    rc = main([str(events_path), "--n-bootstrap", "200", "--seed", "7", "--out", str(out_path)])
    assert rc == 0
    payload = json.loads(out_path.read_text())
    assert payload["candidates_passed"] == ["BOS"]
    assert payload["results"]["BOS"]["verdict"] == "PASS"
