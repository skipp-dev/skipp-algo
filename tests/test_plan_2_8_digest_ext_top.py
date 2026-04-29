"""Tests for ``scripts/plan_2_8_digest_ext_top.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_ext_top.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_ext_top", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_ext_top"] = mod
    spec.loader.exec_module(mod)
    return mod


et = _load()


def test_empty(tmp_path: Path) -> None:
    rep = et.build(tmp_path)
    assert rep["top_ext"] is None
    assert rep["top_count"] == 0


def test_picks_top(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    (tmp_path / "b.md").write_text("x", encoding="utf-8")
    (tmp_path / "c.json").write_text("x", encoding="utf-8")
    rep = et.build(tmp_path)
    assert rep["top_ext"] == "md"
    assert rep["top_count"] == 2


def test_tie_breaks_alpha(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    (tmp_path / "c.json").write_text("x", encoding="utf-8")
    rep = et.build(tmp_path)
    assert rep["top_ext"] == "json"


def test_no_ext_empty_string(tmp_path: Path) -> None:
    (tmp_path / "README").write_text("x", encoding="utf-8")
    (tmp_path / "NOTES").write_text("x", encoding="utf-8")
    rep = et.build(tmp_path)
    assert rep["top_ext"] == ""
    assert rep["top_count"] == 2


def test_subdirs_ignored(tmp_path: Path) -> None:
    sub = tmp_path / "s"
    sub.mkdir()
    (sub / "a.md").write_text("x", encoding="utf-8")
    (sub / "b.md").write_text("x", encoding="utf-8")
    (tmp_path / "a.json").write_text("x", encoding="utf-8")
    rep = et.build(tmp_path)
    assert rep["top_ext"] == "json"


def test_markdown_shape_none(tmp_path: Path) -> None:
    md = et.render_markdown(et.build(tmp_path))
    assert "top_ext: (none)" in md


def test_markdown_shape_noext(tmp_path: Path) -> None:
    (tmp_path / "README").write_text("x", encoding="utf-8")
    md = et.render_markdown(et.build(tmp_path))
    assert "top_ext: (no-ext)" in md


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = et.main([
        "--artifact-dir", str(tmp_path),
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["top_ext"] == "md"


def test_cli_fail_below_count(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    rc = et.main([
        "--artifact-dir", str(tmp_path), "--fail-below-count", "5",
    ])
    assert rc == 1


def test_cli_missing_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = et.main(["--artifact-dir", str(tmp_path / "nope")])
    assert rc == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_ext_top_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest top extension" in names
    assert "Upload Plan 2.8 digest top extension" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest top extension")
    assert "plan_2_8_digest_ext_top.py" in step["run"]
