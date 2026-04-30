"""Tests for ``scripts/plan_2_8_digest_file_manifest.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_file_manifest.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_file_manifest", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_file_manifest"] = mod
    spec.loader.exec_module(mod)
    return mod


fm = _load()


def _fake_repo(tmp_path: Path,
               scripts: list[str], tests: list[str]) -> Path:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "tests").mkdir()
    for s in scripts:
        (tmp_path / "scripts" / s).write_text("", encoding="utf-8")
    for t in tests:
        (tmp_path / "tests" / t).write_text("", encoding="utf-8")
    return tmp_path


def test_matched_pair_no_orphans(tmp_path: Path) -> None:
    root = _fake_repo(
        tmp_path,
        scripts=["plan_2_8_foo.py"],
        tests=["test_plan_2_8_foo.py"],
    )
    rep = fm.scan(root)
    assert rep["counts"]["scripts"] == 1
    assert rep["counts"]["tests"] == 1
    assert rep["orphan_scripts"] == []
    assert rep["orphan_tests"] == []


def test_orphan_script_detected(tmp_path: Path) -> None:
    root = _fake_repo(
        tmp_path,
        scripts=["plan_2_8_foo.py", "plan_2_8_bar.py"],
        tests=["test_plan_2_8_foo.py"],
    )
    rep = fm.scan(root)
    assert rep["orphan_scripts"] == ["plan_2_8_bar"]
    assert rep["orphan_tests"] == []


def test_orphan_test_detected(tmp_path: Path) -> None:
    root = _fake_repo(
        tmp_path,
        scripts=["plan_2_8_foo.py"],
        tests=["test_plan_2_8_foo.py", "test_plan_2_8_bar.py"],
    )
    rep = fm.scan(root)
    assert rep["orphan_tests"] == ["plan_2_8_bar"]
    assert rep["orphan_scripts"] == []


def test_self_and_status_excluded(tmp_path: Path) -> None:
    root = _fake_repo(
        tmp_path,
        scripts=["plan_2_8_digest_file_manifest.py",
                 "plan_2_8_status.py",
                 "plan_2_8_foo.py"],
        tests=["test_plan_2_8_foo.py"],
    )
    rep = fm.scan(root)
    assert rep["counts"]["scripts"] == 1
    assert rep["orphan_scripts"] == []


def test_markdown_lists_orphans(tmp_path: Path) -> None:
    root = _fake_repo(
        tmp_path,
        scripts=["plan_2_8_foo.py"],
        tests=["test_plan_2_8_bar.py"],
    )
    md = fm.render_markdown(fm.scan(root))
    assert "Scripts without tests" in md
    assert "Tests without scripts" in md
    assert "plan_2_8_foo" in md
    assert "plan_2_8_bar" in md


def test_markdown_clean(tmp_path: Path) -> None:
    root = _fake_repo(
        tmp_path,
        scripts=["plan_2_8_foo.py"],
        tests=["test_plan_2_8_foo.py"],
    )
    md = fm.render_markdown(fm.scan(root))
    assert "All scripts have matching tests" in md


def test_cli_json(tmp_path: Path) -> None:
    root = _fake_repo(
        tmp_path,
        scripts=["plan_2_8_foo.py"],
        tests=["test_plan_2_8_foo.py"],
    )
    out = tmp_path / "m.json"
    rc = fm.main([
        "--repo-root", str(root),
        "--format", "json",
        "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["counts"]["scripts"] == 1


def test_cli_fail_on_orphan(tmp_path: Path) -> None:
    root = _fake_repo(
        tmp_path,
        scripts=["plan_2_8_foo.py", "plan_2_8_bar.py"],
        tests=["test_plan_2_8_foo.py"],
    )
    rc = fm.main([
        "--repo-root", str(root),
        "--fail-on-orphan",
    ])
    assert rc == 1


def test_cli_fail_on_orphan_clean(tmp_path: Path) -> None:
    root = _fake_repo(
        tmp_path,
        scripts=["plan_2_8_foo.py"],
        tests=["test_plan_2_8_foo.py"],
    )
    rc = fm.main([
        "--repo-root", str(root),
        "--fail-on-orphan",
    ])
    assert rc == 0


def test_cli_bad_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = fm.main(["--repo-root", str(tmp_path)])
    assert rc == 1
    assert "scripts/" in capsys.readouterr().err
