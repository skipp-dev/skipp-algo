"""Tests enforcing that SCHEMA_VERSION is the single source of truth
and that the semver utilities work correctly."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from smc_core.schema_version import SCHEMA_VERSION, is_compatible, parse_semver

_REPO_ROOT = Path(__file__).resolve().parents[1]


# --- semver parsing ---


def test_parse_semver_valid() -> None:
    assert parse_semver("1.1.0") == (1, 1, 0)
    assert parse_semver("0.0.1") == (0, 0, 1)
    assert parse_semver("42.7.13") == (42, 7, 13)


@pytest.mark.parametrize("bad", ["1.0", "1.0.0.0", "abc", "1.x.0", ""])
def test_parse_semver_rejects_invalid(bad: str) -> None:
    with pytest.raises(ValueError, match="Invalid semver"):
        parse_semver(bad)


# --- compatibility ---


def test_compatible_same_version() -> None:
    assert is_compatible("1.1.0", "1.1.0")


def test_compatible_producer_has_additive_fields() -> None:
    assert is_compatible("1.2.0", "1.1.0")


def test_incompatible_consumer_ahead_of_producer() -> None:
    assert not is_compatible("1.0.0", "1.1.0")


def test_incompatible_major_mismatch() -> None:
    assert not is_compatible("2.0.0", "1.1.0")


def test_compatible_patch_difference_ignored() -> None:
    assert is_compatible("1.1.5", "1.1.0")
    assert is_compatible("1.1.0", "1.1.5")


# --- canonical constant ---


def test_schema_version_is_valid_semver() -> None:
    major, minor, patch = parse_semver(SCHEMA_VERSION)
    assert major >= 1


def test_schema_version_importable_from_smc_core() -> None:
    mod = importlib.import_module("smc_core")
    assert hasattr(mod, "SCHEMA_VERSION")
    assert mod.SCHEMA_VERSION == SCHEMA_VERSION


# --- no duplicate definitions ---


_FILES_THAT_MUST_NOT_DEFINE_SCHEMA_VERSION = [
    "smc_integration/structure_batch.py",
    "smc_integration/batch.py",
    "scripts/export_smc_structure_artifact.py",
    "scripts/generate_smc_micro_profiles.py",
]


@pytest.mark.parametrize("rel_path", _FILES_THAT_MUST_NOT_DEFINE_SCHEMA_VERSION)
def test_no_local_schema_version_constant(rel_path: str) -> None:
    path = _REPO_ROOT / rel_path
    if not path.exists():
        pytest.skip(f"{rel_path} not found")
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        # Allow `from ... import SCHEMA_VERSION` but reject `SCHEMA_VERSION = "..."`
        if stripped.startswith("SCHEMA_VERSION") and "=" in stripped and "import" not in stripped:
            pytest.fail(f"{rel_path} defines its own SCHEMA_VERSION — must import from smc_core.schema_version")


# --- spec example stays in sync ---


def test_spec_example_uses_current_schema_version() -> None:
    example = _REPO_ROOT / "spec" / "examples" / "smc_snapshot_aapl_15m_normal.json"
    if not example.exists():
        pytest.skip("example not found")
    payload = json.loads(example.read_text(encoding="utf-8"))
    assert payload["schema_version"] == SCHEMA_VERSION, (
        f"spec example has schema_version={payload['schema_version']!r} but canonical is {SCHEMA_VERSION!r}"
    )
