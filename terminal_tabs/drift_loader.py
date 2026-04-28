"""C8/T6 — Drift artifact loader for the Streamlit dashboard.

Resolves ``cache/live/drift_<YYYY-MM-DD>.json`` under the configured
cache dir, returning ``None`` if no artifact is present yet (Phase-A
not started).  Used by the Streamlit entry point to feed
:func:`terminal_tabs.tab_live_incubation.build_live_view`.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterable
from pathlib import Path
from threading import RLock
from typing import Any

__all__ = [
    "DRIFT_FILENAME_PATTERN",
    "DRIFT_HISTORY_DEFAULT_N",
    "DRIFT_RECENT_CACHE_TTL_SECONDS",
    "DRIFT_SCHEMA_MAX_COMPATIBLE_MAJOR",
    "DRIFT_SCHEMA_MIN_COMPATIBLE",
    "DriftSchemaError",
    "invalidate_recent_drift_cache",
    "list_drift_dates",
    "load_drift_artifact",
    "load_recent_drift_artifacts",
    "resolve_drift_path",
]

# C13/T2 — history-window default for the Streamlit dashboard.
# The plan calls for "die letzten 7 Drift-Reports"; the loader exposes
# the constant so the dashboard, tests, and CI all agree on the cap.
DRIFT_HISTORY_DEFAULT_N = 7

# `drift_<YYYY-MM-DD>.json`
DRIFT_FILENAME_PATTERN = re.compile(r"^drift_(\d{4}-\d{2}-\d{2})\.json$")

# Drift-artifact schema compatibility window (Deep-Review C8 MAJOR finding
# 2026-04-27). The producer in ``scripts/compute_live_drift.py`` emits
# ``schema_version`` at the top level. We accept any version whose MAJOR
# matches ``DRIFT_SCHEMA_MAX_COMPATIBLE_MAJOR`` and whose full semver is
# >= ``DRIFT_SCHEMA_MIN_COMPATIBLE`` (additive-MINOR is OK). A MAJOR bump
# requires an explicit consumer update — refuse-load is the safer default
# than silent ``KeyError`` downstream.
DRIFT_SCHEMA_MIN_COMPATIBLE = "1.0.0"
DRIFT_SCHEMA_MAX_COMPATIBLE_MAJOR = 1


class DriftSchemaError(ValueError):
    """Raised when a drift artifact carries an incompatible schema version."""


def _parse_semver(version: str) -> tuple[int, int, int] | None:
    parts = version.split(".")
    if len(parts) != 3:
        return None
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


def _check_drift_schema_version(payload: dict[str, Any]) -> None:
    """Validate the artifact's ``schema_version`` against the consumer window.

    Missing field → accepted as legacy ``"1.0.0"`` (pre-bump artifacts on
    disk during the rollout period). Unparseable version → DriftSchemaError.
    Out-of-window MAJOR → DriftSchemaError. MINOR ahead → accepted (additive).
    """
    raw = payload.get("schema_version")
    if raw is None:
        # Pre-bump artifact: assume baseline, do not refuse.
        return
    if not isinstance(raw, str):
        raise DriftSchemaError(
            f"schema_version must be a semver string, got {type(raw).__name__}",
        )
    parsed = _parse_semver(raw)
    if parsed is None:
        raise DriftSchemaError(
            f"schema_version {raw!r} is not a valid 3-part semver",
        )
    minimum = _parse_semver(DRIFT_SCHEMA_MIN_COMPATIBLE)
    if minimum is None:
        # Constant; covered by tests. Defensive raise instead of
        # ``assert`` so the no-prod-assert pin stays green under
        # ``python -O`` (Deep-Review 2026-04-27).
        raise DriftSchemaError(
            f"DRIFT_SCHEMA_MIN_COMPATIBLE={DRIFT_SCHEMA_MIN_COMPATIBLE!r} is not a valid semver",
        )
    if parsed[0] != DRIFT_SCHEMA_MAX_COMPATIBLE_MAJOR:
        raise DriftSchemaError(
            f"drift artifact schema_version {raw!r} has incompatible MAJOR; "
            f"consumer expects MAJOR={DRIFT_SCHEMA_MAX_COMPATIBLE_MAJOR}",
        )
    if parsed < minimum:
        raise DriftSchemaError(
            f"drift artifact schema_version {raw!r} is below the minimum "
            f"compatible version {DRIFT_SCHEMA_MIN_COMPATIBLE}",
        )


def _live_dir(cache_dir: Path | str) -> Path:
    return Path(cache_dir) / "live"


def list_drift_dates(cache_dir: Path | str) -> list[str]:
    """Return all ``YYYY-MM-DD`` dates with a drift artifact, sorted ASC."""
    live = _live_dir(cache_dir)
    if not live.is_dir():
        return []
    dates: list[str] = []
    for entry in live.iterdir():
        if not entry.is_file():
            continue
        m = DRIFT_FILENAME_PATTERN.match(entry.name)
        if m is not None:
            dates.append(m.group(1))
    return sorted(dates)


def resolve_drift_path(
    cache_dir: Path | str,
    *,
    as_of_date: str | None = None,
) -> Path | None:
    """Pick the drift artifact for ``as_of_date`` or the newest one.

    Returns ``None`` when no artifact exists.
    """
    if as_of_date is not None:
        candidate = _live_dir(cache_dir) / f"drift_{as_of_date}.json"
        return candidate if candidate.exists() else None

    dates = list_drift_dates(cache_dir)
    if not dates:
        return None
    return _live_dir(cache_dir) / f"drift_{dates[-1]}.json"


def load_drift_artifact(
    cache_dir: Path | str,
    *,
    as_of_date: str | None = None,
) -> dict[str, Any] | None:
    """Load a drift artifact JSON.  Returns ``None`` on absent / invalid file.

    The schema is the one emitted by
    :func:`scripts.compute_live_drift.compute_live_drift` (C8/T4).
    """
    path = resolve_drift_path(cache_dir, as_of_date=as_of_date)
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    # Schema-version range check (Deep-Review C8 fix 2026-04-27).
    # Incompatible MAJOR → refuse to load so the dashboard renders a
    # clear "no data" panel rather than a downstream KeyError.
    try:
        _check_drift_schema_version(data)
    except DriftSchemaError:
        return None
    return data


# ---------------------------------------------------------------------------
# Recent-window TTL cache
# ---------------------------------------------------------------------------
# Process-local TTL cache for :func:`load_recent_drift_artifacts`. The
# function is called on every dashboard render (Streamlit reruns the
# script per interaction); reading + parsing N JSON artifacts on every
# rerun is wasteful, so we memoize the result for a short window.
#
# The cache key includes a fingerprint of the ``cache/live/`` directory
# (mtime + entry count) so a freshly-written artifact bypasses stale
# entries automatically — callers don't need to remember to invalidate.
# Tests can call :func:`invalidate_recent_drift_cache` to reset state.

# 60 seconds is short enough that a manual reload picks up new files
# even when the directory mtime is unchanged (e.g. atomic rename in
# place), and long enough to absorb tab-switching bursts.
DRIFT_RECENT_CACHE_TTL_SECONDS = 60.0

_RECENT_CACHE_LOCK = RLock()
_RECENT_CACHE: dict[
    tuple[str, int, int, float],
    tuple[float, list[dict[str, Any]]],
] = {}


def _live_dir_fingerprint(cache_dir: Path | str) -> tuple[int, float]:
    """Cheap fingerprint of ``cache/live/`` for cache-key construction.

    Returns ``(entry_count, mtime_ns)``. Both fields change when the
    producer writes a new ``drift_<date>.json``, so the cache key
    rotates without us having to scan the file list.
    """
    live = _live_dir(cache_dir)
    try:
        st = live.stat()
    except (OSError, FileNotFoundError):
        return (0, 0.0)
    try:
        count = sum(1 for _ in live.iterdir())
    except OSError:
        count = 0
    return (count, float(st.st_mtime_ns))


def _recent_cache_key(
    cache_dir: Path | str,
    n: int,
) -> tuple[str, int, int, float]:
    count, mtime_ns = _live_dir_fingerprint(cache_dir)
    return (str(Path(cache_dir).resolve()), int(n), count, mtime_ns)


def _recent_cache_get(
    key: tuple[str, int, int, float],
) -> list[dict[str, Any]] | None:
    now = time.monotonic()
    with _RECENT_CACHE_LOCK:
        entry = _RECENT_CACHE.get(key)
        if entry is None:
            return None
        ts, value = entry
        if (now - ts) >= DRIFT_RECENT_CACHE_TTL_SECONDS:
            _RECENT_CACHE.pop(key, None)
            return None
        return value


def _recent_cache_put(
    key: tuple[str, int, int, float],
    value: list[dict[str, Any]],
) -> None:
    with _RECENT_CACHE_LOCK:
        _RECENT_CACHE[key] = (time.monotonic(), value)


def invalidate_recent_drift_cache() -> None:
    """Clear the :func:`load_recent_drift_artifacts` TTL cache.

    Mostly useful in tests and from REPL sessions where the directory
    fingerprint cannot be relied on (e.g. fake clocks, in-memory file
    systems). Production code should not need this.
    """
    with _RECENT_CACHE_LOCK:
        _RECENT_CACHE.clear()


def load_recent_drift_artifacts(
    cache_dir: Path | str,
    *,
    n: int = DRIFT_HISTORY_DEFAULT_N,
) -> list[dict[str, Any]]:
    """Return up to ``n`` newest drift artifacts as a list, newest-first.

    C13/T2 — backs the dashboard's "letzten 7 Drift-Reports" panel and
    any external consumer that needs a rolling window. Each item is the
    parsed JSON dict augmented with an ``as_of_date`` key so the caller
    can render history without re-parsing the filename.

    Artifacts that fail to load (missing/corrupt/incompatible schema)
    are silently skipped — the dashboard already renders a "no data"
    panel for absent days, and a single bad file must not break the
    rest of the window.

    Results are memoized in a process-local TTL cache (see
    :data:`DRIFT_RECENT_CACHE_TTL_SECONDS`). The cache key includes a
    ``cache/live/`` directory fingerprint (mtime + entry count), so a
    freshly-written drift artifact bypasses stale entries automatically;
    callers that need to force a refresh can call
    :func:`invalidate_recent_drift_cache`.
    """
    if n < 0:
        raise ValueError(f"n must be non-negative, got {n}")
    if n == 0:
        return []
    key = _recent_cache_key(cache_dir, n)
    cached = _recent_cache_get(key)
    if cached is not None:
        # Defensive shallow-copy so callers that mutate the list (e.g.
        # truncation in a panel) don't corrupt the cached value.
        return list(cached)
    out = _load_recent_drift_artifacts_uncached(cache_dir, n=n)
    _recent_cache_put(key, out)
    return list(out)


def _load_recent_drift_artifacts_uncached(
    cache_dir: Path | str,
    *,
    n: int,
) -> list[dict[str, Any]]:
    dates = list_drift_dates(cache_dir)
    if not dates:
        return []
    out: list[dict[str, Any]] = []
    for date_str in reversed(dates):  # newest-first
        payload = load_drift_artifact(cache_dir, as_of_date=date_str)
        if payload is None:
            continue
        # Don't mutate the cached dict; layer a shallow copy with the date.
        item = dict(payload)
        item["as_of_date"] = date_str
        out.append(item)
        if len(out) >= n:
            break
    return out


def _filter_excluded_variants(
    payload: dict[str, Any] | None,
    *,
    excluded: Iterable[str] | None,
) -> dict[str, Any] | None:
    """Helper for the Streamlit entry: optionally drop blocklisted variants."""
    if payload is None or not excluded:
        return payload
    block = {str(v) for v in excluded}
    variants = payload.get("variants") or []
    if not isinstance(variants, list):
        return payload
    payload = dict(payload)
    payload["variants"] = [v for v in variants if str(v.get("variant")) not in block]
    return payload
