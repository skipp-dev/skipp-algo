"""Tests for ``scripts/plan_2_8_digest_archive_index.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_archive_index.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_digest_archive_index", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_archive_index"] = mod
    spec.loader.exec_module(mod)
    return mod


ai = _load()


def test_scan_missing_dir(tmp_path: Path) -> None:
    rep = ai.scan(tmp_path / "nope")
    assert rep["counts"]["snapshots"] == 0


def test_scan_empty_dir(tmp_path: Path) -> None:
    rep = ai.scan(tmp_path)
    assert rep["entries"] == []


def test_scan_lists_snapshots(tmp_path: Path) -> None:
    s1 = tmp_path / "run-1"
    s1.mkdir()
    (s1 / "a.txt").write_bytes(b"hi")
    (s1 / "b.txt").write_bytes(b"lo")
    s2 = tmp_path / "run-2"
    s2.mkdir()
    (s2 / "c.txt").write_bytes(b"1")
    rep = ai.scan(tmp_path)
    names = [e["name"] for e in rep["entries"]]
    assert names == ["run-1", "run-2"]
    by_name = {e["name"]: e for e in rep["entries"]}
    assert by_name["run-1"]["files"] == 2
    assert by_name["run-1"]["total_size"] == 4
    assert by_name["run-2"]["files"] == 1


def test_scan_ignores_loose_files(tmp_path: Path) -> None:
    (tmp_path / "loose.txt").write_bytes(b"x")
    (tmp_path / "run-a").mkdir()
    rep = ai.scan(tmp_path)
    names = [e["name"] for e in rep["entries"]]
    assert names == ["run-a"]


def test_scan_recurses_within_snapshot(tmp_path: Path) -> None:
    snap = tmp_path / "run"
    (snap / "sub").mkdir(parents=True)
    (snap / "sub" / "f.txt").write_bytes(b"abc")
    rep = ai.scan(tmp_path)
    assert rep["entries"][0]["files"] == 1
    assert rep["entries"][0]["total_size"] == 3


def test_totals_aggregated() -> None:
    rep = {"entries": [
        {"name": "a", "files": 2, "total_size": 10},
        {"name": "b", "files": 1, "total_size": 5},
    ]}
    total = sum(e["total_size"] for e in rep["entries"])
    assert total == 15


def test_render_markdown_empty() -> None:
    md = ai.render_markdown(ai.scan(Path("/nonexistent/xyzzy")))
    assert "No archive snapshots" in md


def test_render_markdown_with_rows(tmp_path: Path) -> None:
    snap = tmp_path / "run-x"
    snap.mkdir()
    (snap / "a.txt").write_bytes(b"hi")
    md = ai.render_markdown(ai.scan(tmp_path))
    assert "| `run-x` | 1 | 2 |" in md


def test_cli_md_output(tmp_path: Path) -> None:
    snap = tmp_path / "run-x"
    snap.mkdir()
    (snap / "a.txt").write_bytes(b"hi")
    out = tmp_path / "idx.md"
    rc = ai.main([
        "--archive-dir", str(tmp_path), "--output", str(out),
    ])
    assert rc == 0
    assert "run-x" in out.read_text(encoding="utf-8")


def test_cli_json_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    snap = tmp_path / "run-y"
    snap.mkdir()
    (snap / "a.txt").write_bytes(b"hi")
    rc = ai.main([
        "--archive-dir", str(tmp_path), "--format", "json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["snapshots"] == 1


def test_cli_fail_on_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ai.main([
        "--archive-dir", str(tmp_path),
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


def test_weekly_has_archive_index_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest archive index" in names
    assert "Upload Plan 2.8 digest archive index" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest archive index")
    assert "plan_2_8_digest_archive_index.py" in step["run"]
