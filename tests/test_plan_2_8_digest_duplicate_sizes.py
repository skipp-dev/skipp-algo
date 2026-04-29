"""Tests for ``scripts/plan_2_8_digest_duplicate_sizes.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_duplicate_sizes.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_duplicate_sizes", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_duplicate_sizes"] = mod
    spec.loader.exec_module(mod)
    return mod


ds = _load()


def test_empty(tmp_path: Path) -> None:
    rep = ds.build(tmp_path)
    assert rep["group_count"] == 0


def test_no_duplicates(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    (tmp_path / "b").write_bytes(b"xx")
    assert ds.build(tmp_path)["group_count"] == 0


def test_finds_groups(tmp_path: Path) -> None:
    (tmp_path / "b").write_bytes(b"xx")
    (tmp_path / "a").write_bytes(b"yy")
    (tmp_path / "c").write_bytes(b"zzz")
    rep = ds.build(tmp_path)
    assert rep["group_count"] == 1
    assert rep["groups"][0]["size"] == 2
    assert rep["groups"][0]["names"] == ["a", "b"]


def test_subdirs_ignored(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"xx")
    (tmp_path / "b").write_bytes(b"xx")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c").write_bytes(b"xx")
    rep = ds.build(tmp_path)
    assert rep["file_count"] == 2


def test_markdown_shape(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"xx")
    (tmp_path / "b").write_bytes(b"xx")
    md = ds.render_markdown(ds.build(tmp_path))
    assert "duplicate sizes" in md
    assert "2B" in md


def test_markdown_empty(tmp_path: Path) -> None:
    md = ds.render_markdown(ds.build(tmp_path))
    assert "_none_" in md


def test_cli_fail(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"xx")
    (tmp_path / "b").write_bytes(b"xx")
    rc = ds.main([
        "--artifact-dir", str(tmp_path), "--fail-on-duplicates",
    ])
    assert rc == 1


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"xx")
    (tmp_path / "b").write_bytes(b"xx")
    out = tmp_path / "o.json"
    rc = ds.main([
        "--artifact-dir", str(tmp_path),
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["group_count"] == 1


def test_cli_missing_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ds.main(["--artifact-dir", str(tmp_path / "nope")])
    assert rc == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_duplicate_sizes_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest duplicate sizes" in names
    assert "Upload Plan 2.8 digest duplicate sizes" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest duplicate sizes")
    assert "plan_2_8_digest_duplicate_sizes.py" in step["run"]
