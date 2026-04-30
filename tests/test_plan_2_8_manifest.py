"""Tests for ``scripts/plan_2_8_manifest.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_manifest.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_manifest", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_manifest"] = mod
    spec.loader.exec_module(mod)
    return mod


mf = _load()


def _mk_repo(tmp: Path) -> Path:
    (tmp / "scripts").mkdir()
    (tmp / "tests").mkdir()
    return tmp


def _script(tmp: Path, name: str, flags: list[str] = ()) -> None:
    body = [
        "import argparse",
        "def main(argv=None):",
        "    p = argparse.ArgumentParser()",
    ]
    for f in flags:
        body.append(f"    p.add_argument('{f}')")
    body += ["    p.parse_args(argv)", "    return 0", ""]
    (tmp / "scripts" / name).write_text("\n".join(body), encoding="utf-8")


def _test(tmp: Path, name: str) -> None:
    (tmp / "tests" / name).write_text("# test\n", encoding="utf-8")


def test_flag_extraction_dedupes_order_preserved() -> None:
    src = (
        "add_argument('--alpha')\n"
        "add_argument('--beta')\n"
        "add_argument('--alpha')\n"
        "add_argument('--gamma-one')\n"
    )
    assert mf._extract_flags(src) == ["--alpha", "--beta", "--gamma-one"]


def test_scan_pairs_script_with_test(tmp_path: Path) -> None:
    repo = _mk_repo(tmp_path)
    _script(repo, "plan_2_8_foo.py", ["--x", "--y"])
    _test(repo, "test_plan_2_8_foo.py")
    rep = mf.scan(repo)
    assert rep["counts"]["scripts"] == 1
    assert rep["counts"]["with_test"] == 1
    assert rep["counts"]["without"] == 0
    row = rep["entries"][0]
    assert row["has_test"] is True
    assert row["cli_flags"] == ["--x", "--y"]


def test_scan_detects_missing_test(tmp_path: Path) -> None:
    repo = _mk_repo(tmp_path)
    _script(repo, "plan_2_8_orphan.py", [])
    rep = mf.scan(repo)
    assert rep["counts"]["without"] == 1
    assert rep["entries"][0]["test"] is None


def test_scan_ignores_non_plan_scripts(tmp_path: Path) -> None:
    repo = _mk_repo(tmp_path)
    _script(repo, "something_else.py", [])
    _script(repo, "plan_2_8_real.py", [])
    rep = mf.scan(repo)
    assert rep["counts"]["scripts"] == 1


def test_scan_ignores_non_plan_tests(tmp_path: Path) -> None:
    repo = _mk_repo(tmp_path)
    _script(repo, "plan_2_8_foo.py", [])
    _test(repo, "test_unrelated.py")
    rep = mf.scan(repo)
    assert rep["counts"]["with_test"] == 0


def test_scan_missing_directories_returns_empty(tmp_path: Path) -> None:
    rep = mf.scan(tmp_path)  # no scripts/ or tests/
    assert rep["counts"] == {"scripts": 0, "with_test": 0, "without": 0}
    assert rep["entries"] == []


def test_render_markdown_headers(tmp_path: Path) -> None:
    repo = _mk_repo(tmp_path)
    _script(repo, "plan_2_8_alpha.py", ["--x"])
    _test(repo, "test_plan_2_8_alpha.py")
    md = mf.render_markdown(mf.scan(repo))
    assert "# Plan 2.8 script manifest" in md
    assert "plan_2_8_alpha.py" in md
    assert "`--x`" in md


def test_render_markdown_missing_test_annotation(tmp_path: Path) -> None:
    repo = _mk_repo(tmp_path)
    _script(repo, "plan_2_8_lonely.py", [])
    md = mf.render_markdown(mf.scan(repo))
    assert "_missing_" in md


def test_cli_json_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _mk_repo(tmp_path)
    _script(repo, "plan_2_8_foo.py", ["--a"])
    _test(repo, "test_plan_2_8_foo.py")
    rc = mf.main(["--repo-root", str(repo), "--format", "json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["scripts"] == 1


def test_cli_md_output_to_file(tmp_path: Path) -> None:
    repo = _mk_repo(tmp_path)
    _script(repo, "plan_2_8_foo.py", [])
    out = tmp_path / "m.md"
    rc = mf.main([
        "--repo-root", str(repo), "--format", "md", "--output", str(out),
    ])
    assert rc == 0
    assert "Plan 2.8 script manifest" in out.read_text(encoding="utf-8")


def test_cli_fail_on_missing_test(tmp_path: Path) -> None:
    repo = _mk_repo(tmp_path)
    _script(repo, "plan_2_8_foo.py", [])
    rc = mf.main([
        "--repo-root", str(repo), "--fail-on-missing-test",
    ])
    assert rc == 1


def test_cli_fail_on_missing_test_passes_when_clean(tmp_path: Path) -> None:
    repo = _mk_repo(tmp_path)
    _script(repo, "plan_2_8_foo.py", [])
    _test(repo, "test_plan_2_8_foo.py")
    rc = mf.main([
        "--repo-root", str(repo), "--fail-on-missing-test",
    ])
    assert rc == 0


def test_cli_missing_repo_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = mf.main([
        "--repo-root", str(tmp_path / "nope"), "--format", "json",
    ])
    assert rc == 1
    assert "repo-root not found" in capsys.readouterr().err


def test_real_repo_has_paired_tests_for_all_plan_2_8_scripts() -> None:
    rep = mf.scan(REPO)
    without = [r["script"] for r in rep["entries"] if not r["has_test"]]
    assert without == [], f"scripts missing tests: {without}"
