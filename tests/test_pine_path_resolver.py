"""Tests for ``scripts.pine_path_resolver`` (ADR-0003 resolver shim)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.pine_path_resolver import (
    CollisionError,
    find_collisions,
    resolve_pine_file,
)


def _write(p: Path, body: str = "// test\n") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def test_resolves_from_first_search_dir(tmp_path: Path) -> None:
    root = tmp_path / "root"
    legacy = tmp_path / "root" / "pine" / "legacy"
    target = _write(root / "FOO.pine")
    legacy.mkdir(parents=True, exist_ok=True)

    resolved = resolve_pine_file("FOO.pine", search_dirs=(root, legacy))

    assert resolved == target


def test_resolves_from_legacy_when_not_at_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    legacy = root / "pine" / "legacy"
    root.mkdir()
    target = _write(legacy / "OLD.pine")

    resolved = resolve_pine_file("OLD.pine", search_dirs=(root, legacy))

    assert resolved == target


def test_missing_file_raises_filenotfound(tmp_path: Path) -> None:
    root = tmp_path / "root"
    legacy = root / "pine" / "legacy"
    root.mkdir()
    legacy.mkdir(parents=True)

    with pytest.raises(FileNotFoundError, match=r"MISSING.pine"):
        resolve_pine_file("MISSING.pine", search_dirs=(root, legacy))


def test_collision_raises_collisionerror(tmp_path: Path) -> None:
    root = tmp_path / "root"
    legacy = root / "pine" / "legacy"
    _write(root / "DUP.pine")
    _write(legacy / "DUP.pine")

    with pytest.raises(CollisionError, match=r"DUP.pine"):
        resolve_pine_file("DUP.pine", search_dirs=(root, legacy))


def test_path_argument_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="bare basename"):
        resolve_pine_file("pine/legacy/FOO.pine", search_dirs=(tmp_path,))


def test_find_collisions_lists_duplicates(tmp_path: Path) -> None:
    root = tmp_path / "root"
    legacy = root / "pine" / "legacy"
    _write(root / "DUP.pine")
    _write(legacy / "DUP.pine")
    _write(root / "UNIQUE.pine")

    collisions = find_collisions(search_dirs=(root, legacy))

    assert set(collisions) == {"DUP.pine"}
    assert len(collisions["DUP.pine"]) == 2
