"""Tests for ``scripts/plan_2_8_digest_size_sum.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_size_sum.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_size_sum", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_size_sum"] = mod
    spec.loader.exec_module(mod)
    return mod


ss = _load()


def test_empty(tmp_path: Path) -> None:
    rep = ss.build(tmp_path)
    assert rep == {
        "schema_version": 1,
        "file_count": 0,
        "total_bytes": 0,
    }


def test_sum(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    (tmp_path / "b.md").write_text("hi", encoding="utf-8")
    rep = ss.build(tmp_path)
    assert rep["file_count"] == 2
    assert rep["total_bytes"] == 7


def test_subdirs_ignored(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    sub = tmp_path / "s"
    sub.mkdir()
    (sub / "b.md").write_text("hi", encoding="utf-8")
    rep = ss.build(tmp_path)
    assert rep["file_count"] == 1
    assert rep["total_bytes"] == 5


def test_markdown_shape(tmp_path: Path) -> None:
    md = ss.render_markdown(ss.build(tmp_path))
    assert "size sum" in md
    assert "total_bytes:" in md


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("abc", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = ss.main([
        "--artifact-dir", str(tmp_path),
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["total_bytes"] == 3


def test_cli_fail_above_bytes(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("abcdef", encoding="utf-8")
    rc = ss.main([
        "--artifact-dir", str(tmp_path), "--fail-above-bytes", "3",
    ])
    assert rc == 1


def test_cli_missing_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ss.main(["--artifact-dir", str(tmp_path / "nope")])
    assert rc == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_size_sum_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest size sum" in names
    assert "Upload Plan 2.8 digest size sum" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest size sum")
    assert "plan_2_8_digest_size_sum.py" in step["run"]
