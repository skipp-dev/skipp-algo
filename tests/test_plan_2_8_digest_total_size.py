"""Tests for ``scripts/plan_2_8_digest_total_size.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_total_size.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_total_size", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_total_size"] = mod
    spec.loader.exec_module(mod)
    return mod


ts = _load()


def test_empty(tmp_path: Path) -> None:
    rep = ts.build(tmp_path)
    assert rep["file_count"] == 0
    assert rep["total_bytes"] == 0


def test_basic(tmp_path: Path) -> None:
    (tmp_path / "a.bin").write_bytes(b"x" * 3)
    (tmp_path / "b.bin").write_bytes(b"y" * 7)
    rep = ts.build(tmp_path)
    assert rep["file_count"] == 2
    assert rep["total_bytes"] == 10


def test_ignores_subdirs(tmp_path: Path) -> None:
    (tmp_path / "a.bin").write_bytes(b"x")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.bin").write_bytes(b"y" * 99)
    assert ts.build(tmp_path)["total_bytes"] == 1


def test_markdown_shape(tmp_path: Path) -> None:
    (tmp_path / "a.bin").write_bytes(b"x")
    md = ts.render_markdown(ts.build(tmp_path))
    assert "total_bytes" in md


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a.bin").write_bytes(b"x" * 5)
    out = tmp_path / "o.json"
    code = ts.main([
        "--artifact-dir", str(tmp_path), "--format", "json",
        "--output", str(out),
    ])
    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["total_bytes"] == 5


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = ts.main(["--artifact-dir", str(tmp_path / "nope")])
    assert code == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_total_size_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest total size" in names
    assert "Upload Plan 2.8 digest total size" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest total size")
    assert "plan_2_8_digest_total_size.py" in step["run"]
