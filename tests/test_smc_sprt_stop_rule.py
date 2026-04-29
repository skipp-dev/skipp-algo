"""Tests for Wald SPRT stop-rule (G3 / F2 promotion gate)."""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

import pytest

from scripts.smc_sprt_stop_rule import (
    INCONCLUSIVE_DECISIONS,
    SPRTConfig,
    SPRTState,
    decide,
    evaluate,
    evaluate_paired,
    main,
    terminal_decision,
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
    _state, decision = evaluate(outcomes, cfg)
    assert decision == "accept_h0"


def test_evaluate_max_n_on_ambiguous_data() -> None:
    cfg = SPRTConfig(p0=0.5, p1=0.7, alpha=0.05, beta=0.20, max_n=10)
    # Alternating hits/misses → LLR oscillates near zero, never crosses bounds
    # within max_n=10.
    outcomes = [True, False] * 5
    state, decision = evaluate(outcomes, cfg)
    assert decision == "max_n_reached"
    assert state.n == 10


# ---------------------------------------------------------------------------
# SPRT-1: "inconclusive" sentinel for terminal_decision
# ---------------------------------------------------------------------------


def test_terminal_decision_returns_inconclusive_when_llr_inside_bounds() -> None:
    cfg = SPRTConfig(p0=0.5, p1=0.7, alpha=0.05, beta=0.20)
    # n=4 with k=2 → LLR ~ 0; well inside Wald bounds.
    state, decision = terminal_decision(n=4, k=2, config=cfg)
    assert decision == "inconclusive"
    assert state.n == 4 and state.k == 2


def test_terminal_decision_zero_n_is_inconclusive_not_max_n_reached() -> None:
    """Regression: empty totals must surface as 'inconclusive', not 'max_n_reached'.

    'max_n_reached' is reserved for the streaming evaluator hitting an
    explicit observation cap; n=0 carries no cap semantics.
    """
    cfg = SPRTConfig(p0=0.5, p1=0.7)
    state, decision = terminal_decision(n=0, k=0, config=cfg)
    assert decision == "inconclusive"
    assert state.n == 0 and state.k == 0


def test_terminal_decision_still_accepts_h1_on_strong_evidence() -> None:
    cfg = SPRTConfig(p0=0.5, p1=0.7, alpha=0.05, beta=0.20)
    _state, decision = terminal_decision(n=100, k=85, config=cfg)
    assert decision == "accept_h1"


def test_terminal_decision_still_accepts_h0_on_low_hit_rate() -> None:
    cfg = SPRTConfig(p0=0.5, p1=0.7, alpha=0.05, beta=0.20)
    _state, decision = terminal_decision(n=100, k=20, config=cfg)
    assert decision == "accept_h0"


def test_evaluate_streaming_max_n_distinct_from_terminal_inconclusive() -> None:
    """max_n_reached vs inconclusive are *not* aliased — they carry
    different operational semantics (see module docstring)."""
    cfg = SPRTConfig(p0=0.5, p1=0.7, alpha=0.05, beta=0.20, max_n=10)
    streaming_state, streaming_decision = evaluate([True, False] * 5, cfg)
    _terminal_state, terminal_dec = terminal_decision(
        n=streaming_state.n, k=streaming_state.k, config=cfg
    )
    assert streaming_decision == "max_n_reached"
    assert terminal_dec == "inconclusive"
    # But both are members of the no-action set.
    assert streaming_decision in INCONCLUSIVE_DECISIONS
    assert terminal_dec in INCONCLUSIVE_DECISIONS


def test_inconclusive_decisions_tuple_is_disjoint_from_action_decisions() -> None:
    """Regression guard: accept_h0/accept_h1 must never be in the
    'no-action' set or downstream gates would silently stop promoting."""
    forbidden = {"accept_h0", "accept_h1"}
    assert forbidden.isdisjoint(set(INCONCLUSIVE_DECISIONS))


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
