"""Tests for the OV7 enrichment A/B experiment framework."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.smc_ab_experiment import (
    Experiment,
    apply_experiment_flags,
    load_experiment,
    summarize_assignment,
)

# ── Experiment construction ──────────────────────────────────────


def test_experiment_basic_creation() -> None:
    exp = Experiment(name="test", treatment_overrides={"enrich_news": True})
    assert exp.name == "test"
    assert exp.split_pct == 50


def test_experiment_rejects_bad_split() -> None:
    with pytest.raises(ValueError, match="split_pct"):
        Experiment(name="bad", treatment_overrides={}, split_pct=150)


def test_experiment_rejects_empty_name() -> None:
    with pytest.raises(ValueError, match="name"):
        Experiment(name="", treatment_overrides={})


# ── Deterministic assignment ─────────────────────────────────────


def test_assign_is_deterministic() -> None:
    exp = Experiment(name="det", treatment_overrides={}, salt="seed42")
    arm1 = exp.assign("AAPL")
    arm2 = exp.assign("AAPL")
    assert arm1 == arm2


def test_assign_splits_symbols() -> None:
    """50/50 split over 100 symbols should not put all in one arm."""
    exp = Experiment(name="split", treatment_overrides={}, split_pct=50)
    arms = [exp.assign(f"SYM{i}") for i in range(100)]
    treatment_count = arms.count("treatment")
    control_count = arms.count("control")
    # With 100 symbols and 50% split, expect roughly balanced (allow ±30).
    assert treatment_count > 10, f"Only {treatment_count} treatment"
    assert control_count > 10, f"Only {control_count} control"


def test_assign_100_pct_treatment() -> None:
    exp = Experiment(name="all-treat", treatment_overrides={}, split_pct=100)
    assert exp.assign("AAPL") == "treatment"
    assert exp.assign("MSFT") == "treatment"


def test_assign_0_pct_treatment() -> None:
    exp = Experiment(name="all-ctrl", treatment_overrides={}, split_pct=0)
    assert exp.assign("AAPL") == "control"
    assert exp.assign("MSFT") == "control"


# ── Flag resolution ──────────────────────────────────────────────


def test_resolve_flags_treatment() -> None:
    exp = Experiment(
        name="t",
        treatment_overrides={"enrich_news": True},
        control_overrides={"enrich_news": False},
        split_pct=100,
    )
    flags = exp.resolve_flags("AAPL")
    assert flags == {"enrich_news": True}


def test_resolve_flags_control() -> None:
    exp = Experiment(
        name="c",
        treatment_overrides={"enrich_news": True},
        control_overrides={"enrich_news": False},
        split_pct=0,
    )
    flags = exp.resolve_flags("AAPL")
    assert flags == {"enrich_news": False}


# ── apply_experiment_flags ───────────────────────────────────────


def test_apply_merges_overrides() -> None:
    base = {"enrich_regime": True, "enrich_news": False}
    exp = Experiment(
        name="news",
        treatment_overrides={"enrich_news": True},
        split_pct=100,
    )
    merged = apply_experiment_flags(base, exp, "AAPL")
    assert merged["enrich_news"] is True
    assert merged["enrich_regime"] is True  # unchanged


def test_apply_none_experiment_returns_copy() -> None:
    base = {"enrich_regime": True}
    result = apply_experiment_flags(base, None, "AAPL")
    assert result == base
    assert result is not base  # must be a copy


# ── Provenance tag ───────────────────────────────────────────────


def test_tag_includes_arm() -> None:
    exp = Experiment(name="exp1", treatment_overrides={}, split_pct=100)
    tag = exp.tag("AAPL")
    assert tag["experiment_name"] == "exp1"
    assert tag["experiment_arm"] == "treatment"


# ── Load from JSON ───────────────────────────────────────────────


def test_load_experiment(tmp_path: Path) -> None:
    spec = {
        "name": "file-test",
        "treatment_overrides": {"enrich_news": True},
        "control_overrides": {},
        "salt": "abc",
        "split_pct": 60,
    }
    p = tmp_path / "experiment.json"
    p.write_text(json.dumps(spec), encoding="utf-8")

    exp = load_experiment(p)
    assert exp.name == "file-test"
    assert exp.split_pct == 60
    assert exp.salt == "abc"


# ── summarize_assignment ─────────────────────────────────────────


def test_summarize_assignment() -> None:
    exp = Experiment(name="sum", treatment_overrides={}, split_pct=100)
    summary = summarize_assignment(exp, ["AAPL", "MSFT"])
    assert summary["treatment_count"] == 2
    assert summary["control_count"] == 0
    assert summary["total_symbols"] == 2
    assert "AAPL" in summary["treatment_symbols"]


# ── A/B comparison ───────────────────────────────────────────────


def test_compare_produces_metrics() -> None:
    from scripts.run_ab_comparison import compare

    pair_a: dict[str, Any] = {
        "symbol": "AAPL",
        "timeframe": "15m",
        "n_events": 30,
        "brier": 0.15,
        "calibrated_brier": 0.12,
        "calibrated_ece": 0.08,
        "hit_rate_pct": 80.0,
    }
    pair_b: dict[str, Any] = {
        "symbol": "AAPL",
        "timeframe": "15m",
        "n_events": 30,
        "brier": 0.20,
        "calibrated_brier": 0.18,
        "calibrated_ece": 0.12,
        "hit_rate_pct": 70.0,
    }

    digest = compare([pair_b], [pair_a], "test-exp")
    assert digest["control_grade"] in ("A", "B", "C", "D", "F")
    assert digest["treatment_grade"] in ("A", "B", "C", "D", "F")
    assert len(digest["metrics"]) == 4


def test_render_comparison_has_table() -> None:
    from scripts.run_ab_comparison import compare, render_comparison

    pair: dict[str, Any] = {
        "symbol": "X",
        "timeframe": "1H",
        "n_events": 10,
        "brier": 0.2,
        "calibrated_brier": 0.15,
        "calibrated_ece": 0.1,
        "hit_rate_pct": 75.0,
    }

    digest = compare([pair], [pair], "render-test")
    md = render_comparison(digest)
    assert "# A/B Comparison" in md
    assert "Control" in md
    assert "Treatment" in md
    assert "calibrated_brier" in md
