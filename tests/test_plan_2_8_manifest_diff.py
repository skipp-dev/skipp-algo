"""Tests for ``scripts/plan_2_8_manifest_diff.py`` + #73 wiring."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_manifest_diff.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_manifest_diff", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_manifest_diff"] = mod
    spec.loader.exec_module(mod)
    return mod


md_mod = _load()


def _m(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "counts":         {"scripts": len(entries)},
        "entries":        entries,
    }


def _entry(script: str, *, has_test: bool = True,
           flags: list[str] = ()) -> dict[str, Any]:
    return {
        "script":    script,
        "test":      f"tests/test_{Path(script).stem}.py" if has_test else None,
        "has_test":  has_test,
        "cli_flags": list(flags),
    }


def test_diff_added_and_removed() -> None:
    base = _m([_entry("scripts/plan_2_8_alpha.py")])
    curr = _m([_entry("scripts/plan_2_8_beta.py")])
    rep = md_mod.diff(base, curr)
    assert rep["added_scripts"] == ["scripts/plan_2_8_beta.py"]
    assert rep["removed_scripts"] == ["scripts/plan_2_8_alpha.py"]


def test_diff_newly_testless() -> None:
    base = _m([_entry("scripts/plan_2_8_x.py", has_test=True)])
    curr = _m([_entry("scripts/plan_2_8_x.py", has_test=False)])
    rep = md_mod.diff(base, curr)
    assert rep["newly_testless"] == ["scripts/plan_2_8_x.py"]
    assert rep["newly_tested"] == []


def test_diff_newly_tested() -> None:
    base = _m([_entry("scripts/plan_2_8_x.py", has_test=False)])
    curr = _m([_entry("scripts/plan_2_8_x.py", has_test=True)])
    rep = md_mod.diff(base, curr)
    assert rep["newly_tested"] == ["scripts/plan_2_8_x.py"]


def test_diff_flag_changes() -> None:
    base = _m([_entry("scripts/plan_2_8_x.py", flags=["--a", "--b"])])
    curr = _m([_entry("scripts/plan_2_8_x.py", flags=["--a", "--c"])])
    rep = md_mod.diff(base, curr)
    assert rep["counts"]["flag_changes"] == 1
    entry = rep["flag_changes"][0]
    assert entry["added_flags"] == ["--c"]
    assert entry["removed_flags"] == ["--b"]


def test_diff_ignores_flag_order() -> None:
    base = _m([_entry("scripts/plan_2_8_x.py", flags=["--a", "--b"])])
    curr = _m([_entry("scripts/plan_2_8_x.py", flags=["--a", "--b"])])
    rep = md_mod.diff(base, curr)
    assert rep["counts"]["flag_changes"] == 0


def test_diff_empty_baseline() -> None:
    rep = md_mod.diff(_m([]), _m([_entry("scripts/plan_2_8_x.py")]))
    assert rep["counts"]["added_scripts"] == 1
    assert rep["counts"]["removed_scripts"] == 0


def test_render_markdown_sections() -> None:
    base = _m([_entry("scripts/plan_2_8_gone.py")])
    curr = _m([
        _entry("scripts/plan_2_8_new.py"),
        _entry("scripts/plan_2_8_flagged.py", flags=["--x"]),
    ])
    md = md_mod.render_markdown(md_mod.diff(base, curr))
    assert "## Added scripts (2)" in md
    assert "## Removed scripts (1)" in md
    assert "_none_" in md  # empty flag-changes section


def test_render_markdown_flag_changes_table() -> None:
    base = _m([_entry("scripts/plan_2_8_x.py", flags=["--a"])])
    curr = _m([_entry("scripts/plan_2_8_x.py", flags=["--a", "--b"])])
    md = md_mod.render_markdown(md_mod.diff(base, curr))
    assert "| script | added | removed |" in md
    assert "`--b`" in md


def _seed(tmp: Path, name: str, manifest: dict[str, Any]) -> Path:
    p = tmp / name
    p.write_text(json.dumps(manifest), encoding="utf-8")
    return p


def test_cli_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = _seed(tmp_path, "b.json",
                 _m([_entry("scripts/plan_2_8_a.py")]))
    curr = _seed(tmp_path, "c.json",
                 _m([_entry("scripts/plan_2_8_a.py"),
                     _entry("scripts/plan_2_8_b.py")]))
    rc = md_mod.main([
        "--baseline", str(base), "--current", str(curr),
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["added_scripts"] == 1


def test_cli_md_output(tmp_path: Path) -> None:
    base = _seed(tmp_path, "b.json", _m([]))
    curr = _seed(tmp_path, "c.json", _m([_entry("scripts/plan_2_8_a.py")]))
    out = tmp_path / "d.md"
    rc = md_mod.main([
        "--baseline", str(base), "--current", str(curr),
        "--format", "md", "--output", str(out),
    ])
    assert rc == 0
    assert "Plan 2.8 manifest diff" in out.read_text(encoding="utf-8")


def test_cli_fail_on_regression_removed(tmp_path: Path) -> None:
    base = _seed(tmp_path, "b.json", _m([_entry("scripts/plan_2_8_x.py")]))
    curr = _seed(tmp_path, "c.json", _m([]))
    rc = md_mod.main([
        "--baseline", str(base), "--current", str(curr),
        "--fail-on-regression",
    ])
    assert rc == 1


def test_cli_fail_on_regression_testless(tmp_path: Path) -> None:
    base = _seed(tmp_path, "b.json",
                 _m([_entry("scripts/plan_2_8_x.py", has_test=True)]))
    curr = _seed(tmp_path, "c.json",
                 _m([_entry("scripts/plan_2_8_x.py", has_test=False)]))
    rc = md_mod.main([
        "--baseline", str(base), "--current", str(curr),
        "--fail-on-regression",
    ])
    assert rc == 1


def test_cli_fail_on_regression_passes_when_clean(tmp_path: Path) -> None:
    base = _seed(tmp_path, "b.json", _m([_entry("scripts/plan_2_8_x.py")]))
    curr = _seed(tmp_path, "c.json",
                 _m([_entry("scripts/plan_2_8_x.py"),
                     _entry("scripts/plan_2_8_y.py")]))
    rc = md_mod.main([
        "--baseline", str(base), "--current", str(curr),
        "--fail-on-regression",
    ])
    assert rc == 0


def test_cli_missing_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    curr = _seed(tmp_path, "c.json", _m([]))
    rc = md_mod.main([
        "--baseline", str(tmp_path / "nope.json"), "--current", str(curr),
    ])
    assert rc == 1
    assert "manifest not found" in capsys.readouterr().err


def test_cli_invalid_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    curr = _seed(tmp_path, "c.json", _m([]))
    rc = md_mod.main([
        "--baseline", str(bad), "--current", str(curr),
    ])
    assert rc == 1
    assert "invalid manifest" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_snooze_expiry_step() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 snooze expiry report" in names
    assert "Upload Plan 2.8 snooze expiry report" in names


def test_weekly_has_manifest_and_diff_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 script manifest" in names
    assert "Upload Plan 2.8 script manifest" in names
    assert "Download prior Plan 2.8 manifest" in names
    assert "Plan 2.8 manifest diff" in names
    assert "Upload Plan 2.8 manifest diff" in names
    step = next(s for s in steps if s.get("name") == "Plan 2.8 manifest diff")
    assert "plan_2_8_manifest_diff.py" in step["run"]
