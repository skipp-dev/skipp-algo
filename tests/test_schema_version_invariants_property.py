"""Property tests for ``smc_core.schema_version`` semver helpers.

Pins the pure-math contract of the canonical schema-version registry
(H-6, system review 2026-04-24):

  * :func:`smc_core.schema_version.parse_semver`
  * :func:`smc_core.schema_version.is_compatible`
  * :func:`smc_core.schema_version.classify_version_change`
  * :func:`smc_core.schema_version.auto_commit_allowed`
  * :class:`smc_core.schema_version.VersionChangeType`

Existing tests cover canonical-constant alignment across downstream
modules (H-6). This file pins the actual semver math invariants —
parser rejection rules, MAJOR/MINOR/PATCH/UNCHANGED classification,
producer/consumer compatibility (`p.major == c.major and p.minor >=
c.minor`), and the governance gate (`auto_commit_allowed` blocks
MAJOR only).

Continues the PQ Re-Audit Tier-1 spillover series (#2350, #2363, #2366,
#2370, #2371, #2372, #2373, #2374, #2375, #2376, #2377, #2378, #2379,
#2380).
"""

from __future__ import annotations

import pytest

from smc_core.schema_version import (
    EVENT_LEDGER_SCHEMA_VERSION,
    SCHEMA_VERSION,
    SESSION_SCHEMA_VERSION,
    VersionChangeType,
    auto_commit_allowed,
    classify_version_change,
    is_compatible,
    parse_semver,
)

# ---------------------------------------------------------------------------
# Canonical constants
# ---------------------------------------------------------------------------


def test_schema_version_parses_as_semver() -> None:
    """The pinned `SCHEMA_VERSION` must itself be a valid semver triple."""
    major, minor, patch = parse_semver(SCHEMA_VERSION)
    assert isinstance(major, int) and isinstance(minor, int) and isinstance(patch, int)


def test_event_ledger_schema_version_is_string() -> None:
    assert isinstance(EVENT_LEDGER_SCHEMA_VERSION, str)
    assert EVENT_LEDGER_SCHEMA_VERSION != ""


def test_session_schema_version_uses_date_dot_n_format() -> None:
    """SESSION_SCHEMA_VERSION uses `YYYY-MM-DD.N` (deliberately distinct from semver)."""
    import re

    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}\.\d+", SESSION_SCHEMA_VERSION), (
        f"Expected `YYYY-MM-DD.N`, got {SESSION_SCHEMA_VERSION!r}"
    )


# ---------------------------------------------------------------------------
# VersionChangeType enum
# ---------------------------------------------------------------------------


def test_version_change_type_values() -> None:
    """StrEnum membership pinned: case-sensitive lowercase tokens."""
    assert VersionChangeType.UNCHANGED == "unchanged"
    assert VersionChangeType.PATCH == "patch"
    assert VersionChangeType.MINOR == "minor"
    assert VersionChangeType.MAJOR == "major"


def test_version_change_type_is_str_enum() -> None:
    """Every member is a real `str` (StrEnum) — round-trips through JSON."""
    for member in VersionChangeType:
        assert isinstance(member, str)


def test_version_change_type_membership_exhaustive() -> None:
    """Pin the membership set so additions are caught explicitly."""
    assert {m.value for m in VersionChangeType} == {"unchanged", "patch", "minor", "major"}


# ---------------------------------------------------------------------------
# parse_semver — valid inputs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0.0.0", (0, 0, 0)),
        ("1.0.0", (1, 0, 0)),
        ("3.0.0", (3, 0, 0)),
        ("1.2.3", (1, 2, 3)),
        ("10.20.30", (10, 20, 30)),
        ("999.999.999", (999, 999, 999)),
        ("0.0.1", (0, 0, 1)),
        ("0.1.0", (0, 1, 0)),
    ],
)
def test_parse_semver_valid(raw: str, expected: tuple[int, int, int]) -> None:
    assert parse_semver(raw) == expected


def test_parse_semver_returns_ints() -> None:
    """All three components are real ints (not str)."""
    result = parse_semver("1.2.3")
    assert all(isinstance(p, int) for p in result)


# ---------------------------------------------------------------------------
# parse_semver — invalid inputs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "",                # empty
        "1",               # 1 part
        "1.2",             # 2 parts
        "1.2.3.4",         # 4 parts
        "1.2.3-rc1",       # pre-release suffix (rejected)
        "v1.2.3",          # 'v' prefix
        "1.2.x",           # non-digit
        "a.b.c",           # all non-digit
        "1..2",            # empty middle part
        "1.2.",            # empty trailing part
        ".1.2",            # empty leading part
        "1.2.3 ",          # trailing whitespace
        " 1.2.3",          # leading whitespace
        "-1.2.3",          # negative (no `-` allowed; isdigit rejects)
        "1.2.+3",
        "1_2_3",
    ],
)
def test_parse_semver_rejects_invalid(bad: str) -> None:
    with pytest.raises(ValueError, match="Invalid semver"):
        parse_semver(bad)


