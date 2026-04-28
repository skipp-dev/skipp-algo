"""Tests for ``scripts/plan_2_8_digest_artifact_age.py``."""

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
SCRIPT = REPO / "scripts" / "plan_2_8_digest_artifact_age.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_artifact_age", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_artifact_age"] = mod
    spec.loader.exec_module(mod)
    return mod


aa = _load()


def test_fresh_file_small_age(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    rep = aa.scan(tmp_path)
    assert rep["count"] == 1
    assert rep["entries"][0]["age_days"] < 1.0


def test_old_file_detected(tmp_path: Path) -> None:
    p = tmp_path / "a.md"
    p.write_text("x", encoding="utf-8")
    old = time.time() - 86400 * 5
    os.utime(p, (old, old))
    rep = aa.scan(tmp_path)
    assert rep["entries"][0]["age_days"] >= 4.5


def test_missing_dir(tmp_path: Path) -> None:
    rep = aa.scan(tmp_path / "nope")
    assert rep["count"] == 0
    assert rep["oldest_days"] == 0.0


def test_subdirectories_ignored(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.md").write_text("x", encoding="utf-8")
    rep = aa.scan(tmp_path)
    assert rep["count"] == 1


def test_markdown_shape(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    md = aa.render_markdown(aa.scan(tmp_path))
    assert "artifact age" in md
    assert "age (days)" in md


def test_markdown_empty_placeholder(tmp_path: Path) -> None:
    md = aa.render_markdown(aa.scan(tmp_path))
    assert "_none_" in md


def test_cli_fail_on_older_than(tmp_path: Path) -> None:
    p = tmp_path / "a.md"
    p.write_text("x", encoding="utf-8")
    old = time.time() - 86400 * 10
    os.utime(p, (old, old))
    rc = aa.main([
        "--artifact-dir", str(tmp_path),
        "--fail-on-older-than", "5",
    ])
    assert rc == 1


def test_cli_fail_on_older_than_clean(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    rc = aa.main([
        "--artifact-dir", str(tmp_path),
        "--fail-on-older-than", "5",
    ])
    assert rc == 0


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = aa.main([
        "--artifact-dir", str(tmp_path),
        "--format", "json",
        "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["count"] == 1


def test_cli_missing_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = aa.main(["--artifact-dir", str(tmp_path / "nope")])
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


def test_weekly_has_artifact_age_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest artifact age" in names
    assert "Upload Plan 2.8 digest artifact age" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest artifact age")
    assert "plan_2_8_digest_artifact_age.py" in step["run"]
