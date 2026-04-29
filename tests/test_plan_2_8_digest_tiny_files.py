"""Tests for ``scripts/plan_2_8_digest_tiny_files.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_tiny_files.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_tiny_files", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_tiny_files"] = mod
    spec.loader.exec_module(mod)
    return mod


tf = _load()


def test_empty(tmp_path: Path) -> None:
    rep = tf.build(tmp_path, 100)
    assert rep["file_count"] == 0
    assert rep["tiny_count"] == 0


def test_identifies_tiny(tmp_path: Path) -> None:
    (tmp_path / "big").write_bytes(b"x" * 200)
    (tmp_path / "small").write_bytes(b"x" * 50)
    (tmp_path / "empty").write_bytes(b"")
    rep = tf.build(tmp_path, 100)
    names = [e["name"] for e in rep["entries"]]
    assert "big" not in names
    assert names == ["empty", "small"]  # sorted by size then name
    assert rep["tiny_count"] == 2
    assert rep["file_count"] == 3


def test_threshold_boundary_excluded(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x" * 100)
    rep = tf.build(tmp_path, 100)
    assert rep["tiny_count"] == 0


def test_subdirs_ignored(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b").write_bytes(b"x")
    rep = tf.build(tmp_path, 100)
    assert rep["file_count"] == 1


def test_markdown_shape(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    md = tf.render_markdown(tf.build(tmp_path, 100))
    assert "tiny files" in md


def test_cli_fail_on_tiny(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    rc = tf.main([
        "--artifact-dir", str(tmp_path),
        "--threshold-bytes", "100", "--fail-on-tiny",
    ])
    assert rc == 1


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    out = tmp_path / "o.json"
    rc = tf.main([
        "--artifact-dir", str(tmp_path),
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["tiny_count"] == 1


def test_cli_missing_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = tf.main(["--artifact-dir", str(tmp_path / "nope")])
    assert rc == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_tiny_files_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest tiny files" in names
    assert "Upload Plan 2.8 digest tiny files" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest tiny files")
    assert "plan_2_8_digest_tiny_files.py" in step["run"]
