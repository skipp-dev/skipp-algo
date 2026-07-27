"""G3 arm routing — run-granular, paired, shadow-only.

Covers the three properties the §G3 decision gate depends on:
  1. the comparison metrics are correct (otherwise the sample is noise),
  2. Arm B never changes or breaks the live run,
  3. a missing Arm B is reported honestly instead of as "no difference".
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from open_prep import ab_arms
from open_prep.ab_arms import (
    ARM_A_LABEL,
    ARM_B_LABEL,
    arm_b_base_available,
    compare_arms,
    run_arm_b_shadow,
)


def _rows(*symbols: str) -> list[dict[str, Any]]:
    return [{"symbol": s, "score": float(len(symbols) - i)} for i, s in enumerate(symbols)]


# ── compare_arms ─────────────────────────────────────────────────────


def test_identical_rankings_are_reported_as_identical() -> None:
    out = compare_arms(_rows("A", "B", "C"), _rows("A", "B", "C"), top_n=3)
    assert out["identical_ranking"] is True
    assert out["spearman_rho"] == 1.0
    assert out["top_n_overlap"] == 3
    assert out["top_n_overlap_pct"] == 1.0
    assert out["top1_changed"] is False
    assert out["max_abs_rank_delta"] == 0
    assert out["entered_top_n"] == []
    assert out["left_top_n"] == []


def test_reversed_ranking_gives_perfect_negative_correlation() -> None:
    out = compare_arms(_rows("A", "B", "C"), _rows("C", "B", "A"), top_n=3)
    assert out["spearman_rho"] == -1.0
    assert out["identical_ranking"] is False
    assert out["top1_changed"] is True
    # Same members, so the top-N set is unchanged even though the order flipped.
    assert out["top_n_overlap"] == 3
    assert out["entered_top_n"] == []


def test_rank_delta_sign_and_membership_changes() -> None:
    """Arm B ranks D into the top 2 and pushes B out."""
    out = compare_arms(_rows("A", "B", "C", "D"), _rows("A", "D", "C", "B"), top_n=2)
    assert out["rank_delta"] == {"A": 0, "B": 2, "C": 0, "D": -2}
    assert out["entered_top_n"] == ["D"]
    assert out["left_top_n"] == ["B"]
    assert out["top_n_overlap"] == 1
    assert out["top_n_overlap_pct"] == 0.5
    assert out["mean_abs_rank_delta"] == 1.0
    assert out["max_abs_rank_delta"] == 2


def test_partially_disjoint_arms_only_correlate_over_common_symbols() -> None:
    out = compare_arms(_rows("A", "B", "C"), _rows("B", "C", "Z"), top_n=3)
    assert out["n_common"] == 2
    assert out["arm_a_n"] == 3
    assert out["arm_b_n"] == 3
    assert set(out["rank_delta"]) == {"B", "C"}


def test_correlation_is_none_when_too_few_common_symbols() -> None:
    assert compare_arms(_rows("A"), _rows("A"), top_n=1)["spearman_rho"] is None
    assert compare_arms(_rows("A"), _rows("Z"), top_n=1)["spearman_rho"] is None


def test_rows_without_a_usable_symbol_are_skipped() -> None:
    out = compare_arms(
        [{"symbol": "A"}, {"symbol": ""}, {"score": 1.0}, {"symbol": 7}],
        _rows("A"),
        top_n=1,
    )
    assert out["arm_a_n"] == 1


# ── arm availability ─────────────────────────────────────────────────


def test_missing_candidate_set_is_not_treated_as_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`load_weight_set` would silently fall back to DEFAULT_WEIGHTS here."""
    monkeypatch.setattr(ab_arms, "OUTCOMES_DIR", tmp_path)
    assert arm_b_base_available() is False
    (tmp_path / "weights_candidate.json").write_text("{}", encoding="utf-8")
    assert arm_b_base_available() is True


# ── run_arm_b_shadow ─────────────────────────────────────────────────


