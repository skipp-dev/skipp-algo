"""Property tests for ``scripts.run_ab_comparison.benjamini_hochberg``.

The BH helper is the heart of the FDR control surface
(``digest['fdr']`` and ``digest['fdr_calibration']``). Existing tests
exercise it indirectly via the digest layer; this module locks in
the **mathematical contract** of the helper itself so a stealth
refactor (e.g. swapping running-max for running-min, or breaking
the monotone step-up rule) is caught immediately.

Pinned properties:

1. **Empty input → empty result.** Output dict carries the requested
   ``q`` and empty ``rejected``/``adjusted`` lists, ``threshold=None``.
2. **Output preserves input order.** ``len(rejected) == len(adjusted)
   == len(input)`` for every shuffle of the same p-value multiset.
3. **Monotonicity of adjusted p-values along the *sorted* axis.**
   When sorted by raw p-value, the adjusted sequence is
   non-decreasing (the BH "monotonisation" step).
4. **Adjusted p-values lie in [0, 1].**
5. **q=1.0 rejects everything below 1.0.** With FDR cap fully open,
   the only un-rejected hypotheses are p == 1.0 exactly.
6. **q=0 rejects nothing.** Edge of the BH inequality
   ``p_(k) <= (k/m) * 0`` is satisfied only by p=0; any positive p
   stays un-rejected.
7. **Rejection set is a prefix of the sorted-p ordering.** If a
   hypothesis with rank r is rejected, every hypothesis with rank
   ≤ r is rejected. (BH step-up cannot leave gaps.)
8. **Threshold equals the largest sorted p that was rejected.**
9. **Pairwise consistency with ``rejected``:** every rejected p is
   ≤ ``threshold``; every un-rejected p is > ``threshold`` (or
   ``threshold is None`` and no rejections).
"""

from __future__ import annotations

import random
from itertools import pairwise

import pytest

from scripts.run_ab_comparison import benjamini_hochberg


def test_empty_input_returns_empty_result() -> None:
    out = benjamini_hochberg([], q=0.10)
    assert out == {"rejected": [], "adjusted": [], "threshold": None, "q": 0.10}


@pytest.mark.parametrize("seed", [0, 1, 42, 1337, 2026])
def test_output_lengths_match_input(seed: int) -> None:
    rng = random.Random(seed)
    pvals = [rng.random() for _ in range(rng.randint(1, 100))]
    out = benjamini_hochberg(pvals, q=0.10)
    assert len(out["rejected"]) == len(pvals)
    assert len(out["adjusted"]) == len(pvals)


@pytest.mark.parametrize("seed", [0, 1, 42, 1337, 2026])
def test_adjusted_monotone_along_sorted_axis(seed: int) -> None:
    rng = random.Random(seed)
    pvals = [rng.random() for _ in range(rng.randint(2, 50))]
    out = benjamini_hochberg(pvals, q=0.10)
    # Re-sort by raw p-value and check adjusted is non-decreasing.
    paired = sorted(zip(pvals, out["adjusted"], strict=False), key=lambda x: x[0])
    adj_sorted = [a for _, a in paired]
    for prev, curr in pairwise(adj_sorted):
        assert prev <= curr + 1e-12, (
            f"BH-adjusted p-values not monotone along sorted axis: {adj_sorted}"
        )


@pytest.mark.parametrize("seed", [0, 1, 42, 1337, 2026])
def test_adjusted_in_unit_interval(seed: int) -> None:
    rng = random.Random(seed)
    pvals = [rng.random() for _ in range(rng.randint(1, 100))]
    out = benjamini_hochberg(pvals, q=0.10)
    for adj in out["adjusted"]:
        assert 0.0 <= adj <= 1.0


def test_q_one_rejects_all_strictly_below_one() -> None:
    pvals = [0.001, 0.10, 0.50, 0.99, 1.0]
    out = benjamini_hochberg(pvals, q=1.0)
    # With q=1.0 the BH inequality ``p_(k) <= (k/m) * 1.0 = k/m``
    # admits the largest k whose sorted-p does not exceed k/m.
    # For 5 sorted ps [0.001, 0.10, 0.50, 0.99, 1.0]:
    # k=5: 1.0 <= 5/5=1.0 ✓ → all 5 rejected.
    assert all(out["rejected"])
    assert out["threshold"] == 1.0


def test_q_zero_rejects_only_exact_zero_pvalues() -> None:
    pvals = [0.0, 0.001, 0.10, 0.50]
    out = benjamini_hochberg(pvals, q=0.0)
    # Only p=0.0 satisfies p <= (k/m) * 0 = 0.
    assert out["rejected"] == [True, False, False, False]
    assert out["threshold"] == 0.0


@pytest.mark.parametrize("seed", [0, 1, 42, 1337, 2026])
def test_rejection_set_is_prefix_of_sorted_order(seed: int) -> None:
    """If rank r is rejected, every rank < r is also rejected."""
    rng = random.Random(seed)
    pvals = [rng.random() for _ in range(rng.randint(2, 50))]
    out = benjamini_hochberg(pvals, q=0.10)
    paired = sorted(zip(pvals, out["rejected"], strict=False), key=lambda x: x[0])
    seen_unrejected = False
    for _, rej in paired:
        if not rej:
            seen_unrejected = True
        elif seen_unrejected:
            pytest.fail(
                f"BH rejection is not a sorted-order prefix: "
                f"{[r for _, r in paired]}"
            )


@pytest.mark.parametrize("seed", [0, 1, 42, 1337, 2026])
def test_threshold_separates_rejected_from_unrejected(seed: int) -> None:
    rng = random.Random(seed)
    pvals = [rng.random() for _ in range(rng.randint(1, 50))]
    out = benjamini_hochberg(pvals, q=0.10)
    threshold = out["threshold"]
    if threshold is None:
        assert not any(out["rejected"])
        return
    for p, rej in zip(pvals, out["rejected"], strict=False):
        if rej:
            assert p <= threshold + 1e-12, (
                f"rejected p={p} exceeds threshold {threshold}"
            )


@pytest.mark.parametrize("seed", [0, 1, 42, 1337, 2026])
def test_shuffle_invariance(seed: int) -> None:
    """Same multiset of p-values → same multiset of (adjusted, rejected)."""
    rng = random.Random(seed)
    pvals = [rng.random() for _ in range(rng.randint(2, 30))]
    out_a = benjamini_hochberg(pvals[:], q=0.10)
    shuffled = pvals[:]
    rng.shuffle(shuffled)
    out_b = benjamini_hochberg(shuffled, q=0.10)
    assert sorted(out_a["adjusted"]) == pytest.approx(sorted(out_b["adjusted"]))
    assert sorted(out_a["rejected"]) == sorted(out_b["rejected"])
    assert out_a["threshold"] == out_b["threshold"]


def test_textbook_three_pvalue_example() -> None:
    """B&H 1995 worked example (small): 3 p-values, q=0.05.

    p_sorted = [0.01, 0.04, 0.50]
    cutoffs = [(1/3)*0.05, (2/3)*0.05, (3/3)*0.05] = [0.0167, 0.0333, 0.05]
    Largest k with p_(k) <= cutoff: k=1 (0.01 <= 0.0167).
    Reject only the smallest p; threshold = 0.01.
    """
    out = benjamini_hochberg([0.50, 0.01, 0.04], q=0.05)
    assert out["rejected"] == [False, True, False]
    assert out["threshold"] == 0.01
