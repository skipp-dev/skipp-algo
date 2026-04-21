"""Tests for Wald SPRT stop-rule (G3 / F2 promotion gate)."""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

import pytest

from scripts.smc_sprt_stop_rule import (
    SPRTConfig,
    SPRTState,
    decide,
    evaluate,
    evaluate_paired,
    main,
    update,
)


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def test_config_validates_p1_must_exceed_p0() -> None:
    with pytest.raises(ValueError, match="must exceed"):
        SPRTConfig(p0=0.6, p1=0.5)


def test_config_validates_probabilities_in_open_interval() -> None:
    with pytest.raises(ValueError):
        SPRTConfig(p0=0.0, p1=0.5)
    with pytest.raises(ValueError):
        SPRTConfig(p0=0.5, p1=1.0)


def test_config_validates_error_rates() -> None:
    with pytest.raises(ValueError):
        SPRTConfig(p0=0.5, p1=0.6, alpha=0.7)
    with pytest.raises(ValueError):
        SPRTConfig(p0=0.5, p1=0.6, beta=0.6)


def test_config_validates_max_n() -> None:
    with pytest.raises(ValueError):
        SPRTConfig(p0=0.5, p1=0.6, max_n=0)


def test_wald_bounds_match_formula() -> None:
    cfg = SPRTConfig(p0=0.5, p1=0.7, alpha=0.05, beta=0.20)
    assert cfg.upper_bound == pytest.approx(math.log(0.80 / 0.05))
    assert cfg.lower_bound == pytest.approx(math.log(0.20 / 0.95))


# ---------------------------------------------------------------------------
# Single-step update
# ---------------------------------------------------------------------------


def test_update_increments_count_and_hits() -> None:
    cfg = SPRTConfig(p0=0.5, p1=0.7)
    s = SPRTState()
    s = update(s, True, cfg)
    assert s.n == 1 and s.k == 1
    s = update(s, False, cfg)
    assert s.n == 2 and s.k == 1


def test_update_hit_pushes_llr_toward_h1() -> None:
    cfg = SPRTConfig(p0=0.5, p1=0.7)
    s_after_hit = update(SPRTState(), True, cfg)
    s_after_miss = update(SPRTState(), False, cfg)
    assert s_after_hit.llr > 0
    assert s_after_miss.llr < 0


# ---------------------------------------------------------------------------
# Decision logic
# ---------------------------------------------------------------------------


def test_decide_continues_inside_bounds() -> None:
    cfg = SPRTConfig(p0=0.5, p1=0.7)
    assert decide(SPRTState(n=1, k=1, llr=0.1), cfg) == "continue"


def test_decide_accepts_h1_at_upper_bound() -> None:
    cfg = SPRTConfig(p0=0.5, p1=0.7)
    s = SPRTState(n=10, k=10, llr=cfg.upper_bound + 0.01)
    assert decide(s, cfg) == "accept_h1"


def test_decide_accepts_h0_at_lower_bound() -> None:
    cfg = SPRTConfig(p0=0.5, p1=0.7)
    s = SPRTState(n=10, k=0, llr=cfg.lower_bound - 0.01)
    assert decide(s, cfg) == "accept_h0"


def test_decide_max_n_when_undecided() -> None:
    cfg = SPRTConfig(p0=0.5, p1=0.7, max_n=5)
    s = SPRTState(n=5, k=2, llr=0.0)
    assert decide(s, cfg) == "max_n_reached"


# ---------------------------------------------------------------------------
# evaluate() — end-to-end on synthetic streams
# ---------------------------------------------------------------------------


def test_evaluate_accepts_h1_on_strong_signal() -> None:
    cfg = SPRTConfig(p0=0.5, p1=0.7, alpha=0.05, beta=0.20)
    outcomes = [True] * 30  # 100% hits — trivially accept H1
    state, decision = evaluate(outcomes, cfg)
    assert decision == "accept_h1"
    assert state.n <= 30
    assert state.k == state.n


def test_evaluate_accepts_h0_on_low_hit_rate() -> None:
    cfg = SPRTConfig(p0=0.5, p1=0.7, alpha=0.05, beta=0.20)
    outcomes = [False] * 30
    state, decision = evaluate(outcomes, cfg)
    assert decision == "accept_h0"


def test_evaluate_max_n_on_ambiguous_data() -> None:
    cfg = SPRTConfig(p0=0.5, p1=0.7, alpha=0.05, beta=0.20, max_n=10)
    # Alternating hits/misses → LLR oscillates near zero, never crosses bounds
    # within max_n=10.
    outcomes = [True, False] * 5
    state, decision = evaluate(outcomes, cfg)
    assert decision == "max_n_reached"
    assert state.n == 10


def test_evaluate_under_h1_truth_decides_h1_with_high_prob() -> None:
    """Monte-Carlo: under true p=0.7, the test should accept H1 most of the time."""
    cfg = SPRTConfig(p0=0.5, p1=0.7, alpha=0.05, beta=0.20, max_n=200)
    rng = random.Random(0xC0FFEE)
    accept_h1 = 0
    trials = 50
    for _ in range(trials):
        outcomes = [rng.random() < 0.7 for _ in range(200)]
        _, d = evaluate(outcomes, cfg)
        if d == "accept_h1":
            accept_h1 += 1
    # With beta=0.20, expect >= 70% acceptance under H1 truth (some loss to max_n).
    assert accept_h1 / trials >= 0.70


# ---------------------------------------------------------------------------
# Paired-arm helper
# ---------------------------------------------------------------------------


def test_evaluate_paired_filters_concordant_pairs() -> None:
    cfg = SPRTConfig(p0=0.3, p1=0.8)
    pairs = [
        (True, True),    # concordant — discarded
        (False, False),  # concordant — discarded
        (False, True),   # treatment-only hit -> True
        (False, True),
        (False, True),
    ]
    state, _ = evaluate_paired(pairs, cfg)
    # Only 3 discordant pairs remain.
    assert state.n == 3
    assert state.k == 3


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


def test_main_writes_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    outcomes_path = tmp_path / "outcomes.jsonl"
    outcomes_path.write_text(
        "\n".join(json.dumps({"hit": True}) for _ in range(30)) + "\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "report.json"
    rc = main([
        "--outcomes", str(outcomes_path),
        "--p0", "0.5",
        "--p1", "0.7",
        "--output", str(output_path),
    ])
    assert rc == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["decision"] == "accept_h1"
    assert report["k"] == report["n"]
    assert report["schema_version"] == 1
