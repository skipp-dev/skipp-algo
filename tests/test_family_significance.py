"""EV-14 / C4 — block-bootstrap significance + Benjamini-Hochberg tests."""
from __future__ import annotations

import random

import pytest

from governance.family_significance import (
    benjamini_hochberg_qvalues,
    block_bootstrap_pvalue,
    family_fdr_qvalues,
)


def _strong_positive(n: int = 60, seed: int = 1) -> list[float]:
    rng = random.Random(seed)
    # Mean ~ +0.01 with small noise -> a clear, detectable positive edge.
    return [0.01 + rng.gauss(0.0, 0.002) for _ in range(n)]


def _zero_mean(n: int = 60, seed: int = 2) -> list[float]:
    rng = random.Random(seed)
    return [rng.gauss(0.0, 0.01) for _ in range(n)]


def test_strong_positive_edge_is_significant() -> None:
    p = block_bootstrap_pvalue(_strong_positive(), block_length=4, B=2000, seed=0)
    assert 0.0 < p < 0.05


def test_zero_mean_is_not_significant() -> None:
    p = block_bootstrap_pvalue(_zero_mean(), block_length=4, B=2000, seed=0)
    # A zero-centred series should sit near or above the boundary, never small.
    assert p > 0.2


def test_negative_mean_is_strongly_insignificant() -> None:
    neg = [-0.01 for _ in range(40)]
    p = block_bootstrap_pvalue(neg, block_length=3, B=1000, seed=0)
    assert p >= 0.5


def test_pvalue_is_deterministic_under_seed() -> None:
    sample = _strong_positive()
    a = block_bootstrap_pvalue(sample, block_length=4, B=1000, seed=42)
    b = block_bootstrap_pvalue(sample, block_length=4, B=1000, seed=42)
    assert a == b


def test_block_length_is_clamped_to_sample() -> None:
    # block_length far larger than n must not raise; it is clamped to n-1.
    sample = _strong_positive(n=30)
    p = block_bootstrap_pvalue(sample, block_length=999, B=500, seed=0)
    assert 0.0 < p <= 1.0


def test_bootstrap_rejects_degenerate_input() -> None:
    with pytest.raises(ValueError, match="at least"):
        block_bootstrap_pvalue([0.01], block_length=1, B=100, seed=0)
    with pytest.raises(ValueError, match="finite"):
        block_bootstrap_pvalue([0.01, float("nan")], block_length=1, B=100, seed=0)


def test_benjamini_hochberg_known_values() -> None:
    # m=4, p=[0.01,0.02,0.03,0.04]; adjusted = p*m/rank then monotone-from-top.
    # ranks 1..4 -> [0.04, 0.04, 0.04, 0.04] after monotonicity.
    q = benjamini_hochberg_qvalues([0.01, 0.02, 0.03, 0.04])
    assert q == pytest.approx([0.04, 0.04, 0.04, 0.04])


def test_benjamini_hochberg_preserves_input_order() -> None:
    # Unsorted input: largest raw p should map back to its original slot.
    q = benjamini_hochberg_qvalues([0.04, 0.01, 0.5])
    assert len(q) == 3
    # The 0.5 entry (index 2) must remain the largest adjusted value.
    assert q[2] == max(q)


def test_benjamini_hochberg_is_monotone_in_rank() -> None:
    raw = [0.001, 0.2, 0.03, 0.9, 0.04]
    q = benjamini_hochberg_qvalues(raw)
    ordered = sorted(range(len(raw)), key=lambda i: raw[i])
    adj_in_rank = [q[i] for i in ordered]
    assert adj_in_rank == sorted(adj_in_rank)
    assert all(0.0 <= v <= 1.0 for v in q)


def test_benjamini_hochberg_empty_and_bounds() -> None:
    assert benjamini_hochberg_qvalues([]) == []
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        benjamini_hochberg_qvalues([0.5, 1.5])


def test_family_fdr_qvalues_maps_by_family() -> None:
    out = family_fdr_qvalues({"BOS": 0.01, "OB": 0.04, "FVG": 0.5})
    assert set(out) == {"BOS", "OB", "FVG"}
    # FVG (largest raw) keeps the largest q-value after adjustment.
    assert out["FVG"] == max(out.values())
    assert all(0.0 <= v <= 1.0 for v in out.values())
