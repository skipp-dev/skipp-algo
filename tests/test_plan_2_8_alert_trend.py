"""Tests for ``scripts/plan_2_8_alert_trend.py`` + #75 wiring."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_alert_trend.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_alert_trend", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_alert_trend"] = mod
    spec.loader.exec_module(mod)
    return mod


at = _load()


def _alert(tf: str = "5m", fam: str = "HR", *,
           hr: float = 55.0, ev: int = 100) -> dict[str, Any]:
    return {
        "tf": tf, "family": fam,
        "hit_rate_pct": hr, "delta_pp": 0.5,
        "events": ev, "severity": "info",
    }


def _digest(day: str, alerts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "captured_at":    f"{day}T00:00:00+00:00",
        "scoring_root":   "master",
        "alerts":         alerts,
    }


def _seed(tmp: Path, digests: list[tuple[str, dict[str, Any]]]) -> Path:
    arc = tmp / "arc"
    arc.mkdir()
    for name, d in digests:
        (arc / name).write_text(json.dumps(d), encoding="utf-8")
    return arc


def test_direction_rising_when_hit_rate_up() -> None:
    rep = at.build(
        _digest("2026-04-20", [_alert(hr=60)]),
        _digest("2026-04-13", [_alert(hr=55)]),
    )
    assert rep["counts"]["rising"] == 1
    assert rep["entries"][0]["direction"] == "rising"
    assert rep["entries"][0]["hit_rate_delta"] == pytest.approx(5.0)


def test_direction_falling_when_hit_rate_down() -> None:
    rep = at.build(
        _digest("2026-04-20", [_alert(hr=50)]),
        _digest("2026-04-13", [_alert(hr=55)]),
    )
    assert rep["counts"]["falling"] == 1


def test_direction_flat_when_equal() -> None:
    rep = at.build(
        _digest("2026-04-20", [_alert(hr=55)]),
        _digest("2026-04-13", [_alert(hr=55)]),
    )
    assert rep["counts"]["flat"] == 1
    assert rep["entries"][0]["direction"] == "flat"


def test_new_entry_when_missing_from_prev() -> None:
    rep = at.build(
        _digest("2026-04-20", [_alert(tf="5m", fam="HR")]),
        _digest("2026-04-13", []),
    )
    assert rep["counts"]["new"] == 1
    assert rep["entries"][0]["direction"] == "new"
    assert rep["entries"][0]["prev_hit_rate"] is None


def test_gone_entry_when_missing_from_latest() -> None:
    rep = at.build(
        _digest("2026-04-20", []),
        _digest("2026-04-13", [_alert(tf="5m", fam="HR")]),
    )
    assert rep["counts"]["gone"] == 1
    assert rep["entries"][0]["direction"] == "gone"
    assert rep["entries"][0]["latest_hit_rate"] is None


def test_handles_none_prev_gracefully() -> None:
    rep = at.build(_digest("2026-04-20", [_alert()]), None)
    assert rep["counts"]["new"] == 1


def test_handles_none_latest_gracefully() -> None:
    rep = at.build(None, _digest("2026-04-13", [_alert()]))
    assert rep["counts"]["gone"] == 1


def test_index_ignores_non_string_keys() -> None:
    bad = _digest("2026-04-20", [
        {"tf": 5, "family": "HR", "hit_rate_pct": 1,
         "delta_pp": 0, "events": 1, "severity": "info"},
        _alert(),
    ])
    rep = at.build(bad, _digest("2026-04-13", []))
    assert rep["counts"]["new"] == 1  # only the well-formed one


def test_render_markdown_empty() -> None:
    md = at.render_markdown(at.build(None, None))
    assert "No alerts tracked" in md


def test_render_markdown_table() -> None:
    rep = at.build(
        _digest("2026-04-20", [_alert(hr=60)]),
        _digest("2026-04-13", [_alert(hr=55)]),
    )
    md = at.render_markdown(rep)
    assert "| tf | family | latest ev |" in md
    assert "rising" in md
    assert "5.00" in md


def test_latest_two_picks_last_sorted(tmp_path: Path) -> None:
    arc = _seed(tmp_path, [
        ("2026-04-06.json", _digest("2026-04-06", [])),
        ("2026-04-13.json", _digest("2026-04-13", [_alert(hr=55)])),
        ("2026-04-20.json", _digest("2026-04-20", [_alert(hr=60)])),
    ])
    files = at._latest_two(arc)
    names = [p.name for p in files]
    assert names == ["2026-04-13.json", "2026-04-20.json"]


def test_load_archive_tolerates_bad_json(tmp_path: Path) -> None:
    bad = tmp_path / "b.json"
    bad.write_text("not json", encoding="utf-8")
    assert at._load_archive(bad) is None


def test_cli_md_output(tmp_path: Path) -> None:
    arc = _seed(tmp_path, [
        ("2026-04-13.json", _digest("2026-04-13", [_alert(hr=55)])),
        ("2026-04-20.json", _digest("2026-04-20", [_alert(hr=60)])),
    ])
    out = tmp_path / "t.md"
    rc = at.main([
        "--archive-dir", str(arc), "--output", str(out),
    ])
    assert rc == 0
    assert "Plan 2.8 alert trend" in out.read_text(encoding="utf-8")


def test_cli_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    arc = _seed(tmp_path, [
        ("2026-04-13.json", _digest("2026-04-13", [_alert(hr=55)])),
        ("2026-04-20.json", _digest("2026-04-20", [_alert(hr=60)])),
    ])
    rc = at.main([
        "--archive-dir", str(arc), "--format", "json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["rising"] == 1


def test_cli_fail_on_empty(tmp_path: Path) -> None:
    arc = tmp_path / "empty"
    arc.mkdir()
    rc = at.main([
        "--archive-dir", str(arc), "--fail-on-empty",
    ])
    assert rc == 1


def test_cli_missing_archive_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = at.main(["--archive-dir", str(tmp_path / "nope")])
    assert rc == 1
    assert "archive-dir not found" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_alert_trend_step() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 alert trend" in names
    assert "Upload Plan 2.8 alert trend" in names
    step = next(s for s in steps if s.get("name") == "Plan 2.8 alert trend")
    assert "plan_2_8_alert_trend.py" in step["run"]
