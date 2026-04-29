"""Tests for ``scripts/plan_2_8_digest_empty_files.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_empty_files.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_empty_files", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_empty_files"] = mod
    spec.loader.exec_module(mod)
    return mod


ef = _load()


def test_empty_dir(tmp_path: Path) -> None:
    rep = ef.build(tmp_path)
    assert rep["file_count"] == 0
    assert rep["empty_count"] == 0


def test_none_empty(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    rep = ef.build(tmp_path)
    assert rep["empty_count"] == 0


def test_finds_empty_sorted(tmp_path: Path) -> None:
    (tmp_path / "b").write_bytes(b"")
    (tmp_path / "a").write_bytes(b"")
    (tmp_path / "c").write_bytes(b"x")
    rep = ef.build(tmp_path)
    assert rep["empty_files"] == ["a", "b"]


def test_subdirs_ignored(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b").write_bytes(b"")
    rep = ef.build(tmp_path)
    assert rep["empty_count"] == 1


def test_markdown_none(tmp_path: Path) -> None:
    md = ef.render_markdown(ef.build(tmp_path))
    assert "_none_" in md


def test_markdown_lists(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"")
    md = ef.render_markdown(ef.build(tmp_path))
    assert "- a" in md


def test_cli_fail_on_empty(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"")
    rc = ef.main([
        "--artifact-dir", str(tmp_path), "--fail-on-empty",
    ])
    assert rc == 1


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"")
    out = tmp_path / "o.json"
    rc = ef.main([
        "--artifact-dir", str(tmp_path),
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["empty_count"] == 1


def test_cli_missing_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ef.main(["--artifact-dir", str(tmp_path / "nope")])
    assert rc == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_empty_files_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest empty files" in names
    assert "Upload Plan 2.8 digest empty files" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest empty files")
    assert "plan_2_8_digest_empty_files.py" in step["run"]
