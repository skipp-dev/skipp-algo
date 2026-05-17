"""Tests for ``scripts/plan_2_8_digest_stale_report.py``."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_stale_report.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_stale_report", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_stale_report"] = mod
    spec.loader.exec_module(mod)
    return mod


sr = _load()


def _touch(path: Path, age_days: float) -> None:
    path.write_text("x", encoding="utf-8")
    t = time.time() - age_days * 86400
    os.utime(path, (t, t))


def test_fresh_file(tmp_path: Path) -> None:
    _touch(tmp_path / "a.md", 1)
    rep = sr.classify(tmp_path, warn_days=7, stale_days=14)
    assert len(rep["fresh"]) == 1
    assert rep["warn"] == [] and rep["stale"] == []


def test_warn_file(tmp_path: Path) -> None:
    _touch(tmp_path / "a.md", 10)
    rep = sr.classify(tmp_path, warn_days=7, stale_days=14)
    assert len(rep["warn"]) == 1


def test_stale_file(tmp_path: Path) -> None:
    _touch(tmp_path / "a.md", 20)
    rep = sr.classify(tmp_path, warn_days=7, stale_days=14)
    assert len(rep["stale"]) == 1


def test_boundary_warn(tmp_path: Path) -> None:
    _touch(tmp_path / "a.md", 7)
    rep = sr.classify(tmp_path, warn_days=7, stale_days=14)
    assert len(rep["warn"]) == 1


def test_boundary_stale(tmp_path: Path) -> None:
    if sys.platform == "win32":
        pytest.skip("Windows-specific failure tracked in #2267")
    _touch(tmp_path / "a.md", 14)
    rep = sr.classify(tmp_path, warn_days=7, stale_days=14)
    assert len(rep["stale"]) == 1


def test_missing_dir(tmp_path: Path) -> None:
    rep = sr.classify(tmp_path / "nope", warn_days=7, stale_days=14)
    assert rep["fresh"] == [] and rep["warn"] == [] and rep["stale"] == []


def test_subdirectories_ignored(tmp_path: Path) -> None:
    _touch(tmp_path / "a.md", 1)
    (tmp_path / "sub").mkdir()
    _touch(tmp_path / "sub" / "b.md", 30)
    rep = sr.classify(tmp_path, warn_days=7, stale_days=14)
    assert len(rep["fresh"]) + len(rep["warn"]) + len(rep["stale"]) == 1


def test_markdown_none_placeholder(tmp_path: Path) -> None:
    md = sr.render_markdown(
        sr.classify(tmp_path, warn_days=7, stale_days=14),
    )
    assert "_(none)_" in md


def test_cli_fail_on_stale(tmp_path: Path) -> None:
    _touch(tmp_path / "a.md", 20)
    rc = sr.main([
        "--artifact-dir", str(tmp_path),
        "--warn-days",  "7",
        "--stale-days", "14",
        "--fail-on-stale",
    ])
    assert rc == 1


def test_cli_json(tmp_path: Path) -> None:
    _touch(tmp_path / "a.md", 1)
    out = tmp_path / "o.json"
    rc = sr.main([
        "--artifact-dir", str(tmp_path),
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert len(payload["fresh"]) == 1


def test_cli_missing_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = sr.main(["--artifact-dir", str(tmp_path / "nope")])
    assert rc == 1
    assert "artifact dir not found" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_stale_report_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest stale report" in names
    assert "Upload Plan 2.8 digest stale report" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest stale report")
    assert "plan_2_8_digest_stale_report.py" in step["run"]
