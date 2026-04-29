"""Tests for ``scripts/plan_2_8_metadata_diff.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_metadata_diff.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_metadata_diff", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_metadata_diff"] = mod
    spec.loader.exec_module(mod)
    return mod


md = _load()


def _payload(scripts: list[tuple[str, int]], *,
             python: str = "3.13.0") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "python":         python,
        "platform":       "Linux",
        "scripts":        [{"name": n, "size": s, "mtime": "x"}
                           for n, s in scripts],
    }


def test_identical_no_changes() -> None:
    prior = _payload([("a.py", 100), ("b.py", 200)])
    rep = md.diff(prior, prior)
    assert rep["added"] == []
    assert rep["removed"] == []
    assert rep["changed"] == []


def test_added_and_removed() -> None:
    prior = _payload([("a.py", 100)])
    cur = _payload([("a.py", 100), ("b.py", 200)])
    rep = md.diff(prior, cur)
    assert rep["added"] == ["b.py"]
    assert rep["removed"] == []
    rep2 = md.diff(cur, prior)
    assert rep2["removed"] == ["b.py"]


def test_size_change_delta() -> None:
    rep = md.diff(
        _payload([("a.py", 100)]),
        _payload([("a.py", 150)]),
    )
    assert len(rep["changed"]) == 1
    assert rep["changed"][0]["delta"] == 50


def test_python_version_tracked() -> None:
    rep = md.diff(
        _payload([], python="3.12.0"),
        _payload([], python="3.13.0"),
    )
    assert rep["python_prior"] == "3.12.0"
    assert rep["python_current"] == "3.13.0"


def test_markdown_shape() -> None:
    rep = md.diff(
        _payload([("a.py", 100)]),
        _payload([("a.py", 200), ("b.py", 50)]),
    )
    out = md.render_markdown(rep)
    assert "## Added" in out
    assert "## Size changes" in out
    assert "b.py" in out


def test_markdown_clean() -> None:
    prior = _payload([("a.py", 100)])
    out = md.render_markdown(md.diff(prior, prior))
    assert "No script changes" in out


def test_cli_fail_on_change(tmp_path: Path) -> None:
    prior = tmp_path / "p.json"
    cur = tmp_path / "c.json"
    prior.write_text(json.dumps(_payload([("a.py", 100)])),
                     encoding="utf-8")
    cur.write_text(json.dumps(_payload([("a.py", 200)])),
                   encoding="utf-8")
    rc = md.main([
        "--prior", str(prior), "--current", str(cur),
        "--fail-on-change",
    ])
    assert rc == 1


def test_cli_fail_on_change_clean(tmp_path: Path) -> None:
    prior = tmp_path / "p.json"
    cur = tmp_path / "c.json"
    data = json.dumps(_payload([("a.py", 100)]))
    prior.write_text(data, encoding="utf-8")
    cur.write_text(data, encoding="utf-8")
    rc = md.main([
        "--prior", str(prior), "--current", str(cur),
        "--fail-on-change",
    ])
    assert rc == 0


def test_cli_missing_current(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = md.main([
        "--prior", str(tmp_path / "p.json"),
        "--current", str(tmp_path / "c.json"),
    ])
    assert rc == 1
    assert "current not found" in capsys.readouterr().err


def test_cli_missing_prior_treated_as_empty(tmp_path: Path) -> None:
    cur = tmp_path / "c.json"
    cur.write_text(json.dumps(_payload([("a.py", 100)])),
                   encoding="utf-8")
    out = tmp_path / "o.md"
    rc = md.main([
        "--prior", str(tmp_path / "nope.json"),
        "--current", str(cur),
        "--format", "md",
        "--output", str(out),
    ])
    assert rc == 0
    assert "a.py" in out.read_text(encoding="utf-8")


def test_malformed_prior_treated_as_empty(tmp_path: Path) -> None:
    prior = tmp_path / "p.json"
    prior.write_text("not-json", encoding="utf-8")
    cur = tmp_path / "c.json"
    cur.write_text(json.dumps(_payload([("a.py", 100)])),
                   encoding="utf-8")
    rc = md.main([
        "--prior", str(prior), "--current", str(cur),
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


def test_weekly_has_metadata_diff_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Download prior Plan 2.8 metadata" in names
    assert "Plan 2.8 metadata diff" in names
    assert "Upload Plan 2.8 metadata diff" in names
