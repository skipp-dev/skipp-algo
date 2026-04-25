"""Canonical schema version for all SMC artifacts, snapshots, and manifests.

Versioning policy (semver):
- PATCH (x.y.Z): internal-only changes (docs, comments, refactors) — no payload change
- MINOR (x.Y.z): additive, backwards-compatible field additions — consumers can ignore new fields
- MAJOR (X.y.z): breaking changes that require consumer updates

Bump instructions: see docs/schema_versioning.md
"""

from __future__ import annotations

from enum import Enum

# Current pin: 3.0.0 (2026-04-23). Pine-library export field count 200 → 201
# (adds ZONE_CAL_TRUST + ZONE_CAL_CONFIDENCE for Phase-H consumer maturity,
# PR #19 + ADR 2026-04-22). The governance gate in
# scripts/smc_version_governance.py escalates *any* field-count change to
# MAJOR — see CHANGELOG.md "Schema Versions" section for the full bump
# history (1.0.0 → 1.1.0 → 1.2.0 → 2.0.0 → 2.1.0 [superseded] → 3.0.0).
SCHEMA_VERSION = "3.0.0"


# ---------------------------------------------------------------------------
# Sub-artifact schema versions (H-6, system review 2026-04-24).
# Single source of truth for downstream-persisted schemas. Each entry
# tracks a separate artifact family with its own evolution cadence:
#
#   * EVENT_LEDGER_SCHEMA_VERSION — JSONL records emitted by
#     :mod:`smc_core.event_ledger`. Bumped on field add/remove.
#   * SESSION_SCHEMA_VERSION — Streamlit-app derived-state cache key
#     (``streamlit_terminal`` + ``databento_volatility_screener``).
#     Date-suffix scheme (``YYYY-MM-DD.N``) intentionally distinct
#     from semver because it busts in-memory derived caches, not a
#     persisted on-disk schema.
# ---------------------------------------------------------------------------
EVENT_LEDGER_SCHEMA_VERSION = "1.0"
SESSION_SCHEMA_VERSION = "2026-04-24.0"


class VersionChangeType(str, Enum):
    """Classification of a semver transition."""

    UNCHANGED = "unchanged"
    PATCH = "patch"
    MINOR = "minor"
    MAJOR = "major"


def parse_semver(version: str) -> tuple[int, int, int]:
    """Return (major, minor, patch) from a semver string."""
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError(f"Invalid semver: {version!r}")
    return int(parts[0]), int(parts[1]), int(parts[2])


def is_compatible(producer: str, consumer: str) -> bool:
    """True when the *producer* version is readable by a *consumer*.

    Rule: same major, and producer minor >= consumer minor.
    A producer at 1.3.0 can feed a consumer expecting 1.2.0 (additive fields are ignored).
    A consumer at 1.3.0 can NOT read a producer at 1.2.0 (missing expected fields).
    """
    p = parse_semver(producer)
    c = parse_semver(consumer)
    return p[0] == c[0] and p[1] >= c[1]


def classify_version_change(
    old_version: str, new_version: str,
) -> VersionChangeType:
    """Classify a semver transition as unchanged / patch / minor / major.

    Rules:
    - Same triple → UNCHANGED
    - Same major + minor, different patch → PATCH
    - Same major, different minor → MINOR
    - Different major → MAJOR
    """
    old = parse_semver(old_version)
    new = parse_semver(new_version)
    if old == new:
        return VersionChangeType.UNCHANGED
    if old[0] != new[0]:
        return VersionChangeType.MAJOR
    if old[1] != new[1]:
        return VersionChangeType.MINOR
    return VersionChangeType.PATCH


def auto_commit_allowed(change_type: VersionChangeType) -> bool:
    """Whether the automation path may auto-commit for this change type.

    - UNCHANGED / PATCH / MINOR → allowed (additive, backward-compatible)
    - MAJOR → blocked (requires PR or explicit operator review)
    """
    return change_type in (
        VersionChangeType.UNCHANGED,
        VersionChangeType.PATCH,
        VersionChangeType.MINOR,
    )
