"""Tests for ``scripts/plan_2_8_digest_name_length_stats.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_name_length_stats.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_name_length_stats", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_name_length_stats"] = mod
    spec.loader.exec_module(mod)
    return mod


nl = _load()


def test_empty(tmp_path: Path) -> None:
    rep = nl.build(tmp_path)
    assert rep["file_count"] == 0
    assert rep["mean_length"] == 0.0


def test_stats(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")          # 1
    (tmp_path / "abc").write_bytes(b"x")        # 3
    (tmp_path / "abcdef").write_bytes(b"x")     # 6
    rep = nl.build(tmp_path)
    assert rep["file_count"] == 3
    assert rep["min_length"] == 1
    assert rep["max_length"] == 6
    assert rep["mean_length"] == round(10 / 3, 2)


def test_subdirs_ignored(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "longer_name").write_bytes(b"x")
    rep = nl.build(tmp_path)
    assert rep["file_count"] == 1
    assert rep["max_length"] == 1


def test_markdown_shape(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    md = nl.render_markdown(nl.build(tmp_path))
    assert "name length stats" in md


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "abc").write_bytes(b"x")
    out = tmp_path / "o.json"
    rc = nl.main([
        "--artifact-dir", str(tmp_path),
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["max_length"] == 3


def test_cli_missing_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = nl.main(["--artifact-dir", str(tmp_path / "nope")])
    assert rc == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_name_length_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest name length stats" in names
    assert "Upload Plan 2.8 digest name length stats" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest name length stats")
    assert "plan_2_8_digest_name_length_stats.py" in step["run"]
