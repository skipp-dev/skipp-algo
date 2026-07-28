"""Stationary/iid resampling primitives for :mod:`governance.family_significance`.

> **REMOVED (stranded), 2026-07-28 — same treatment as C4.1.** The Sprint-C3.1
> public API that lived here (``bootstrap_ci``, ``BootstrapConfig``,
> ``BootstrapResult``, ``CIMethod``, the percentile/basic/BCa CI methods and
> the jackknife pass) was removed: it had **zero production callers** — no
> consumer ever opted in ("Gate-Kopplung: keine direkte; Konsumenten opt-in"),
> ``BootstrapConfig`` had zero references anywhere, and the C6 "Migration auf
> BCa" never happened. The bootstrap statistics that actually feed the
> promotion pipeline live in ``scripts/performance_inference.py`` +
> ``scripts/build_family_metrics.py`` (ADR-0008 anchors the Brier CI there).
> Do NOT rebuild from the C3.1 roadmap section without first deciding why a
> second bootstrap stack should exist next to the wired one.

What remains is exactly what has a real caller: the two resampling
primitives ``governance/family_significance.py::block_bootstrap_pvalue``
imports (Politis-Romano stationary block bootstrap + the iid fallback).
Pure NumPy; determinism is the caller's job via the injected ``rng``.
"""
from __future__ import annotations

import numpy as np


def _iid_resample(arr: np.ndarray, B: int, rng: np.random.Generator) -> np.ndarray:
    n = arr.size
    idx = rng.integers(0, n, size=(B, n), dtype=np.int64)
    return arr[idx]


def _stationary_resample(
    arr: np.ndarray, B: int, mean_block_length: int, rng: np.random.Generator
) -> np.ndarray:
    """Politis-Romano stationary block bootstrap."""
    n = arr.size
    p = 1.0 / max(mean_block_length, 1)
    out = np.empty((B, n), dtype=arr.dtype)
    for b in range(B):
        starts = rng.integers(0, n, size=n, dtype=np.int64)
        breaks = rng.random(size=n) < p
        idx = np.empty(n, dtype=np.int64)
        cur = int(starts[0])
        for k in range(n):
            if k > 0 and breaks[k]:
                cur = int(starts[k])
            idx[k] = cur % n
            cur += 1
        out[b] = arr[idx]
    return out
