"""Tests for ``scripts/plan_2_8_digest_median_size.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_median_size.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_median_size", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_median_size"] = mod
    spec.loader.exec_module(mod)
    return mod


ms = _load()


def test_empty_dir(tmp_path: Path) -> None:
    rep = ms.build(tmp_path)
    assert rep["file_count"] == 0
    assert rep["median_bytes"] == 0.0


def test_odd_count(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    (tmp_path / "b").write_bytes(b"xx")
    (tmp_path / "c").write_bytes(b"xxxx")
    rep = ms.build(tmp_path)
    assert rep["file_count"] == 3
    assert rep["median_bytes"] == 2.0


def test_even_count(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    (tmp_path / "b").write_bytes(b"xxx")
    rep = ms.build(tmp_path)
    assert rep["median_bytes"] == 2.0


def test_subdirs_ignored(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b").write_bytes(b"xxxxx")
    rep = ms.build(tmp_path)
    assert rep["file_count"] == 1
    assert rep["median_bytes"] == 1.0


def test_markdown_shape(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    md = ms.render_markdown(ms.build(tmp_path))
    assert "median size" in md


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    out = tmp_path / "o.json"
    rc = ms.main([
        "--artifact-dir", str(tmp_path),
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["file_count"] == 1


def test_cli_missing_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ms.main(["--artifact-dir", str(tmp_path / "nope")])
    assert rc == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_median_size_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest median size" in names
    assert "Upload Plan 2.8 digest median size" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest median size")
    assert "plan_2_8_digest_median_size.py" in step["run"]
