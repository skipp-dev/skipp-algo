"""Sprint C4.1 — null-distribution cache for the block permutation test.

Permutation tests are expensive for large ``B``; running the same
``(family, regime, dataset_fingerprint, block_size)`` configuration
multiple times in CI is wasteful. This cache persists null distributions
keyed by an opaque ``CacheKey`` to a Parquet-equivalent JSON shard
(parquet would pull a heavy dep; JSON keeps the cache human-readable).

The cache is intentionally additive — invalidation happens by changing
the ``dataset_fingerprint`` field, which the X3 run-manifest provides.
The key covers the fields that define the null *distribution* (family,
regime, dataset_fingerprint, n_perms, block_size, statistic_name). The RNG
``seed`` is deliberately EXCLUDED: two seeds draw different realized arrays
of the same distribution, treated as exchangeable, so a cache hit returns a
valid draw rather than the identical one. (``alternative`` is carried for
p-value tallying but does not change the null distribution.)

NOTE: this cache is a PREPARED component — it is not yet wired into
:func:`smc_core.inference.permutation.block_permutation_test`, which always
recomputes. Wire it at that callsite (or drop the module) before relying on
the CI speedup described above.

Roadmap: docs/IMPROVEMENTS_C2_C12_ROADMAP_2026-04-26.md#c41
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
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
        if not isinstance(payload, dict):
            return None
        if payload.get("key") != _key_to_dict(key):
            return None
        null_payload = payload.get("null")
        if null_payload is None:
            return None
        try:
            arr = np.asarray(null_payload, dtype=np.float64)
        except (TypeError, ValueError):
            return None
        if arr.size != key.n_perms:
            return None
        return arr

    def put(self, key: CacheKey, null: np.ndarray) -> None:
        path = self._shard_path(key)
        if null.size != key.n_perms:
            raise ValueError(
                f"null array length {null.size} does not match key.n_perms {key.n_perms}"
            )
        if not np.all(np.isfinite(null)):
            raise ValueError("null array contains non-finite values")
        payload = {"key": _key_to_dict(key), "null": null.tolist()}
        body = json.dumps(payload, sort_keys=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
        )
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(body)
                fh.flush()
                os.fsync(fh.fileno())
            tmp.replace(path)
        except Exception:
            if tmp.exists():
                with contextlib.suppress(OSError):
                    tmp.unlink()
            raise

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
