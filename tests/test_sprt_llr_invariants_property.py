"""Property tests: SPRT LLR invariants (streaming ≡ closed-form, monotonicity).

``scripts.smc_sprt_stop_rule`` exposes two LLR accumulators that *must*
agree on the terminal log-likelihood-ratio for any Bernoulli sequence:

* Streaming: :func:`evaluate` / :func:`update` (per-observation increment).
* Closed-form: :func:`terminal_decision` (``k·ln(p1/p0) + (n−k)·ln((1−p1)/(1−p0))``).

A stealth refactor that swaps the streaming increment sign, reorders
``p1``/``p0`` in the log, or drops the ``1−p`` complement would silently
shift every SPRT promote/hold/rollback decision without tripping the
existing Wald-bound formula tests (``test_sprt_wald_bounds_property``).

Companion to :mod:`tests.test_sprt_wald_bounds_property` (decision-boundary
side) and PR #2362 / issue #45 (state-reset side). Where the Wald-bound
tests pin the *decision thresholds*, this module pins the *evidence
accumulator* that feeds them.

Properties pinned here
----------------------
1. **Order independence**: streaming LLR is invariant under any permutation
   of the outcome sequence (Bernoulli LLR is a sum of i.i.d. increments).
2. **Streaming ≡ closed-form**: streaming terminal LLR equals
   ``terminal_decision(n, k).llr`` bit-close for every ``(n, k)`` with
   ``0 ≤ k ≤ n``.
3. **Monotone in k**: for fixed ``n > 0`` and fixed config with ``p1 > p0``,
   ``terminal_decision(n, k+1).llr > terminal_decision(n, k).llr`` (every
   additional hit raises evidence for H1; a sign error in either log term
   breaks this).
4. **Paired evaluator ignores concordant pairs**: appending any number of
   ``(True, True)`` or ``(False, False)`` pairs does not change the
   :func:`evaluate_paired` outcome.
5. **n = 0 corner**: ``terminal_decision(0, 0)`` returns the zero state
   and ``"inconclusive"`` (documented sentinel; gates downstream rely on it).
"""

from __future__ import annotations

import math
import random
from itertools import product

import pytest

from scripts.smc_sprt_stop_rule import (
    SPRTConfig,
    SPRTState,
    evaluate_paired,
    terminal_decision,
    update,
)

# Configs spanning the documented validation range. Each row exercises a
# different (p0, p1) regime so a sign error on one log term is unlikely
# to cancel out across the grid.
_CONFIGS: tuple[SPRTConfig, ...] = (
    SPRTConfig(p0=0.50, p1=0.60, alpha=0.05, beta=0.20),
    SPRTConfig(p0=0.30, p1=0.45, alpha=0.025, beta=0.10),
    SPRTConfig(p0=0.70, p1=0.85, alpha=0.05, beta=0.20),
    SPRTConfig(p0=0.10, p1=0.20, alpha=0.01, beta=0.05),
    SPRTConfig(p0=0.45, p1=0.55, alpha=0.10, beta=0.25),
)

