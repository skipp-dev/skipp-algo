"""Tests for ``scripts.sync_tradingview_libraries`` (bug-hunt round 3).

Covers the two review findings:

* ``validate_imports`` only scanned the repo root (``glob("*.pine")``) and
  missed every Pine file under ``pine/**`` and ``SMC++/``. It now scans
  recursively while skipping hidden directories and ``node_modules``.
* ``sync_library`` treated the (intentionally) fetch-less
  ``fetch_library_source`` as a hard error on every run. It now validates
  the already-fetched local copy instead (fetching is delegated to
  ``scripts/tv_fetch_smc_libraries.ts``).
"""

from __future__ import annotations

import logging
from pathlib import Path

from scripts.sync_tradingview_libraries import (
    TRADINGVIEW_LIBRARIES,
    sync_library,
    validate_imports,
)

VALID_LIB = "smc_profile_engine"
VALID_LIB_PATH = TRADINGVIEW_LIBRARIES[VALID_LIB]["local_path"]


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _lib_source(name: str) -> str:
    return f'library("{name}")\n'


def test_validate_imports_scans_nested_directories(tmp_path: Path, monkeypatch) -> None:
    """A missing import target in pine/** must now fail validation."""
    monkeypatch.chdir(tmp_path)
    _write(
        tmp_path,
        "pine/generated/consumer.pine",
        f"import preuss_steffen/{VALID_LIB}/1 as pe\n",
    )
    # Local copy of the imported library is missing -> error.
    assert validate_imports() is False


def test_validate_imports_passes_when_local_library_exists(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write(
        tmp_path,
        "pine/generated/consumer.pine",
        f"import preuss_steffen/{VALID_LIB}/1 as pe\n",
    )
    _write(tmp_path, VALID_LIB_PATH, _lib_source(VALID_LIB))
    assert validate_imports() is True


def test_validate_imports_skips_hidden_and_node_modules(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    # Broken imports in ignored directories must not fail validation.
    _write(tmp_path, "node_modules/dep/broken.pine", "import not-a-path as x\n")
    _write(tmp_path, ".hidden/broken.pine", "import also-broken as y\n")
    assert validate_imports() is True


def test_validate_imports_flags_invalid_import_syntax(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write(tmp_path, "pine/broken.pine", "import justonepart as x\n")
    assert validate_imports() is False


def test_sync_library_validates_local_copy_without_error(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    """fetch_library_source returns None by design — not an error."""
    monkeypatch.chdir(tmp_path)
    _write(tmp_path, VALID_LIB_PATH, _lib_source(VALID_LIB))

    with caplog.at_level(logging.DEBUG):
        updated = sync_library(VALID_LIB, TRADINGVIEW_LIBRARIES[VALID_LIB])

    assert updated is False
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_sync_library_errors_when_local_copy_missing(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    monkeypatch.chdir(tmp_path)

    with caplog.at_level(logging.DEBUG):
        updated = sync_library(VALID_LIB, TRADINGVIEW_LIBRARIES[VALID_LIB])

    assert updated is False
    assert any("local copy missing" in r.getMessage() for r in caplog.records)


def test_sync_library_errors_on_invalid_local_syntax(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    monkeypatch.chdir(tmp_path)
    _write(tmp_path, VALID_LIB_PATH, "// not a library declaration\n")

    with caplog.at_level(logging.DEBUG):
        updated = sync_library(VALID_LIB, TRADINGVIEW_LIBRARIES[VALID_LIB])

    assert updated is False
    assert any("syntax validation" in r.getMessage() for r in caplog.records)


def test_managed_libraries_match_claude_md_inventory() -> None:
    """CLAUDE.md lists 7 libraries under management; keep the script in sync."""
    expected = {
        "smc_profile_engine",
        "smc_context_resolvers",
        "smc_observability_private",
        "smc_bus_private",
        "smc_lifecycle_private",
        "smc_overlay_generated",
        "smc_micro_profiles_generated",
    }
    assert set(TRADINGVIEW_LIBRARIES) == expected
