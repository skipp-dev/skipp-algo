"""Tests for ``scripts/plan_2_8_trend_threshold_alert.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_trend_threshold_alert.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_trend_threshold_alert", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_trend_threshold_alert"] = mod
    spec.loader.exec_module(mod)
    return mod


ta = _load()


def _trend(weeks: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": 1, "weeks": weeks, "skipped": 0}


def test_passes_when_above_threshold() -> None:
    rep = ta.evaluate(
        _trend([{"week": "2026-W17", "total": 10,
                 "green": 9, "green_pct": 90.0}]),
        threshold=85.0,
    )
    assert rep["passed"] is True
    assert rep["latest_pct"] == 90.0


def test_fails_when_below() -> None:
    rep = ta.evaluate(
        _trend([{"week": "2026-W17", "total": 10,
                 "green": 5, "green_pct": 50.0}]),
        threshold=90.0,
    )
    assert rep["passed"] is False


def test_equal_to_threshold_passes() -> None:
    rep = ta.evaluate(
        _trend([{"week": "2026-W17", "green_pct": 90.0}]),
        threshold=90.0,
    )
    assert rep["passed"] is True


def test_empty_weeks_fails() -> None:
    rep = ta.evaluate(_trend([]), threshold=0.0)
    assert rep["passed"] is False
    assert rep["latest_week"] is None


def test_uses_last_week() -> None:
    rep = ta.evaluate(
        _trend([
            {"week": "2026-W16", "green_pct": 50.0},
            {"week": "2026-W17", "green_pct": 100.0},
        ]),
        threshold=90.0,
    )
    assert rep["latest_week"] == "2026-W17"
    assert rep["passed"] is True


def test_markdown_pass() -> None:
    rep = ta.evaluate(
        _trend([{"week": "X", "green_pct": 95.0}]),
        threshold=90.0,
    )
    md = ta.render_markdown(rep)
    assert "PASS" in md


def test_markdown_fail() -> None:
    rep = ta.evaluate(
        _trend([{"week": "X", "green_pct": 50.0}]),
        threshold=90.0,
    )
    md = ta.render_markdown(rep)
    assert "FAIL" in md


def test_cli_fail_below(tmp_path: Path) -> None:
    path = tmp_path / "t.json"
    path.write_text(
        json.dumps(_trend([{"week": "X", "green_pct": 50.0}])),
        encoding="utf-8",
    )
    rc = ta.main([
        "--trend-json", str(path),
        "--threshold", "90",
        "--fail-below",
    ])
    assert rc == 1


def test_cli_fail_below_pass(tmp_path: Path) -> None:
    path = tmp_path / "t.json"
    path.write_text(
        json.dumps(_trend([{"week": "X", "green_pct": 95.0}])),
        encoding="utf-8",
    )
    rc = ta.main([
        "--trend-json", str(path),
        "--threshold", "90",
        "--fail-below",
    ])
    assert rc == 0


def test_cli_missing_trend(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ta.main([
        "--trend-json", str(tmp_path / "nope.json"),
    ])
    assert rc == 1
    assert "trend JSON not found" in capsys.readouterr().err


def test_cli_invalid_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "t.json"
    path.write_text("not json", encoding="utf-8")
    rc = ta.main(["--trend-json", str(path)])
    assert rc == 1
    assert "invalid trend JSON" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_threshold_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 trend-threshold alert" in names
    assert "Upload Plan 2.8 trend-threshold alert" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 trend-threshold alert")
    assert "plan_2_8_trend_threshold_alert.py" in step["run"]
    assert "--threshold  90" in step["run"]
