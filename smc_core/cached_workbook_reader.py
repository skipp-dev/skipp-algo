from __future__ import annotations

import functools
from pathlib import Path

import pandas as pd


@functools.lru_cache(maxsize=8)
def _read_daily_bars_cached(resolved_path: str, mtime_ns: int) -> pd.DataFrame:
    """Parse the ``daily_bars`` sheet once per (path, mtime).

    The ``mtime_ns`` component of the cache key guarantees the cache is
    invalidated whenever the underlying workbook changes on disk, so callers
    never observe stale bars. The returned frame is treated as immutable; use
    :func:`read_daily_bars` which hands out fresh copies.
    """
    return pd.read_excel(resolved_path, sheet_name="daily_bars")


def read_daily_bars(workbook: str | Path) -> pd.DataFrame:
    """Return the workbook's ``daily_bars`` sheet, memoized by path + mtime.

    The heavy ``pd.read_excel`` xlsx parse is shared across the many callers
    (structure-artifact export, structure batch, measurement evidence) that all
    read the same daily-only workbook repeatedly. A fresh ``.copy()`` is handed
    out on every call so downstream mutation cannot leak between callers and
    test isolation is preserved.
    """
    path = Path(workbook)
    frame = _read_daily_bars_cached(str(path.resolve()), path.stat().st_mtime_ns)
    return frame.copy()
