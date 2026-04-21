"""Tests for ``scripts/plan_2_8_digest_binary_file_count.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_binary_file_count.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_binary_file_count", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_binary_file_count"] = mod
    spec.loader.exec_module(mod)
    return mod


bf = _load()


def test_empty(tmp_path: Path) -> None:
    assert bf.build(tmp_path)["binary_file_count"] == 0


def test_counts(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("text")
    (tmp_path / "b.bin").write_bytes(b"\x00\x01\x02")
    rep = bf.build(tmp_path)
    assert rep["entry_count"] == 2
    assert rep["binary_file_count"] == 1


def test_dir_skipped(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    rep = bf.build(tmp_path)
    assert rep["entry_count"] == 1
    assert rep["binary_file_count"] == 0


def test_markdown_shape(tmp_path: Path) -> None:
    assert "binary_file_count" in bf.render_markdown(bf.build(tmp_path))


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "b.bin").write_bytes(b"\x00")
    out = tmp_path / "o.json"
    code = bf.main([
        "--artifact-dir", str(tmp_path), "--format", "json",
        "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["binary_file_count"] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = bf.main(["--artifact-dir", str(tmp_path / "nope")])
    assert code == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_binary_count_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest binary file count" in names
    assert "Upload Plan 2.8 digest binary file count" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest binary file count")
    assert "plan_2_8_digest_binary_file_count.py" in step["run"]
