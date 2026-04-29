"""Tests for ``scripts/plan_2_8_status_snapshot.py`` + batch #68 wiring."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_status_snapshot.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_status_snapshot", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_status_snapshot"] = mod
    spec.loader.exec_module(mod)
    return mod


snap = _load()


def test_all_inputs_populated() -> None:
    rep = snap.snapshot(
        health       ={"status": "green", "score": 1.0},
        runcard_index={"counts": {"present": 5, "total": 8}},
        coverage     ={"counts": {"under": 0, "total": 20}},
        digest       ={"alerts": [{}, {}]},
    )
    assert rep["status"] == "green"
    assert rep["score"] == 1.0
    assert rep["signals"]["alerts"] == 2
    assert rep["signals"]["runcard_present"] == 5
    assert rep["signals"]["runcard_total"] == 8
    assert all(rep["inputs_seen"].values())


def test_all_inputs_missing_returns_defaults() -> None:
    rep = snap.snapshot(None, None, None, None)
    assert rep["status"] is None
    assert rep["score"] is None
    assert rep["signals"]["alerts"] == 0
    assert rep["signals"]["runcard_total"] == 0
    assert not any(rep["inputs_seen"].values())


def test_partial_inputs_mark_missing() -> None:
    rep = snap.snapshot(
        {"status": "amber", "score": 0.7}, None,
        {"counts": {"under": 1, "total": 10}}, None,
    )
    assert rep["inputs_seen"] == {
        "health": True, "runcard_index": False,
        "coverage": True, "digest": False,
    }


def test_render_markdown_with_score() -> None:
    rep = snap.snapshot(
        {"status": "green", "score": 0.5},
        {"counts": {"present": 1, "total": 2}},
        {"counts": {"under": 0, "total": 3}},
        {"alerts": []},
    )
    md = snap.render_markdown(rep)
    assert "**green**" in md
    assert "0.50" in md
    assert "runcard sections: 1/2" in md


def test_render_markdown_unknown_and_missing() -> None:
    rep = snap.snapshot(None, None, None, None)
    md = snap.render_markdown(rep)
    assert "**unknown**" in md
    assert "n/a" in md
    assert "missing inputs" in md


def _seed(dir_: Path, name: str, data: dict[str, Any]) -> Path:
    p = dir_ / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_cli_json_single_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    h = _seed(tmp_path, "h.json", {"status": "green", "score": 1.0})
    r = _seed(tmp_path, "r.json", {"counts": {"present": 3, "total": 5}})
    c = _seed(tmp_path, "c.json", {"counts": {"under": 0, "total": 8}})
    d = _seed(tmp_path, "d.json", {"alerts": []})
    rc = snap.main([
        "--health", str(h), "--runcard-index", str(r),
        "--coverage", str(c), "--digest", str(d),
    ])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert "\n" not in out  # single-line JSON output
    payload = json.loads(out)
    assert payload["status"] == "green"


def test_cli_md_output(tmp_path: Path) -> None:
    h = _seed(tmp_path, "h.json", {"status": "amber", "score": 0.5})
    out = tmp_path / "snap.md"
    rc = snap.main([
        "--health", str(h), "--format", "md", "--output", str(out),
    ])
    assert rc == 0
    assert "**amber**" in out.read_text(encoding="utf-8")


def test_cli_tolerates_missing_inputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = snap.main([])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] is None


def test_cli_ignores_malformed_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not-json", encoding="utf-8")
    rc = snap.main([
        "--health", str(bad),
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["inputs_seen"]["health"] is False


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_heatmap_step() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 alert-history heatmap (90-day window)" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 alert-history heatmap (90-day window)")
    assert "plan_2_8_alert_history_heatmap.py" in step["run"]
    assert "--lookback-days  90" in step["run"]
