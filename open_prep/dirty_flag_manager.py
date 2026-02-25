"""Pipeline dirty-flag manager for open_prep scoring.

Ported from IB_MON's dirty_flag_manager — avoids re-scoring symbols whose
input data has not changed between consecutive pipeline runs.

The manager keeps a lightweight fingerprint (hash) of the scoring-relevant
fields for each symbol.  On a subsequent run, symbols with unchanged
fingerprints can skip the full ``score_candidate()`` call and reuse the
previous result, dramatically reducing CPU cost for periodic re-runs where
only a handful of symbols change each cycle.

Usage::

    from open_prep.dirty_flag_manager import PipelineDirtyManager

    dirty_mgr = PipelineDirtyManager()

    for fr in passed_candidates:
        fp = dirty_mgr.fingerprint(fr.symbol, fr.features)
        if dirty_mgr.is_clean(fr.symbol, fp):
            scored.append(dirty_mgr.get_cached(fr.symbol))
        else:
            row = score_candidate(fr, bias, weights)
            dirty_mgr.update(fr.symbol, fp, row)
            scored.append(row)
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Fields that affect the score — if any of these change, re-score is needed.
_SCORE_RELEVANT_KEYS: tuple[str, ...] = (
    "price",
    "gap_pct",
    "gap_pct_for_scoring",
    "rel_vol",
    "rel_vol_capped",
    "momentum_z",
    "atr",
    "atr_pct",
    "ext_hours_score",
    "news_score",
    "analyst_catalyst_score",
    "corporate_action_penalty",
    "earnings_bmo",
    "is_hvb",
    "vwap_distance_pct",
    "freshness_decay",
    "institutional_quality",
    "estimate_revision_score",
    "sector_relative_gap",
    "spread_pct",
)


def _make_fingerprint(features: dict[str, Any]) -> str:
    """Create a deterministic hash from score-relevant feature values."""
    # Extract only relevant keys, round floats to avoid floating-point jitter
    parts: list[str] = []
    for key in _SCORE_RELEVANT_KEYS:
        val = features.get(key)
        if isinstance(val, float):
            parts.append(f"{key}={val:.6f}")
        elif val is not None:
            parts.append(f"{key}={val}")
        else:
            parts.append(f"{key}=None")
    raw = "|".join(parts)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


class PipelineDirtyManager:
    """Track per-symbol data fingerprints to skip redundant scoring."""

    def __init__(self) -> None:
        self._fingerprints: dict[str, str] = {}
        self._cache: dict[str, dict[str, Any]] = {}
        self._stats = {"hits": 0, "misses": 0}

    def fingerprint(self, symbol: str, features: dict[str, Any]) -> str:
        """Compute a fingerprint for the given features dict."""
        return _make_fingerprint(features)

    def is_clean(self, symbol: str, fp: str) -> bool:
        """Return True if *symbol*'s fingerprint matches the cached one."""
        return (
            symbol in self._fingerprints
            and self._fingerprints[symbol] == fp
            and symbol in self._cache
        )

    def get_cached(self, symbol: str) -> dict[str, Any]:
        """Return the previously cached score result for *symbol*.

        Caller must verify ``is_clean()`` first.
        """
        self._stats["hits"] += 1
        return self._cache[symbol]

    def update(self, symbol: str, fp: str, result: dict[str, Any]) -> None:
        """Store the scoring result and fingerprint for *symbol*."""
        self._stats["misses"] += 1
        self._fingerprints[symbol] = fp
        self._cache[symbol] = result

    def invalidate(self, symbol: str) -> None:
        """Force re-scoring of *symbol* on the next cycle."""
        self._fingerprints.pop(symbol, None)
        self._cache.pop(symbol, None)

    def clear(self) -> None:
        """Flush all cached fingerprints and results."""
        self._fingerprints.clear()
        self._cache.clear()
        self._stats = {"hits": 0, "misses": 0}

    @property
    def stats(self) -> dict[str, int]:
        """Return cache hit/miss statistics."""
        return dict(self._stats)

    def log_stats(self) -> None:
        """Log a summary of cache usage."""
        total = self._stats["hits"] + self._stats["misses"]
        if total > 0:
            hit_rate = 100.0 * self._stats["hits"] / total
            logger.info(
                "DirtyFlagManager: %d/%d cache hits (%.1f%%), %d re-scored",
                self._stats["hits"],
                total,
                hit_rate,
                self._stats["misses"],
            )
