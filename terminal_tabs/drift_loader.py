"""C8/T6 — Drift artifact loader for the Streamlit dashboard.

Resolves ``cache/live/drift_<YYYY-MM-DD>.json`` under the configured
cache dir, returning ``None`` if no artifact is present yet (Phase-A
not started).  Used by the Streamlit entry point to feed
:func:`terminal_tabs.tab_live_incubation.build_live_view`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

__all__ = [
    "DRIFT_FILENAME_PATTERN",
    "list_drift_dates",
    "load_drift_artifact",
    "resolve_drift_path",
]

# `drift_<YYYY-MM-DD>.json`
DRIFT_FILENAME_PATTERN = re.compile(r"^drift_(\d{4}-\d{2}-\d{2})\.json$")


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
    return data


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
    payload["variants"] = [
        v for v in variants if str(v.get("variant")) not in block
    ]
    return payload
