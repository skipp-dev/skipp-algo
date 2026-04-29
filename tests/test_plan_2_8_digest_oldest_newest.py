"""Tests for ``scripts/plan_2_8_digest_oldest_newest.py``."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_oldest_newest.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_oldest_newest", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_oldest_newest"] = mod
    spec.loader.exec_module(mod)
    return mod


on = _load()


def test_empty(tmp_path: Path) -> None:
    rep = on.build(tmp_path)
    assert rep["file_count"] == 0
    assert rep["oldest"] is None
    assert rep["newest"] is None


def test_oldest_newest(tmp_path: Path) -> None:
    a = tmp_path / "a"
    a.write_bytes(b"x")
    b = tmp_path / "b"
    b.write_bytes(b"xx")
    os.utime(a, (100, 100))
    os.utime(b, (200, 200))
    rep = on.build(tmp_path)
    assert rep["oldest"]["name"] == "a"
    assert rep["newest"]["name"] == "b"


def test_subdirs_ignored(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b").write_bytes(b"xx")
    rep = on.build(tmp_path)
    assert rep["file_count"] == 1


def test_markdown_empty(tmp_path: Path) -> None:
    md = on.render_markdown(on.build(tmp_path))
    assert "_none_" in md


def test_markdown_shape(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    md = on.render_markdown(on.build(tmp_path))
    assert "oldest" in md and "newest" in md


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    out = tmp_path / "o.json"
    rc = on.main([
        "--artifact-dir", str(tmp_path),
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["file_count"] == 1


def test_cli_missing_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = on.main(["--artifact-dir", str(tmp_path / "nope")])
    assert rc == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_oldest_newest_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest oldest/newest" in names
    assert "Upload Plan 2.8 digest oldest/newest" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest oldest/newest")
    assert "plan_2_8_digest_oldest_newest.py" in step["run"]
