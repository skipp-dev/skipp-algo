"""Tests for ``scripts/plan_2_8_digest_metadata.py``."""

from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_metadata.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_metadata", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_metadata"] = mod
    spec.loader.exec_module(mod)
    return mod


dm = _load()


def test_collect_counts_scripts(tmp_path: Path) -> None:
    d = tmp_path / "scripts"
    d.mkdir()
    (d / "plan_2_8_foo.py").write_text("x", encoding="utf-8")
    (d / "plan_2_8_bar.py").write_text("x", encoding="utf-8")
    (d / "unrelated.py").write_text("x", encoding="utf-8")
    rep = dm.collect(d)
    assert rep["scripts_count"] == 2
    names = {e["name"] for e in rep["scripts"]}
    assert names == {"plan_2_8_foo.py", "plan_2_8_bar.py"}


def test_collect_captured_at_iso(tmp_path: Path) -> None:
    d = tmp_path / "scripts"
    d.mkdir()
    rep = dm.collect(
        d, now=_dt.datetime(2026, 4, 21, 12, 0,
                            tzinfo=_dt.UTC),
    )
    assert rep["captured_at"] == "2026-04-21T12:00:00Z"


def test_missing_scripts_dir_returns_empty(tmp_path: Path) -> None:
    rep = dm.collect(tmp_path / "nope")
    assert rep["scripts_count"] == 0
    assert rep["scripts"] == []


def test_entries_include_size_and_mtime(tmp_path: Path) -> None:
    d = tmp_path / "scripts"
    d.mkdir()
    (d / "plan_2_8_foo.py").write_text("hello", encoding="utf-8")
    rep = dm.collect(d)
    entry = rep["scripts"][0]
    assert entry["size"] == 5
    assert entry["mtime"].endswith("Z")


def test_markdown_shape(tmp_path: Path) -> None:
    d = tmp_path / "scripts"
    d.mkdir()
    md = dm.render_markdown(dm.collect(d))
    assert md.startswith("# Plan 2.8 digest metadata")
    assert "python:" in md


def test_cli_json(tmp_path: Path) -> None:
    d = tmp_path / "scripts"
    d.mkdir()
    out = tmp_path / "m.json"
    rc = dm.main([
        "--scripts-dir", str(d),
        "--format", "json",
        "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["scripts_count"] == 0
    assert "python" in payload


def test_cli_md(tmp_path: Path) -> None:
    d = tmp_path / "scripts"
    d.mkdir()
    out = tmp_path / "m.md"
    rc = dm.main([
        "--scripts-dir", str(d),
        "--format", "md",
        "--output", str(out),
    ])
    assert rc == 0
    assert "digest metadata" in out.read_text(encoding="utf-8")


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_metadata_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest metadata" in names
    assert "Upload Plan 2.8 digest metadata" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest metadata")
    assert "plan_2_8_digest_metadata.py" in step["run"]
