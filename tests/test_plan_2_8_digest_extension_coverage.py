"""Tests for ``scripts/plan_2_8_digest_extension_coverage.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_extension_coverage.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_extension_coverage", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_extension_coverage"] = mod
    spec.loader.exec_module(mod)
    return mod


ec = _load()


def test_empty(tmp_path: Path) -> None:
    rep = ec.build(tmp_path)
    assert rep["file_count"] == 0
    assert rep["coverage_ratio"] == 0.0


def test_all_with_ext(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"x")
    (tmp_path / "b.json").write_bytes(b"x")
    rep = ec.build(tmp_path)
    assert rep["coverage_ratio"] == 1.0


def test_partial(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"x")
    (tmp_path / "b").write_bytes(b"x")
    rep = ec.build(tmp_path)
    assert rep["files_with_ext"] == 1
    assert rep["files_without_ext"] == 1
    assert rep["coverage_ratio"] == 0.5


def test_subdirs_ignored(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.md").write_bytes(b"x")
    rep = ec.build(tmp_path)
    assert rep["file_count"] == 1


def test_markdown_shape(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"x")
    md = ec.render_markdown(ec.build(tmp_path))
    assert "extension coverage" in md


def test_cli_fail_below(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    rc = ec.main([
        "--artifact-dir", str(tmp_path), "--fail-below-ratio", "0.5",
    ])
    assert rc == 1


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"x")
    out = tmp_path / "o.json"
    rc = ec.main([
        "--artifact-dir", str(tmp_path),
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["coverage_ratio"] == 1.0


def test_cli_missing_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ec.main(["--artifact-dir", str(tmp_path / "nope")])
    assert rc == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_extension_coverage_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest extension coverage" in names
    assert "Upload Plan 2.8 digest extension coverage" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest extension coverage")
    assert "plan_2_8_digest_extension_coverage.py" in step["run"]
