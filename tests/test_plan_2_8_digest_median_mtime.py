"""Tests for ``scripts/plan_2_8_digest_median_mtime.py``."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_median_mtime.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_median_mtime", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_median_mtime"] = mod
    spec.loader.exec_module(mod)
    return mod


mm = _load()


def _set(p: Path, t: int) -> None:
    os.utime(p, (t, t))


def test_empty(tmp_path: Path) -> None:
    assert mm.build(tmp_path)["found"] is False


def test_single(tmp_path: Path) -> None:
    p = tmp_path / "a"
    p.write_bytes(b"x")
    _set(p, 1_700_000_000)
    rep = mm.build(tmp_path)
    assert rep["file_count"] == 1
    assert "1970" not in rep["median_mtime"]


def test_odd_count(tmp_path: Path) -> None:
    for i, t in enumerate([1_700_000_000, 1_710_000_000, 1_720_000_000]):
        p = tmp_path / f"f{i}"
        p.write_bytes(b"x")
        _set(p, t)
    rep = mm.build(tmp_path)
    assert rep["file_count"] == 3
    assert "2024" in rep["median_mtime"] or "2023" in rep["median_mtime"]


def test_lower_middle_for_even(tmp_path: Path) -> None:
    ts = [1_700_000_000, 1_710_000_000, 1_720_000_000, 1_730_000_000]
    for i, t in enumerate(ts):
        p = tmp_path / f"f{i}"
        p.write_bytes(b"x")
        _set(p, t)
    rep = mm.build(tmp_path)
    # lower middle is index 1 -> 1_710_000_000 (2024)
    assert "2024" in rep["median_mtime"]


def test_subdirs_ignored(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a").write_bytes(b"x")
    assert mm.build(tmp_path)["found"] is False


def test_markdown_empty(tmp_path: Path) -> None:
    assert "_none_" in mm.render_markdown(mm.build(tmp_path))


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    out = tmp_path / "o.json"
    rc = mm.main([
        "--artifact-dir", str(tmp_path),
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["found"] is True


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = mm.main(["--artifact-dir", str(tmp_path / "nope")])
    assert rc == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_median_mtime_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest median mtime" in names
    assert "Upload Plan 2.8 digest median mtime" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest median mtime")
    assert "plan_2_8_digest_median_mtime.py" in step["run"]
