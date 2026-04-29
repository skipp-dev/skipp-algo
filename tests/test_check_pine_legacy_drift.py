"""Tests for ``scripts/check_pine_legacy_drift.py``.

The drift check is the D-1 v2 follow-up enforcement: it stops new root
``*.pine`` files from being added without a matching entry in
``PINE_LEGACY.md`` and stops stale entries from accumulating.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_pine_legacy_drift.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "check_pine_legacy_drift", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_pine_legacy_drift"] = mod
    spec.loader.exec_module(mod)
    return mod


CHECK = _load_module()


def _write_index(path: Path, rows: list[str]) -> None:
    body = ["# Index", "", "| File | LOC |", "|---|---:|"]
    body.extend(f"| `{name}` | 1 |" for name in rows)
    path.write_text("\n".join(body) + "\n", encoding="utf-8")


def _make_repo(tmp_path: Path, files: list[str], indexed: list[str]) -> tuple[Path, Path]:
    for name in files:
        (tmp_path / name).write_text("// pine\n", encoding="utf-8")
    index = tmp_path / "PINE_LEGACY.md"
    _write_index(index, indexed)
    return tmp_path, index


class TestRootFileEnumeration:
    def test_lists_only_root_level_pine_files(self, tmp_path):
        (tmp_path / "A.pine").write_text("//\n")
        (tmp_path / "B.pine").write_text("//\n")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "nested.pine").write_text("//\n")

        result = CHECK.list_root_pine_files(tmp_path)

        assert result == {"A.pine", "B.pine"}


class TestIndexParsing:
    def test_only_table_rows_are_counted(self, tmp_path):
        index = tmp_path / "PINE_LEGACY.md"
        index.write_text(
            "# Index\n\n"
            "Some prose mentioning `Ghost.pine` should NOT count.\n\n"
            "| File | LOC |\n"
            "|---|---:|\n"
            "| `Real.pine` | 10 |\n"
            "| `Other.pine` | 20 |\n",
            encoding="utf-8",
        )
        assert CHECK.parse_index_file_names(index) == {"Real.pine", "Other.pine"}

    def test_glob_patterns_excluded(self, tmp_path):
        index = tmp_path / "PINE_LEGACY.md"
        index.write_text(
            "| `*.pine` | n/a |\n"
            "| `Real.pine` | 1 |\n",
            encoding="utf-8",
        )
        assert CHECK.parse_index_file_names(index) == {"Real.pine"}

    def test_nested_paths_excluded(self, tmp_path):
        index = tmp_path / "PINE_LEGACY.md"
        index.write_text(
            "| `pine/library.pine` | 1 |\n"
            "| `Root.pine` | 1 |\n",
            encoding="utf-8",
        )
        assert CHECK.parse_index_file_names(index) == {"Root.pine"}

    def test_missing_index_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            CHECK.parse_index_file_names(tmp_path / "does_not_exist.md")


class TestMainExitCodes:
    def test_passes_when_in_sync(self, tmp_path, capsys):
        root, index = _make_repo(
            tmp_path, files=["A.pine", "B.pine"], indexed=["A.pine", "B.pine"]
        )
        rc = CHECK.main(["--root", str(root), "--index", str(index)])
        captured = capsys.readouterr()
        assert rc == 0
        assert "OK" in captured.out

    def test_fails_when_root_has_unindexed_file(self, tmp_path, capsys):
        root, index = _make_repo(
            tmp_path,
            files=["A.pine", "Brand_New.pine"],
            indexed=["A.pine"],
        )
        rc = CHECK.main(["--root", str(root), "--index", str(index)])
        captured = capsys.readouterr()
        assert rc == 1
        assert "Brand_New.pine" in captured.out
        assert "Missing from PINE_LEGACY.md" in captured.out

    def test_fails_when_index_has_stale_entry(self, tmp_path, capsys):
        root, index = _make_repo(
            tmp_path, files=["A.pine"], indexed=["A.pine", "Removed.pine"]
        )
        rc = CHECK.main(["--root", str(root), "--index", str(index)])
        captured = capsys.readouterr()
        assert rc == 1
        assert "Removed.pine" in captured.out
        assert "Stale entries" in captured.out

    def test_real_repo_is_in_sync(self):
        """Lock-down: the live PINE_LEGACY.md must match real root state.

        If this fails, either add the new file to PINE_LEGACY.md or
        remove the stale entry from the index. This is the regression
        guard for the D-1 v2 follow-up.
        """
        rc = CHECK.main([])
        assert rc == 0
