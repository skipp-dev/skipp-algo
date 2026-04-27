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
    "DRIFT_SCHEMA_MIN_COMPATIBLE",
    "DRIFT_SCHEMA_MAX_COMPATIBLE_MAJOR",
    "DriftSchemaError",
    "list_drift_dates",
    "load_drift_artifact",
    "resolve_drift_path",
]

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
