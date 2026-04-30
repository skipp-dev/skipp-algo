"""Tests for ``scripts/plan_2_8_digest_file_count_by_ext.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_file_count_by_ext.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_file_count_by_ext", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_file_count_by_ext"] = mod
    spec.loader.exec_module(mod)
    return mod


fe = _load()


def test_empty(tmp_path: Path) -> None:
    rep = fe.build(tmp_path)
    assert rep["file_count"] == 0
    assert rep["extension_count"] == 0
    assert rep["entries"] == []


def test_counts(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("x")
    (tmp_path / "b.md").write_text("x")
    (tmp_path / "c.json").write_text("x")
    (tmp_path / "README").write_text("x")
    rep = fe.build(tmp_path)
    assert rep["file_count"] == 4
    assert rep["extension_count"] == 3
    # sorted by -count then ext
    assert rep["entries"][0] == {"ext": ".md", "count": 2}
    exts = {e["ext"] for e in rep["entries"]}
    assert exts == {".md", ".json", "<none>"}


def test_ignores_subdirs(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("x")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.md").write_text("x")
    assert fe.build(tmp_path)["file_count"] == 1


def test_markdown_shape(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("x")
    md = fe.render_markdown(fe.build(tmp_path))
    assert ".md: 1" in md


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("x")
    out = tmp_path / "o.json"
    code = fe.main([
        "--artifact-dir", str(tmp_path), "--format", "json",
        "--output", str(out),
    ])
    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["file_count"] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = fe.main(["--artifact-dir", str(tmp_path / "nope")])
    assert code == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_file_count_by_ext_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest file count by ext" in names
    assert "Upload Plan 2.8 digest file count by ext" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest file count by ext")
    assert "plan_2_8_digest_file_count_by_ext.py" in step["run"]
