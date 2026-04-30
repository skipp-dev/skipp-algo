"""Tests for ``scripts/plan_2_8_digest_index_compare.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_index_compare.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_digest_index_compare", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_index_compare"] = mod
    spec.loader.exec_module(mod)
    return mod


ic = _load()


def _write(path: Path, entries: list[dict[str, Any]]) -> Path:
    path.write_text(json.dumps({
        "schema_version": 1, "entries": entries,
    }), encoding="utf-8")
    return path


def test_no_prior_all_added(tmp_path: Path) -> None:
    prior = {}
    current = {"a.md": 10, "b.md": 20}
    rep = ic.diff(prior, current)
    assert rep["counts"] == {"added": 2, "removed": 0, "changed": 0}
    assert rep["added"] == ["a.md", "b.md"]


def test_all_removed() -> None:
    rep = ic.diff({"x.md": 5}, {})
    assert rep["counts"]["removed"] == 1
    assert rep["removed"] == ["x.md"]


def test_size_change_reported() -> None:
    rep = ic.diff({"a.md": 10}, {"a.md": 25})
    assert rep["counts"]["changed"] == 1
    row = rep["changed"][0]
    assert row["before"] == 10
    assert row["after"] == 25
    assert row["delta"] == 15


def test_no_change_reports_nothing() -> None:
    rep = ic.diff({"a.md": 10}, {"a.md": 10})
    assert all(v == 0 for v in rep["counts"].values())


def test_added_removed_sorted() -> None:
    rep = ic.diff(
        {"z.md": 1, "a.md": 1},
        {"b.md": 2, "m.md": 2},
    )
    assert rep["added"] == ["b.md", "m.md"]
    assert rep["removed"] == ["a.md", "z.md"]


def test_load_missing_file_returns_empty(tmp_path: Path) -> None:
    assert ic._load(tmp_path / "nope.json") == {}


def test_load_bad_json_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("not-json", encoding="utf-8")
    assert ic._load(p) == {}


def test_load_non_object_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "arr.json"
    p.write_text("[1,2]", encoding="utf-8")
    assert ic._load(p) == {}


def test_load_skips_malformed_entries(tmp_path: Path) -> None:
    p = _write(tmp_path / "x.json", [
        {"path": "a.md", "size": 10},
        {"path": "bad"},  # missing size
        "nope",
        {"path": 123, "size": 5},
    ])
    result = ic._load(p)
    assert result == {"a.md": 10}


def test_render_markdown_no_diff() -> None:
    md = ic.render_markdown(ic.diff({}, {}))
    assert "No differences" in md


def test_render_markdown_with_diff() -> None:
    rep = ic.diff({"a.md": 10}, {"a.md": 15, "b.md": 5})
    md = ic.render_markdown(rep)
    assert "## Added" in md
    assert "## Changed" in md
    assert "delta +5" in md


def test_cli_writes_file(tmp_path: Path) -> None:
    prior = _write(tmp_path / "p.json", [{"path": "a.md", "size": 10}])
    curr = _write(tmp_path / "c.json", [{"path": "a.md", "size": 20}])
    out = tmp_path / "d.md"
    rc = ic.main([
        "--prior", str(prior), "--current", str(curr),
        "--output", str(out),
    ])
    assert rc == 0
    assert "delta +10" in out.read_text(encoding="utf-8")


def test_cli_fail_on_change(tmp_path: Path) -> None:
    prior = _write(tmp_path / "p.json", [{"path": "a.md", "size": 10}])
    curr = _write(tmp_path / "c.json", [{"path": "a.md", "size": 11}])
    rc = ic.main([
        "--prior", str(prior), "--current", str(curr),
        "--fail-on-change",
    ])
    assert rc == 1


def test_cli_no_change_success(tmp_path: Path) -> None:
    prior = _write(tmp_path / "p.json", [{"path": "a.md", "size": 10}])
    curr = _write(tmp_path / "c.json", [{"path": "a.md", "size": 10}])
    rc = ic.main([
        "--prior", str(prior), "--current", str(curr),
        "--fail-on-change",
    ])
    assert rc == 0


def test_cli_missing_current(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    prior = _write(tmp_path / "p.json", [])
    rc = ic.main([
        "--prior", str(prior),
        "--current", str(tmp_path / "nope.json"),
    ])
    assert rc == 1
    assert "current not found" in capsys.readouterr().err


def test_cli_missing_prior_treated_as_empty(tmp_path: Path) -> None:
    curr = _write(tmp_path / "c.json", [{"path": "a.md", "size": 10}])
    rc = ic.main([
        "--prior", str(tmp_path / "nope.json"),
        "--current", str(curr),
    ])
    assert rc == 0


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_index_diff_step() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly-index diff" in names
    assert "Upload Plan 2.8 weekly-index diff" in names
    assert "Download prior Plan 2.8 weekly index" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 weekly-index diff")
    assert "plan_2_8_digest_index_compare.py" in step["run"]
