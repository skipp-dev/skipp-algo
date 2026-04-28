"""Tests for ``scripts/plan_2_8_weekly_index.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_index.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_weekly_index", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_index"] = mod
    spec.loader.exec_module(mod)
    return mod


wi = _load()


def test_scan_empty_dir(tmp_path: Path) -> None:
    rep = wi.scan(tmp_path)
    assert rep["counts"]["files"] == 0
    assert rep["counts"]["total_size"] == 0
    assert rep["entries"] == []


def test_scan_missing_dir(tmp_path: Path) -> None:
    rep = wi.scan(tmp_path / "nope")
    assert rep["counts"]["files"] == 0


def test_scan_lists_files_sorted(tmp_path: Path) -> None:
    (tmp_path / "b.md").write_text("bb", encoding="utf-8")
    (tmp_path / "a.md").write_text("aaaa", encoding="utf-8")
    rep = wi.scan(tmp_path)
    paths = [e["path"] for e in rep["entries"]]
    assert paths == ["a.md", "b.md"]
    sizes = {e["path"]: e["size"] for e in rep["entries"]}
    assert sizes["a.md"] == 4 and sizes["b.md"] == 2
    assert rep["counts"]["total_size"] == 6


def test_scan_recurses_subdirs(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.json").write_text("{}", encoding="utf-8")
    rep = wi.scan(tmp_path)
    assert any(e["path"] == "sub/c.json" for e in rep["entries"])


def test_render_markdown_empty() -> None:
    rep = wi.scan(Path("/nonexistent/xyzzy"))
    md = wi.render_markdown(rep)
    assert "No artifacts present" in md
    assert "files:      0" in md


def test_render_markdown_with_entries(tmp_path: Path) -> None:
    (tmp_path / "x.md").write_text("hi", encoding="utf-8")
    rep = wi.scan(tmp_path)
    md = wi.render_markdown(rep)
    assert "| path | size" in md
    assert "`x.md`" in md


def test_cli_md_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    out = tmp_path / "i.md"
    rc = wi.main([
        "--artifact-dir", str(tmp_path), "--output", str(out),
    ])
    assert rc == 0
    assert "`a.txt`" in out.read_text(encoding="utf-8")


def test_cli_json_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    rc = wi.main([
        "--artifact-dir", str(tmp_path), "--format", "json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["files"] == 1


def test_cli_fail_on_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = wi.main([
        "--artifact-dir", str(tmp_path / "nope"),
        "--fail-on-empty",
    ])
    assert rc == 1


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_index_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly artifact index" in names
    assert "Upload Plan 2.8 weekly artifact index" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 weekly artifact index")
    assert "plan_2_8_weekly_index.py" in step["run"]
