"""Tests for ``scripts/plan_2_8_digest_shortest_filename.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_shortest_filename.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_shortest_filename", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_shortest_filename"] = mod
    spec.loader.exec_module(mod)
    return mod


sf = _load()


def test_empty(tmp_path: Path) -> None:
    assert sf.build(tmp_path)["found"] is False


def test_picks_shortest(tmp_path: Path) -> None:
    (tmp_path / "longer_name.txt").write_text("x", encoding="utf-8")
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    rep = sf.build(tmp_path)
    assert rep["name"] == "a.txt"
    assert rep["length"] == 5


def test_tie_first_sorted_wins(tmp_path: Path) -> None:
    (tmp_path / "bb.txt").write_text("x", encoding="utf-8")
    (tmp_path / "aa.txt").write_text("x", encoding="utf-8")
    assert sf.build(tmp_path)["name"] == "aa.txt"


def test_ignores_subdirs(tmp_path: Path) -> None:
    (tmp_path / "longer_name.txt").write_text("x", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "a.txt").write_text("x", encoding="utf-8")
    assert sf.build(tmp_path)["name"] == "longer_name.txt"


def test_markdown_empty() -> None:
    assert "_none_" in sf.render_markdown(sf.build(Path("/nope")))


def test_markdown_shape(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    assert "length" in sf.render_markdown(sf.build(tmp_path))


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    out = tmp_path / "o.json"
    code = sf.main([
        "--artifact-dir", str(tmp_path), "--format", "json",
        "--output", str(out),
    ])
    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["found"] is True


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = sf.main(["--artifact-dir", str(tmp_path / "nope")])
    assert code == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_shortest_filename_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest shortest filename" in names
    assert "Upload Plan 2.8 digest shortest filename" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest shortest filename")
    assert "plan_2_8_digest_shortest_filename.py" in step["run"]
