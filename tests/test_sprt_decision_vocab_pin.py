"""Pin: SPRT decision vocab is closed and exhaustive.

``scripts/smc_sprt_stop_rule.py`` exposes a typed ``Decision`` literal
with five disjoint outcomes. Downstream gates (promotion, rollback,
inconclusive handling) branch on string identity. If a code path ever
returned ``None`` or a free-form string instead of one of the five
literals, the gate would silently fall through and the
treatment-vs-control rollout would deadlock.

This pin freezes:

1. The exact membership of the ``Decision`` literal (sentinel set).
2. ``INCONCLUSIVE_DECISIONS`` is a subset of ``Decision``.
3. Every public decision-returning function actually returns a member
   of the vocab on representative inputs (continue / accept_h0 /
   accept_h1 / max_n_reached / inconclusive).
"""

from __future__ import annotations

import typing

from scripts.smc_sprt_stop_rule import (
    INCONCLUSIVE_DECISIONS,
    SPRTConfig,
    SPRTState,
    decide,
    evaluate,
    terminal_decision,
)
from scripts import smc_sprt_stop_rule

_EXPECTED_VOCAB: frozenset[str] = frozenset({
    "continue",
    "accept_h0",
    "accept_h1",
    "max_n_reached",
    "inconclusive",
})


def _decision_literal_args() -> frozenset[str]:
    decision = smc_sprt_stop_rule.Decision
    return frozenset(typing.get_args(decision))


def test_decision_literal_membership_is_frozen() -> None:
    observed = _decision_literal_args()
    assert observed == _EXPECTED_VOCAB, (
        f"Decision literal drift: observed={sorted(observed)} "
        f"expected={sorted(_EXPECTED_VOCAB)}. "
        f"Adding/removing a decision sentinel is a CONTRACT BREAK — "
        f"every downstream gate that branches on Decision must be updated "
        f"and this pin must be bumped intentionally."
    )


def test_inconclusive_decisions_is_subset_of_vocab() -> None:
    extras = sorted(set(INCONCLUSIVE_DECISIONS) - _EXPECTED_VOCAB)
    assert not extras, (
        f"INCONCLUSIVE_DECISIONS contains non-vocab token(s): {extras}. "
        f"Every entry must be a member of the Decision literal."
    )


def test_decide_returns_continue_on_neutral_state() -> None:
    cfg = SPRTConfig(p0=0.5, p1=0.6, alpha=0.05, beta=0.2)
    state = SPRTState()  # n=0, llr=0.0 → strictly between bounds
    result = decide(state, cfg)
    assert result in _EXPECTED_VOCAB
    assert result == "continue"


def test_decide_returns_max_n_reached_when_capped() -> None:
    cfg = SPRTConfig(p0=0.5, p1=0.6, alpha=0.05, beta=0.2, max_n=1)
    # llr=0 (strictly between bounds), n>=max_n → max_n_reached
    state = SPRTState(n=1, k=0, llr=0.0)
    result = decide(state, cfg)
    assert result == "max_n_reached"


def test_evaluate_decision_is_vocab_member() -> None:
    cfg = SPRTConfig(p0=0.5, p1=0.6, alpha=0.05, beta=0.2, max_n=20)
    _, decision = evaluate([True] * 20, cfg)
    assert decision in _EXPECTED_VOCAB


def test_terminal_decision_is_vocab_member() -> None:
    cfg = SPRTConfig(p0=0.5, p1=0.6, alpha=0.05, beta=0.2)
    _, decision = terminal_decision(5, 3, cfg)
    assert decision in _EXPECTED_VOCAB
    # n=0 → explicit "inconclusive"
    _, zero_decision = terminal_decision(0, 0, cfg)
    assert zero_decision == "inconclusive"