# ---------------------------------------------------------------------------
# is_compatible — producer/consumer rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("producer", "consumer", "expected"),
    [
        # Same triple → compatible.
        ("1.2.3", "1.2.3", True),
        # Producer minor > consumer minor → compatible (additive fields).
        ("1.3.0", "1.2.0", True),
        ("1.9.0", "1.0.0", True),
        # Producer minor == consumer minor with any patch → compatible.
        ("1.2.0", "1.2.5", True),
        ("1.2.5", "1.2.0", True),
        # Producer minor < consumer minor → NOT compatible (missing fields).
        ("1.2.0", "1.3.0", False),
        ("1.0.0", "1.9.0", False),
        # Cross-major → NEVER compatible (in either direction).
        ("1.0.0", "2.0.0", False),
        ("2.0.0", "1.0.0", False),
        ("3.5.0", "2.5.0", False),
        ("2.5.0", "3.5.0", False),
    ],
)
def test_is_compatible_table(producer: str, consumer: str, expected: bool) -> None:
    assert is_compatible(producer, consumer) is expected


def test_is_compatible_ignores_patch_component() -> None:
    """Patch differences never affect compatibility (within same major.minor)."""
    for p in ("1.2.0", "1.2.1", "1.2.99"):
        for c in ("1.2.0", "1.2.5", "1.2.99"):
            assert is_compatible(p, c) is True


def test_is_compatible_reflexive() -> None:
    """Any valid version is compatible with itself."""
    for v in ("0.0.0", "1.0.0", "1.2.3", "10.20.30"):
        assert is_compatible(v, v) is True


def test_is_compatible_invalid_input_raises() -> None:
    with pytest.raises(ValueError, match="Invalid semver"):
        is_compatible("bad", "1.0.0")
    with pytest.raises(ValueError, match="Invalid semver"):
        is_compatible("1.0.0", "bad")


# ---------------------------------------------------------------------------
# classify_version_change — transition table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        # UNCHANGED — identical triple.
        ("1.2.3", "1.2.3", VersionChangeType.UNCHANGED),
        ("0.0.0", "0.0.0", VersionChangeType.UNCHANGED),
        # PATCH — same major + minor, different patch (both directions).
        ("1.2.3", "1.2.4", VersionChangeType.PATCH),
        ("1.2.5", "1.2.0", VersionChangeType.PATCH),  # downgrade still classifies
        # MINOR — same major, different minor.
        ("1.2.0", "1.3.0", VersionChangeType.MINOR),
        ("1.3.5", "1.2.9", VersionChangeType.MINOR),  # downgrade still classifies
        ("1.0.0", "1.1.0", VersionChangeType.MINOR),
        # MAJOR — different major (patch/minor differences are irrelevant).
        ("1.0.0", "2.0.0", VersionChangeType.MAJOR),
        ("2.0.0", "1.0.0", VersionChangeType.MAJOR),
        ("1.5.3", "2.0.0", VersionChangeType.MAJOR),
        ("3.0.0", "2.9.9", VersionChangeType.MAJOR),
    ],
)
def test_classify_version_change_table(
    old: str, new: str, expected: VersionChangeType
) -> None:
    assert classify_version_change(old, new) == expected


def test_classify_version_change_symmetric_classification() -> None:
    """The *kind* of change is symmetric: classify(a,b) == classify(b,a)."""
    pairs = [
        ("1.2.3", "1.2.4"),  # PATCH
        ("1.2.0", "1.3.0"),  # MINOR
        ("1.0.0", "2.0.0"),  # MAJOR
        ("1.2.3", "1.2.3"),  # UNCHANGED
    ]
    for a, b in pairs:
        assert classify_version_change(a, b) == classify_version_change(b, a)


def test_classify_version_change_major_takes_precedence_over_minor_patch_change() -> None:
    """A simultaneous major+minor+patch change is classified MAJOR."""
    assert classify_version_change("1.2.3", "2.5.7") == VersionChangeType.MAJOR


def test_classify_version_change_minor_takes_precedence_over_patch_change() -> None:
    """Same major, different minor+patch is classified MINOR (not PATCH)."""
    assert classify_version_change("1.2.3", "1.3.7") == VersionChangeType.MINOR


def test_classify_version_change_invalid_input_raises() -> None:
    with pytest.raises(ValueError, match="Invalid semver"):
        classify_version_change("bad", "1.0.0")
    with pytest.raises(ValueError, match="Invalid semver"):
        classify_version_change("1.0.0", "bad")


# ---------------------------------------------------------------------------
# auto_commit_allowed — governance gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change_type", "expected"),
    [
        (VersionChangeType.UNCHANGED, True),
        (VersionChangeType.PATCH, True),
        (VersionChangeType.MINOR, True),
        (VersionChangeType.MAJOR, False),
    ],
)
def test_auto_commit_allowed_table(
    change_type: VersionChangeType, expected: bool
) -> None:
    assert auto_commit_allowed(change_type) is expected


def test_auto_commit_allowed_blocks_only_major() -> None:
    """Inverse phrasing: the gate blocks MAJOR and nothing else."""
    blocked = {ct for ct in VersionChangeType if not auto_commit_allowed(ct)}
    assert blocked == {VersionChangeType.MAJOR}


# ---------------------------------------------------------------------------
# End-to-end: classify → auto_commit gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("old", "new", "expected_allowed"),
    [
        ("1.2.3", "1.2.3", True),   # UNCHANGED → allowed
        ("1.2.3", "1.2.4", True),   # PATCH → allowed
        ("1.2.0", "1.3.0", True),   # MINOR → allowed
        ("1.0.0", "2.0.0", False),  # MAJOR → blocked
        ("2.9.9", "3.0.0", False),  # MAJOR → blocked
    ],
)
def test_pipeline_classify_then_gate(
    old: str, new: str, expected_allowed: bool
) -> None:
    assert auto_commit_allowed(classify_version_change(old, new)) is expected_allowed
