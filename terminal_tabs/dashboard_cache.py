"""C7/T7 — Performance-cache helpers for the dashboard.

Provides a tiny TTL-keyed memoization layer used by the Streamlit
tabs to wrap :func:`scripts.build_dashboard_payload.build_dashboard_payload`
and the per-file JSON loaders.  Streamlit's own ``@st.cache_data``
decorator is not applied here so the helper stays test-friendly in a
non-Streamlit environment; the Streamlit entry point composes both
layers when it imports this module.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from threading import RLock
from typing import Any, TypeVar

__all__ = [
    "DEFAULT_TTL_SECONDS",
    "TTLCache",
    "load_json_cached",
    "payload_cache_key",
]

T = TypeVar("T")

# Aligned with the Streamlit cache TTL recommendation in the C7 sprint
# plan (5 minutes — JSON files are nightly artefacts).
DEFAULT_TTL_SECONDS = 300


class TTLCache:
    """Tiny thread-safe TTL cache used by the dashboard helpers.

    Provides ``get_or_compute(key, factory)`` so the first caller pays
    the cost of the underlying computation while concurrent dashboard
    sessions reuse the result for ``ttl`` seconds.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._ttl = float(ttl_seconds)
        self._clock = clock
        self._store: dict[Any, tuple[float, Any]] = {}
        self._lock = RLock()

    def get_or_compute(self, key: Any, factory: Callable[[], T]) -> T:
        now = self._clock()
        with self._lock:
            entry = self._store.get(key)
            if entry is not None and (now - entry[0]) < self._ttl:
                return entry[1]
        value = factory()
        with self._lock:
            self._store[key] = (self._clock(), value)
        return value

    def invalidate(self, key: Any | None = None) -> None:
        with self._lock:
            if key is None:
                self._store.clear()
            else:
                self._store.pop(key, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


def payload_cache_key(
    cache_dir: Path | str,
    *,
    as_of_date: str | None = None,
) -> tuple[str, str | None]:
    """Stable cache key for a dashboard payload load.

    The key is intentionally a plain tuple of strings so it is
    hashable and ``repr``-friendly in the Streamlit cache panel.
    """
    return (str(Path(cache_dir).resolve()), as_of_date)


def load_json_cached(
    path: Path | str,
    *,
    cache: TTLCache,
) -> dict[str, Any] | None:
    """Read JSON file via the cache, returning ``None`` on missing file.

    The cache key includes the file's ``mtime`` so a freshly-written
    artefact is picked up on the next read instead of being shadowed
    by the previous cached value.
    """
    p = Path(path)
    if not p.exists():
        return None
    key = (str(p.resolve()), p.stat().st_mtime_ns)

    def _load() -> dict[str, Any] | None:
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    return cache.get_or_compute(key, _load)
