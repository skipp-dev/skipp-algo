"""Tests for ``scripts/plan_2_8_digest_missing_files.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_missing_files.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_missing_files", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_missing_files"] = mod
    spec.loader.exec_module(mod)
    return mod


mf = _load()


def test_empty(tmp_path: Path) -> None:
    rep = mf.build(tmp_path)
    assert rep["required_count"] == len(mf.REQUIRED_FILES)
    assert rep["present_count"] == 0
    assert set(rep["missing_files"]) == set(mf.REQUIRED_FILES)


def test_all_present(tmp_path: Path) -> None:
    for name in mf.REQUIRED_FILES:
        (tmp_path / name).write_text("x", encoding="utf-8")
    rep = mf.build(tmp_path)
    assert rep["missing_count"] == 0
    assert rep["missing_files"] == []


def test_partial(tmp_path: Path) -> None:
    (tmp_path / mf.REQUIRED_FILES[0]).write_text("x", encoding="utf-8")
    rep = mf.build(tmp_path)
    assert rep["present_count"] == 1
    assert rep["missing_count"] == len(mf.REQUIRED_FILES) - 1


def test_markdown_shape(tmp_path: Path) -> None:
    assert "missing_count" in mf.render_markdown(mf.build(tmp_path))


def test_cli_json(tmp_path: Path) -> None:
    out = tmp_path / "o.json"
    code = mf.main([
        "--artifact-dir", str(tmp_path), "--format", "json",
        "--output", str(out),
    ])
    assert code == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["required_count"] == len(mf.REQUIRED_FILES)


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = mf.main(["--artifact-dir", str(tmp_path / "nope")])
    assert code == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_missing_files_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest missing files" in names
    assert "Upload Plan 2.8 digest missing files" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest missing files")
    assert "plan_2_8_digest_missing_files.py" in step["run"]
