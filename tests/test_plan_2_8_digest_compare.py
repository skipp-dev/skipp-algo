"""Tests for ``scripts/plan_2_8_digest_compare.py`` + batch #67 wiring."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_compare.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_digest_compare", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_compare"] = mod
    spec.loader.exec_module(mod)
    return mod


cmp_mod = _load()


def _alert(tf: str, fam: str, d: float = 0.01) -> dict[str, Any]:
    return {"tf": tf, "family": fam, "delta_pp": d}


def test_added_and_removed_detected() -> None:
    base = {"alerts": [_alert("5m", "HR"), _alert("15m", "HR")]}
    cur  = {"alerts": [_alert("15m", "HR"), _alert("1h", "FVG")]}
    rep = cmp_mod.compare(base, cur)
    assert rep["counts"]["added"] == 1
    assert rep["counts"]["removed"] == 1
    assert rep["counts"]["persistent"] == 1


def test_all_persistent() -> None:
    a = [_alert("5m", "HR"), _alert("15m", "HR")]
    rep = cmp_mod.compare({"alerts": a}, {"alerts": a})
    assert rep["counts"] == {
        "baseline": 2, "current": 2, "added": 0, "removed": 0, "persistent": 2,
    }


def test_empty_on_both_sides() -> None:
    rep = cmp_mod.compare({"alerts": []}, {"alerts": []})
    assert rep["counts"]["added"] == 0
    assert rep["counts"]["removed"] == 0
    assert rep["counts"]["persistent"] == 0


def test_missing_tf_or_family_are_skipped() -> None:
    base = {"alerts": [{"tf": "", "family": "HR"}, _alert("5m", "HR")]}
    cur  = {"alerts": [_alert("5m", "HR")]}
    rep = cmp_mod.compare(base, cur)
    assert rep["counts"]["baseline"] == 1
    assert rep["counts"]["persistent"] == 1


def test_sorted_output() -> None:
    base = {"alerts": []}
    cur  = {"alerts": [_alert("5m", "HR"), _alert("1h", "FVG"),
                       _alert("15m", "HR")]}
    rep = cmp_mod.compare(base, cur)
    keys = [(a["tf"], a["family"]) for a in rep["added"]]
    assert keys == sorted(keys)


def test_render_markdown_sections() -> None:
    base = {"alerts": [_alert("5m", "HR")]}
    cur  = {"alerts": [_alert("1h", "FVG")]}
    md = cmp_mod.render_markdown(cmp_mod.compare(base, cur))
    assert "## Added (1)" in md
    assert "## Removed (1)" in md
    assert "## Persistent (0)" in md


def test_cli_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    b = tmp_path / "b.json"
    c = tmp_path / "c.json"
    b.write_text(json.dumps({"alerts": [_alert("5m", "HR")]}), encoding="utf-8")
    c.write_text(json.dumps({"alerts": [_alert("1h", "FVG")]}), encoding="utf-8")
    rc = cmp_mod.main([
        "--baseline", str(b), "--current", str(c), "--format", "json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["added"] == 1


def test_cli_fail_on_added(tmp_path: Path) -> None:
    b = tmp_path / "b.json"
    c = tmp_path / "c.json"
    b.write_text(json.dumps({"alerts": []}), encoding="utf-8")
    c.write_text(json.dumps({"alerts": [_alert("5m", "HR")]}), encoding="utf-8")
    rc = cmp_mod.main([
        "--baseline", str(b), "--current", str(c), "--fail-on-added",
    ])
    assert rc == 1


def test_cli_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    c = tmp_path / "c.json"
    c.write_text("{}", encoding="utf-8")
    rc = cmp_mod.main([
        "--baseline", str(tmp_path / "nope.json"), "--current", str(c),
    ])
    assert rc == 1
    assert "baseline not found" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_runcard_index_step() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 runcard section index" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 runcard section index")
    assert "plan_2_8_runcard_index.py" in step["run"]
    assert "runcard_index.json" in step["run"]


def test_weekly_has_changelog_slice_step() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 CHANGELOG slice (last 14 days)" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 CHANGELOG slice (last 14 days)")
    assert "plan_2_8_changelog_digest.py" in step["run"]
    assert "--lookback-days  14" in step["run"]
