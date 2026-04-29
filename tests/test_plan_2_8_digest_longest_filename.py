"""Tests for ``scripts/plan_2_8_digest_longest_filename.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_longest_filename.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_longest_filename", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_longest_filename"] = mod
    spec.loader.exec_module(mod)
    return mod


lf = _load()


def test_empty(tmp_path: Path) -> None:
    assert lf.build(tmp_path)["found"] is False


def test_picks_longest(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "aaaaaa.txt").write_text("x", encoding="utf-8")
    rep = lf.build(tmp_path)
    assert rep["name"] == "aaaaaa.txt"
    assert rep["length"] == 10


def test_tie_first_sorted_wins(tmp_path: Path) -> None:
    (tmp_path / "bb.txt").write_text("x", encoding="utf-8")
    (tmp_path / "aa.txt").write_text("x", encoding="utf-8")
    assert lf.build(tmp_path)["name"] == "aa.txt"


def test_ignores_subdirs(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "very_long_filename.txt").write_text("x", encoding="utf-8")
    assert lf.build(tmp_path)["name"] == "a.txt"


def test_markdown_empty() -> None:
    assert "_none_" in lf.render_markdown(lf.build(Path("/nope")))


def test_markdown_shape(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    md = lf.render_markdown(lf.build(tmp_path))
    assert "length" in md


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    out = tmp_path / "o.json"
    code = lf.main([
        "--artifact-dir", str(tmp_path), "--format", "json",
        "--output", str(out),
    ])
    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["found"] is True


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = lf.main(["--artifact-dir", str(tmp_path / "nope")])
    assert code == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_longest_filename_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest longest filename" in names
    assert "Upload Plan 2.8 digest longest filename" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest longest filename")
    assert "plan_2_8_digest_longest_filename.py" in step["run"]
