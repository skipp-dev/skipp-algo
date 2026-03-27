"""Canonical schema version for all SMC artifacts, snapshots, and manifests.

Versioning policy (semver):
- PATCH (x.y.Z): internal-only changes (docs, comments, refactors) — no payload change
- MINOR (x.Y.z): additive, backwards-compatible field additions — consumers can ignore new fields
- MAJOR (X.y.z): breaking changes that require consumer updates

Bump instructions: see docs/schema_versioning.md
"""

from __future__ import annotations

SCHEMA_VERSION = "1.2.0"


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
