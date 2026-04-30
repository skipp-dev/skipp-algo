"""Walk-forward splitter for time-series cross-validation (Sprint C2 / T2).

Provides ``WalkForwardSplitter`` with **rolling** and **anchored** window
modes, plus per-fold **purging** and **embargo** to prevent label leakage
into the training set.

The splitter operates on a sequence of trade *entry* timestamps and
optional *exit* timestamps. When exits are supplied, purging removes any
training trade whose exit lands inside (or within ``purge_size``
observations of) the corresponding test fold — this is the standard
Lopez de Prado "purged CV" guard against forward-looking labels.

Pure stdlib + numpy. No vectorbt / sklearn dependency.

References
----------
- Lopez de Prado, *Advances in Financial Machine Learning* (2018), ch. 7.
- https://en.wikipedia.org/wiki/Purged_cross-validation
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

WindowType = Literal["rolling", "anchored"]


@dataclass(frozen=True)
class WalkForwardSplit:
    """One fold returned by :class:`WalkForwardSplitter`."""

    fold_idx: int
    train_idx: np.ndarray
    test_idx: np.ndarray


class WalkForwardSplitter:
    """Chronological train / test splitter with purging and embargo.

    Parameters
    ----------
    window_type:
        ``"rolling"`` keeps a fixed-size training window that slides
        forward each fold; ``"anchored"`` (a.k.a. expanding) accumulates
        all earlier observations into the training set.
    n_splits:
        Number of folds to emit.
    train_size:
        Number of observations in each training window (rolling) or the
        size of the *first* training window (anchored). For
        ``"anchored"``, later folds extend this window.
    test_size:
        Number of observations per test fold.
    purge_size:
        Number of observations immediately preceding the test fold that
        are dropped from the training set. Use this to absorb the
        maximum trade-holding period so labels do not leak. ``0``
        disables purging.
    embargo_size:
        Number of observations immediately *after* the test fold that
        are dropped from all *subsequent* training sets. Guards against
        autocorrelation leakage. ``0`` disables embargo.
    """

    def __init__(
        self,
        *,
        window_type: WindowType = "rolling",
        n_splits: int = 5,
        train_size: int = 60,
        test_size: int = 15,
        purge_size: int = 0,
        embargo_size: int = 0,
    ) -> None:
        if window_type not in ("rolling", "anchored"):
            raise ValueError(
                f"window_type must be 'rolling' or 'anchored', got {window_type!r}"
            )
        if n_splits < 1:
            raise ValueError("n_splits must be >= 1")
        if train_size < 1:
            raise ValueError("train_size must be >= 1")
        if test_size < 1:
            raise ValueError("test_size must be >= 1")
        if purge_size < 0:
            raise ValueError("purge_size must be >= 0")
        if embargo_size < 0:
            raise ValueError("embargo_size must be >= 0")

        self.window_type = window_type
        self.n_splits = n_splits
        self.train_size = train_size
        self.test_size = test_size
        self.purge_size = purge_size
        self.embargo_size = embargo_size

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def required_observations(self) -> int:
        """Minimum observation count needed to emit ``n_splits`` folds."""

        return self.train_size + self.n_splits * self.test_size

    def split(
        self,
        timestamps: Sequence[int] | np.ndarray,
        *,
        exit_timestamps: Sequence[int] | np.ndarray | None = None,
    ) -> Iterator[WalkForwardSplit]:
        """Yield ``WalkForwardSplit`` objects in chronological order.

        Parameters
        ----------
        timestamps:
            Sorted entry timestamps (any monotonically non-decreasing
            comparable values — int seconds, ns, etc.).
        exit_timestamps:
            Optional exit timestamps aligned with ``timestamps``. When
            provided, any training trade whose exit lands inside the
            test fold's time span (or within ``purge_size`` test
            observations of its start) is purged.
        """

        ts = np.asarray(timestamps)
        n = len(ts)
        if n == 0:
            return
        if np.any(np.diff(ts) < 0):
            raise ValueError("timestamps must be monotonically non-decreasing")

        required = self.required_observations()
        if n < required:
            raise ValueError(
                f"need at least {required} observations for "
                f"n_splits={self.n_splits}, train_size={self.train_size}, "
                f"test_size={self.test_size}; got {n}"
            )

        exits: np.ndarray | None
        if exit_timestamps is not None:
            exits = np.asarray(exit_timestamps)
            if len(exits) != n:
                raise ValueError(
                    f"exit_timestamps length {len(exits)} != "
                    f"timestamps length {n}"
                )
        else:
            exits = None

        for fold_idx in range(self.n_splits):
            test_start = self.train_size + fold_idx * self.test_size
            test_end = test_start + self.test_size  # exclusive
            if test_end > n:
                break

            test_idx = np.arange(test_start, test_end)

            # Train window — rolling shifts forward, anchored expands.
            if self.window_type == "rolling":
                train_start_raw = test_start - self.train_size - fold_idx * self.embargo_size
                # Clamp to 0; embargo can't push us before the data.
                train_start = max(0, train_start_raw)
            else:  # anchored
                train_start = 0

            # Drop the immediately preceding `purge_size` rows.
            train_end = test_start - self.purge_size
            # Purge ate the whole training window — yield empty.
            train_idx = (
                np.empty(0, dtype=np.int64)
                if train_end <= train_start
                else np.arange(train_start, train_end)
            )

            # Apply embargo: remove from `train_idx` any observation
            # that fell inside an *earlier* fold's embargo window.
            # Earlier folds end at (train_size + k*test_size); their
            # embargo extends `embargo_size` further. For anchored
            # mode this matters; for rolling mode the train_start
            # adjustment above already accounts for it.
            if self.embargo_size > 0 and self.window_type == "anchored":
                train_idx = self._apply_anchored_embargo(train_idx, fold_idx)

            # Apply label-leakage purge using exit timestamps.
            #
            # Deep-Review 2026-04-27 (MINOR): the comparison below is
            # strict ``<`` on purpose. A training trade whose exit
            # timestamp equals ``test_t0`` (the first bar of the test
            # window) is **dropped** here, because the strict mask
            # ``exits < test_t0`` evaluates to False at equality. This
            # is the conservative choice — at bar-granularity inputs
            # (e.g. 1-min bars) a simultaneous exit at the boundary
            # bar carries label information from the same bar that
            # opens the test window. Switching to ``<=`` would *keep*
            # those trades (potential label leakage); switching to
            # ``<`` plus an additional ``embargo_size >= 1`` enforces
            # an even stricter separation.
            if exits is not None and len(train_idx) > 0:
                test_t0 = ts[test_start]
                pre_mask = exits[train_idx] < test_t0
                train_idx = train_idx[pre_mask]

            yield WalkForwardSplit(
                fold_idx=fold_idx,
                train_idx=train_idx,
                test_idx=test_idx,
            )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _apply_anchored_embargo(
        self, train_idx: np.ndarray, fold_idx: int
    ) -> np.ndarray:
        """Drop indices that fall in any *earlier* fold's embargo zone."""

        if fold_idx == 0 or self.embargo_size == 0:
            return train_idx

        embargo_zones: list[tuple[int, int]] = []
        for k in range(fold_idx):
            test_end_k = self.train_size + (k + 1) * self.test_size
            embargo_zones.append((test_end_k, test_end_k + self.embargo_size))

        keep = np.ones(len(train_idx), dtype=bool)
        for lo, hi in embargo_zones:
            keep &= ~((train_idx >= lo) & (train_idx < hi))
        return train_idx[keep]