# (n, k) grid covering edge counts (0 hits, all hits) plus interior values.
_NK_CASES: tuple[tuple[int, int], ...] = tuple(
    (n, k) for n in (1, 2, 5, 17, 100) for k in (0, 1, n // 2, n - 1, n) if 0 <= k <= n
)


def _streaming_llr(n: int, k: int, config: SPRTConfig) -> float:
    """Run the streaming accumulator over k hits followed by n-k misses."""
    state = SPRTState()
    for _ in range(k):
        state = update(state, True, config)
    for _ in range(n - k):
        state = update(state, False, config)
    return state.llr


@pytest.mark.parametrize("config", _CONFIGS)
@pytest.mark.parametrize("n,k", _NK_CASES)
def test_streaming_llr_equals_closed_form(
    n: int, k: int, config: SPRTConfig
) -> None:
    """Streaming sum and closed-form formula agree to float precision."""
    streamed = _streaming_llr(n, k, config)
    closed_state, _ = terminal_decision(n, k, config)
    assert math.isclose(streamed, closed_state.llr, rel_tol=1e-12, abs_tol=1e-12), (
        f"streaming/closed-form LLR drift at n={n}, k={k}, "
        f"p0={config.p0}, p1={config.p1}: "
        f"streamed={streamed!r}, closed={closed_state.llr!r}"
    )


def _accumulate(outcomes: list[bool], config: SPRTConfig) -> SPRTState:
    """Drive :func:`update` over every outcome, bypassing Wald early-stop.

    :func:`evaluate` short-circuits on the first terminal :func:`decide`
    result, so permutations of the same multiset can yield different
    terminal states (different ``n``/``k`` consumed). The accumulator
    invariant under test here is on :func:`update` alone — drive it
    explicitly so the property is well-defined for any config / sequence.
    """
    state = SPRTState()
    for outcome in outcomes:
        state = update(state, outcome, config)
    return state


@pytest.mark.parametrize("config", _CONFIGS)
@pytest.mark.parametrize("seed", (0, 1, 2, 7, 42))
def test_accumulator_llr_order_independent(config: SPRTConfig, seed: int) -> None:
    """Permuting the outcome sequence leaves the accumulator LLR unchanged.

    Bernoulli LLR is a sum of i.i.d. log-likelihood-ratio increments; the
    final value depends only on the count of hits and misses, never on
    their order. A refactor that accidentally introduced a position-
    dependent term (e.g. EWMA weighting on :func:`update`) would break this.

    Drives :func:`update` directly to bypass :func:`evaluate`'s Wald
    early-stop, which is permitted to terminate at different ``n`` for
    different permutations of the same multiset.
    """
    rng = random.Random(seed)
    n = 50
    k = rng.randint(0, n)
    outcomes = [True] * k + [False] * (n - k)
    baseline_state = _accumulate(outcomes, config)

    for shuffle_seed in range(3):
        permuted = list(outcomes)
        random.Random(shuffle_seed * 100 + seed).shuffle(permuted)
        permuted_state = _accumulate(permuted, config)
        assert permuted_state.n == baseline_state.n == n
        assert permuted_state.k == baseline_state.k == k
        assert math.isclose(
            permuted_state.llr, baseline_state.llr, rel_tol=1e-12, abs_tol=1e-12
        ), (
            f"order-dependent LLR at seed={seed}, shuffle={shuffle_seed}: "
            f"baseline={baseline_state.llr!r}, permuted={permuted_state.llr!r}"
        )


@pytest.mark.parametrize("config", _CONFIGS)
@pytest.mark.parametrize("n", (1, 2, 5, 17, 100))
def test_terminal_llr_strictly_increasing_in_k(config: SPRTConfig, n: int) -> None:
    """For p1 > p0, each additional hit strictly raises the LLR.

    Increment per hit is ``ln(p1/p0) > 0``; per miss ``ln((1−p1)/(1−p0)) < 0``.
    A sign error in either term would invert this monotonicity and silently
    flip the SPRT decision at every (n, k).
    """
    previous = terminal_decision(n, 0, config)[0].llr
    for k in range(1, n + 1):
        current = terminal_decision(n, k, config)[0].llr
        assert current > previous, (
            f"LLR not monotone at n={n}, k={k}, "
            f"p0={config.p0}, p1={config.p1}: "
            f"llr[k-1]={previous!r} → llr[k]={current!r}"
        )
        previous = current


@pytest.mark.parametrize("config", _CONFIGS)
@pytest.mark.parametrize(
    "discordant_pairs",
    (
        [(False, True)],
        [(False, True), (False, True), (True, False)],
        [(True, False)] * 5 + [(False, True)] * 10,
    ),
)
@pytest.mark.parametrize(
    "concordant_to_inject",
    (
        [],
        [(True, True)] * 3,
        [(False, False)] * 7,
        [(True, True), (False, False)] * 4,
    ),
)
def test_evaluate_paired_ignores_concordant_pairs(
    config: SPRTConfig,
    discordant_pairs: list[tuple[bool, bool]],
    concordant_to_inject: list[tuple[bool, bool]],
) -> None:
    """Adding concordant (both-hit / both-miss) pairs does not move the LLR.

    The paired SPRT uses McNemar-style sufficient statistics — only
    discordant pairs carry signal. A regression that started counting
    concordant pairs (e.g. by dropping the ``if control != treatment``
    filter) would shift the LLR proportionally to the concordant count.
    """
    baseline_state, baseline_decision = evaluate_paired(
        iter(discordant_pairs), config
    )
    # Interleave concordant pairs into the discordant stream; final LLR
    # must equal the discordant-only baseline.
    augmented: list[tuple[bool, bool]] = []
    concordant_iter = iter(concordant_to_inject)
    for pair in discordant_pairs:
        augmented.append(pair)
        next_concordant = next(concordant_iter, None)
        if next_concordant is not None:
            augmented.append(next_concordant)
    augmented.extend(concordant_iter)

    aug_state, aug_decision = evaluate_paired(iter(augmented), config)
    assert math.isclose(
        aug_state.llr, baseline_state.llr, rel_tol=1e-12, abs_tol=1e-12
    ), (
        f"concordant pairs leaked into LLR: "
        f"baseline={baseline_state.llr!r}, augmented={aug_state.llr!r}"
    )
    assert aug_state.n == baseline_state.n, (
        f"concordant pairs inflated discordant count: "
        f"baseline n={baseline_state.n}, augmented n={aug_state.n}"
    )
    # Decision can only differ if early-stop fired mid-stream on the
    # augmented order; with the same final state the decision must match.
    assert aug_decision == baseline_decision


@pytest.mark.parametrize("config", _CONFIGS)
def test_terminal_decision_n_zero_returns_inconclusive(config: SPRTConfig) -> None:
    """``terminal_decision(0, 0)`` returns zero-state + ``"inconclusive"``.

    Downstream gates (g23_ab_watchdog, F2 rollback) treat ``"inconclusive"``
    as a no-action sentinel; a regression that raised here or returned
    ``"continue"`` would break the closed-form post-hoc evaluator and
    poison the gate's fail-soft path.
    """
    state, decision = terminal_decision(0, 0, config)
    assert state == SPRTState()
    assert decision == "inconclusive"
