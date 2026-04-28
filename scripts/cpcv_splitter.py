"""Combinatorial Purged Cross-Validation (Sprint C2 / T5).

Implements ``CombinatorialPurgedSplitter`` per Lopez de Prado,
*Advances in Financial Machine Learning* (2018), ch. 12. Splits a
chronological observation index into ``n_groups`` contiguous groups,
then enumerates every C(n_groups, k_test_groups) combination — yielding
significantly more OOS paths than k-fold while still respecting time
order via purging and embargo.

The output set of OOS paths is consumed by the walk-forward runner to
build a *distribution* of OOS Sharpe values; downstream callers can
report e.g. the 10th-percentile Sharpe as a robust worst-case
indicator (see C2 sprint plan T5 acceptance criteria).

Pure stdlib + numpy. Independent of ``scripts/walk_forward.py`` (T2).

References
----------
- Lopez de Prado (2018), *Advances in Financial Machine Learning*, ch. 12.
- https://www.quantbeckman.com/p/with-code-combinatorial-purged-cross
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import comb
from typing import Iterator

import numpy as np


@dataclass(frozen=True)
class CPCVSplit:
    """One combinatorial fold returned by :class:`CombinatorialPurgedSplitter`."""

    fold_idx: int
    test_groups: tuple[int, ...]
    train_idx: np.ndarray
    test_idx: np.ndarray


class CombinatorialPurgedSplitter:
    """Combinatorial purged cross-validation splitter.

    Parameters
    ----------
    n_groups:
        Total number of contiguous chronological groups to carve the
        observation set into. Lopez de Prado's typical recipe is
        ``n_groups=6`` and ``k_test_groups=2`` → 15 paths.
    k_test_groups:
        Number of groups assigned to the test set per combination.
    purge_size:
        Observations dropped from training immediately around each
        test-group boundary (both before and after) to absorb labels
        whose holding period crosses the boundary.
    embargo_size:
        Additional observations dropped *after* each test group from
        the training set, guarding against autocorrelation leakage.
    """

    def __init__(
        self,
        *,
        n_groups: int = 6,
        k_test_groups: int = 2,
        purge_size: int = 0,
        embargo_size: int = 0,
    ) -> None:
        if n_groups < 2:
            raise ValueError("n_groups must be >= 2")
        if k_test_groups < 1:
            raise ValueError("k_test_groups must be >= 1")
        if k_test_groups >= n_groups:
            raise ValueError("k_test_groups must be < n_groups")
        if purge_size < 0:
            raise ValueError("purge_size must be >= 0")
        if embargo_size < 0:
            raise ValueError("embargo_size must be >= 0")

        self.n_groups = n_groups
        self.k_test_groups = k_test_groups
        self.purge_size = purge_size
        self.embargo_size = embargo_size

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def n_paths(self) -> int:
        """Total number of fold combinations this splitter will yield."""

        return comb(self.n_groups, self.k_test_groups)

    def split(self, n_observations: int) -> Iterator[CPCVSplit]:
        """Enumerate every ``C(n_groups, k_test_groups)`` combination.

        Parameters
        ----------
        n_observations:
            Length of the (already chronologically sorted) observation
            index. Groups are formed by ``np.array_split``.
        """

        if n_observations < self.n_groups:
            raise ValueError(
                f"need at least n_groups={self.n_groups} observations, "
                f"got {n_observations}"
            )

        all_idx = np.arange(n_observations, dtype=np.int64)
        groups = np.array_split(all_idx, self.n_groups)

        for fold_idx, combo in enumerate(
            combinations(range(self.n_groups), self.k_test_groups)
        ):
            test_idx = np.concatenate([groups[g] for g in combo])
            train_groups = [g for g in range(self.n_groups) if g not in combo]
            if not train_groups:
                continue
            train_idx_raw = np.concatenate([groups[g] for g in train_groups])

            train_idx = self._purge_and_embargo(
                train_idx=train_idx_raw,
                test_groups=combo,
                groups=groups,
                n_observations=n_observations,
            )

            yield CPCVSplit(
                fold_idx=fold_idx,
                test_groups=combo,
                train_idx=train_idx,
                test_idx=test_idx,
            )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _purge_and_embargo(
        self,
        *,
        train_idx: np.ndarray,
        test_groups: tuple[int, ...],
        groups: list[np.ndarray],
        n_observations: int,
    ) -> np.ndarray:
        """Remove training rows in the purge zones around each test group."""

        if self.purge_size == 0 and self.embargo_size == 0:
            return train_idx

        keep = np.ones(len(train_idx), dtype=bool)
        for g in test_groups:
            test_lo = int(groups[g][0])
            test_hi = int(groups[g][-1])  # inclusive

            # Purge: drop `purge_size` rows immediately before and after
            # the test group. Using <= test_hi + purge_size captures the
            # post-purge zone; embargo extends only the post side.
            pre_lo = max(0, test_lo - self.purge_size)
            post_hi = min(n_observations - 1, test_hi + self.purge_size + self.embargo_size)
            in_zone = (train_idx >= pre_lo) & (train_idx <= post_hi)
            keep &= ~in_zone

        return train_idx[keep]
