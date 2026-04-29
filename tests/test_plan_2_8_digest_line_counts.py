"""Tests for ``scripts/plan_2_8_digest_line_counts.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_line_counts.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_line_counts", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_line_counts"] = mod
    spec.loader.exec_module(mod)
    return mod


lc = _load()


def test_empty(tmp_path: Path) -> None:
    rep = lc.build(tmp_path)
    assert rep["file_count"] == 0
    assert rep["total_lines"] == 0


def test_basic(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("x", encoding="utf-8")
    rep = lc.build(tmp_path)
    assert rep["file_count"] == 2
    assert rep["total_lines"] == 4
    names = [e["name"] for e in rep["entries"]]
    assert names == ["a.txt", "b.txt"]


def test_ignores_subdirs(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("only\n", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "x.txt").write_text("ignored\n", encoding="utf-8")
    rep = lc.build(tmp_path)
    assert rep["file_count"] == 1


def test_no_trailing_newline(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    assert lc.build(tmp_path)["total_lines"] == 1


def test_markdown_shape(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a\nb\n", encoding="utf-8")
    md = lc.render_markdown(lc.build(tmp_path))
    assert "total_lines" in md
    assert "a.txt" in md


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = lc.main([
        "--artifact-dir", str(tmp_path), "--format", "json",
        "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["total_lines"] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = lc.main(["--artifact-dir", str(tmp_path / "nope")])
    assert rc == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_line_counts_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest line counts" in names
    assert "Upload Plan 2.8 digest line counts" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest line counts")
    assert "plan_2_8_digest_line_counts.py" in step["run"]