def test_unavailable_arm_b_is_recorded_honestly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ab_arms, "OUTCOMES_DIR", tmp_path / "outcomes")
    out_dir = tmp_path / "ab_arms"

    record = run_arm_b_shadow(
        quotes=[], bias=0.0, top_n=5, news_scores=None, news_metrics=None,
        sector_changes=None, symbol_sectors=None, vix_level=None,
        apply_regime=lambda w, _s: w, regime_snapshot=None,
        arm_a_rows=_rows("A"), day="2026-07-27", out_dir=out_dir,
    )

    assert record["status"] == "arm_b_unavailable"
    # Crucially NOT a zero-difference row, which would dilute the sample.
    assert "spearman_rho" not in record
    written = json.loads((out_dir / "ab_arms_2026-07-27.json").read_text(encoding="utf-8"))
    assert written["status"] == "arm_b_unavailable"
    assert json.loads((out_dir / "latest.json").read_text(encoding="utf-8")) == written


def test_shadow_arm_uses_the_same_regime_tilt_as_arm_a(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Arm parity: the base weights must be the only difference between arms."""
    outcomes = tmp_path / "outcomes"
    outcomes.mkdir()
    (outcomes / "weights_candidate.json").write_text('{"gap": 9.0}', encoding="utf-8")
    monkeypatch.setattr(ab_arms, "OUTCOMES_DIR", outcomes)
    monkeypatch.setattr(ab_arms, "load_weight_set", lambda label: {"gap": 9.0, "_label": label})

    seen: dict[str, Any] = {}

    def _apply_regime(weights: dict[str, Any], snapshot: Any) -> dict[str, Any]:
        seen["base"] = dict(weights)
        seen["snapshot"] = snapshot
        return {**weights, "tilted": True}

    def _rank(**kwargs: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        seen["label"] = kwargs["weight_label"]
        return _rows("B", "A"), []

    saved: dict[str, Any] = {}
    monkeypatch.setattr(ab_arms, "save_weight_set", lambda label, w: saved.update({label: w}))
    monkeypatch.setattr(ab_arms, "rank_candidates_v2", _rank)

    record = run_arm_b_shadow(
        quotes=[], bias=0.0, top_n=2, news_scores=None, news_metrics=None,
        sector_changes=None, symbol_sectors=None, vix_level=None,
        apply_regime=_apply_regime, regime_snapshot="RISK_ON",
        arm_a_rows=_rows("A", "B"), day="2026-07-27", out_dir=tmp_path / "ab",
    )

    assert record["status"] == "ok"
    # The learned base went through the same regime tilt Arm A gets...
    assert seen["base"]["_label"] == "candidate"
    assert seen["snapshot"] == "RISK_ON"
    # ...and was scored under its own label, never overwriting Arm A's.
    assert saved[ARM_B_LABEL]["tilted"] is True
    assert ARM_A_LABEL not in saved
    assert seen["label"] == ARM_B_LABEL
    assert record["arm_b_label"] == ARM_B_LABEL
    assert record["top1_changed"] is True


def test_shadow_failure_never_propagates_into_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes = tmp_path / "outcomes"
    outcomes.mkdir()
    (outcomes / "weights_candidate.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(ab_arms, "OUTCOMES_DIR", outcomes)

    def _boom(**_kw: Any) -> None:
        raise RuntimeError("scorer exploded")

    monkeypatch.setattr(ab_arms, "rank_candidates_v2", _boom)

    record = run_arm_b_shadow(
        quotes=[], bias=0.0, top_n=2, news_scores=None, news_metrics=None,
        sector_changes=None, symbol_sectors=None, vix_level=None,
        apply_regime=lambda w, _s: w, regime_snapshot=None,
        arm_a_rows=_rows("A"), day="2026-07-27", out_dir=tmp_path / "ab",
    )

    assert record["status"] == "error"
    assert "scorer exploded" in record["reason"]
