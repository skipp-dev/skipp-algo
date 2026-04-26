"""Microstructure features (Bid-Ask Imbalance, Volume Imbalance, VPIN)."""
from __future__ import annotations

from typing import Sequence

import numpy as np


def bid_ask_imbalance(bid_size: Sequence[float], ask_size: Sequence[float]) -> np.ndarray:
    """(bid - ask) / (bid + ask) per bar; 0 when both sides empty."""
    b = np.asarray(bid_size, dtype=float)
    a = np.asarray(ask_size, dtype=float)
    if b.shape != a.shape:
        raise ValueError("bid_size and ask_size must align")
    denom = b + a
    out = np.zeros_like(b)
    mask = denom > 0
    out[mask] = (b[mask] - a[mask]) / denom[mask]
    return out


def volume_imbalance(buy_volume: Sequence[float], sell_volume: Sequence[float]) -> np.ndarray:
    return bid_ask_imbalance(buy_volume, sell_volume)


def vpin(
    buy_volume: Sequence[float],
    sell_volume: Sequence[float],
    bucket_size: int = 50,
) -> np.ndarray:
    """Volume-Synchronised Probability of Informed Trading approximation
    (Easley-López de Prado-O'Hara 2012). Bucketed mean of |buy - sell| / total.
    Output length: ``ceil(n / bucket_size)``.
    """
    bv = np.asarray(buy_volume, dtype=float)
    sv = np.asarray(sell_volume, dtype=float)
    if bv.shape != sv.shape:
        raise ValueError("buy_volume and sell_volume must align")
    if bucket_size <= 0:
        raise ValueError("bucket_size must be positive")
    n = bv.size
    n_buckets = (n + bucket_size - 1) // bucket_size
    out = np.zeros(n_buckets, dtype=float)
    for k in range(n_buckets):
        lo, hi = k * bucket_size, min(n, (k + 1) * bucket_size)
        b_sum = float(bv[lo:hi].sum())
        s_sum = float(sv[lo:hi].sum())
        total = b_sum + s_sum
        out[k] = abs(b_sum - s_sum) / total if total > 0 else 0.0
    return out


__all__ = ["bid_ask_imbalance", "volume_imbalance", "vpin"]
