"""Tests for ``scripts/plan_2_8_digest_file_age_stats.py``."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_file_age_stats.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_file_age_stats", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_file_age_stats"] = mod
    spec.loader.exec_module(mod)
    return mod


fa = _load()


def test_empty(tmp_path: Path) -> None:
    rep = fa.build(tmp_path)
    assert rep["file_count"] == 0
    assert rep["mean_age_seconds"] == 0.0


def test_known_ages(tmp_path: Path) -> None:
    a = tmp_path / "a"
    a.write_bytes(b"x")
    b = tmp_path / "b"
    b.write_bytes(b"x")
    os.utime(a, (1000.0, 1000.0))
    os.utime(b, (1500.0, 1500.0))
    rep = fa.build(tmp_path, now_ts=2000.0)
    assert rep["file_count"] == 2
    assert rep["min_age_seconds"] == 500.0
    assert rep["max_age_seconds"] == 1000.0
    assert rep["mean_age_seconds"] == 750.0


def test_subdirs_ignored(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b").write_bytes(b"x")
    rep = fa.build(tmp_path)
    assert rep["file_count"] == 1


def test_negative_age_clamped(tmp_path: Path) -> None:
    a = tmp_path / "a"
    a.write_bytes(b"x")
    os.utime(a, (2000.0, 2000.0))
    rep = fa.build(tmp_path, now_ts=1000.0)
    assert rep["min_age_seconds"] == 0.0


def test_markdown_shape(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    md = fa.render_markdown(fa.build(tmp_path))
    assert "file age stats" in md


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    out = tmp_path / "o.json"
    rc = fa.main([
        "--artifact-dir", str(tmp_path),
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["file_count"] == 1


def test_cli_missing_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = fa.main(["--artifact-dir", str(tmp_path / "nope")])
    assert rc == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_file_age_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest file age stats" in names
    assert "Upload Plan 2.8 digest file age stats" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest file age stats")
    assert "plan_2_8_digest_file_age_stats.py" in step["run"]
