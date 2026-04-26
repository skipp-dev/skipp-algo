"""Sprint C4.1 — null-distribution cache for the block permutation test.

Permutation tests are expensive for large ``B``; running the same
``(family, regime, dataset_fingerprint, block_size)`` configuration
multiple times in CI is wasteful. This cache persists null distributions
keyed by an opaque ``CacheKey`` to a Parquet-equivalent JSON shard
(parquet would pull a heavy dep; JSON keeps the cache human-readable).

The cache is intentionally additive — invalidation happens by changing
the ``dataset_fingerprint`` field, which the X3 run-manifest provides.
Stale entries do no harm because the cache key includes everything that
could change the null distribution.

Roadmap: docs/IMPROVEMENTS_C2_C12_ROADMAP_2026-04-26.md#c41
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class CacheKey:
    family: str
    regime: str
    dataset_fingerprint: str
    n_perms: int
    block_size: int
    statistic_name: str
    alternative: str = "two-sided"

    def hash_id(self) -> str:
        raw = json.dumps(self.__dict__, sort_keys=True).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]


class NullCache:
    """JSON-backed cache for permutation null distributions.

    Storage layout::

        cache_dir/
            <hash_id>.json    # {"key": {...}, "null": [...]}

    Read/write are atomic via a temporary-file rename; concurrent readers
    will only ever see a fully-written shard.
    """

    def __init__(self, cache_dir: Path | str) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _shard_path(self, key: CacheKey) -> Path:
        return self.cache_dir / f"{key.hash_id()}.json"

    def get(self, key: CacheKey) -> np.ndarray | None:
        path = self._shard_path(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if payload.get("key") != _key_to_dict(key):
            return None
        return np.asarray(payload["null"], dtype=np.float64)

    def put(self, key: CacheKey, null: np.ndarray) -> None:
        path = self._shard_path(key)
        tmp = path.with_suffix(".json.tmp")
        payload = {"key": _key_to_dict(key), "null": null.tolist()}
        tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        tmp.replace(path)

    def __len__(self) -> int:
        return sum(1 for _ in self.cache_dir.glob("*.json"))


def _key_to_dict(key: CacheKey) -> dict[str, object]:
    return {
        "family": key.family,
        "regime": key.regime,
        "dataset_fingerprint": key.dataset_fingerprint,
        "n_perms": key.n_perms,
        "block_size": key.block_size,
        "statistic_name": key.statistic_name,
        "alternative": key.alternative,
    }


__all__ = ["CacheKey", "NullCache"]
