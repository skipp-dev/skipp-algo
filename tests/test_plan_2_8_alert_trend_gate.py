"""Tests for ``scripts/plan_2_8_alert_trend_gate.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_alert_trend_gate.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_alert_trend_gate", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_alert_trend_gate"] = mod
    spec.loader.exec_module(mod)
    return mod


gt = _load()


def _tr(rising: int = 0, new: int = 0, falling: int = 0,
        entries: int = 1) -> dict[str, Any]:
    return {
        "counts": {
            "entries": entries,
            "rising":  rising,
            "new":     new,
            "falling": falling,
        },
    }


def test_no_thresholds_no_breach() -> None:
    r = gt.evaluate(_tr(rising=5, new=5))
    assert r["breached"] is False
    assert r["breaches"] == []


def test_rising_breach() -> None:
    r = gt.evaluate(_tr(rising=6), max_rising=5)
    assert r["breached"] is True
    assert r["breaches"][0] == {"kind": "rising", "limit": 5, "actual": 6}


def test_rising_at_limit_is_not_a_breach() -> None:
    r = gt.evaluate(_tr(rising=5), max_rising=5)
    assert r["breached"] is False


def test_new_breach_independent_of_rising() -> None:
    r = gt.evaluate(_tr(rising=0, new=11), max_new=10)
    assert [b["kind"] for b in r["breaches"]] == ["new"]


def test_multiple_breaches() -> None:
    r = gt.evaluate(
        _tr(rising=6, new=11, falling=8),
        max_rising=5, max_new=10, max_falling=5,
    )
    assert [b["kind"] for b in r["breaches"]] == ["rising", "new", "falling"]


def test_non_dict_trend_tolerated() -> None:
    r = gt.evaluate(["not", "a", "dict"])  # type: ignore[arg-type]
    assert r["entries"] == 0
    assert r["breached"] is False


def test_counts_key_missing_falls_back_to_zeros() -> None:
    r = gt.evaluate({"not_counts": 1}, max_rising=0)
    assert r["rising"] == 0
    assert r["breached"] is False


def test_bool_count_field_is_not_counted() -> None:
    r = gt.evaluate({"counts": {"rising": True}}, max_rising=0)
    # bool must not masquerade as an int
    assert r["rising"] == 0
    assert r["breached"] is False


def test_render_markdown_clean() -> None:
    md = gt.render_markdown(gt.evaluate(_tr()))
    assert "within limits" in md


def test_render_markdown_table() -> None:
    md = gt.render_markdown(
        gt.evaluate(_tr(rising=6), max_rising=5),
    )
    assert "| kind | limit | actual |" in md
    assert "rising" in md


def _seed(tmp: Path, trend: Any) -> Path:
    p = tmp / "t.json"
    p.write_text(json.dumps(trend), encoding="utf-8")
    return p


def test_cli_json_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    p = _seed(tmp_path, _tr(rising=3))
    rc = gt.main([
        "--trend", str(p), "--format", "json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rising"] == 3


def test_cli_md_output(tmp_path: Path) -> None:
    p = _seed(tmp_path, _tr())
    out = tmp_path / "g.md"
    rc = gt.main([
        "--trend", str(p), "--output", str(out),
    ])
    assert rc == 0
    assert "alert-trend gate" in out.read_text(encoding="utf-8")


def test_cli_fail_on_breach_returns_1(tmp_path: Path) -> None:
    p = _seed(tmp_path, _tr(rising=6))
    rc = gt.main([
        "--trend", str(p), "--max-rising", "5", "--fail-on-breach",
    ])
    assert rc == 1


def test_cli_fail_on_breach_passes_when_clean(tmp_path: Path) -> None:
    p = _seed(tmp_path, _tr(rising=0))
    rc = gt.main([
        "--trend", str(p), "--max-rising", "5", "--fail-on-breach",
    ])
    assert rc == 0


def test_cli_missing_trend(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = gt.main(["--trend", str(tmp_path / "nope.json")])
    assert rc == 1
    assert "trend not found" in capsys.readouterr().err


def test_cli_invalid_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "bad.json"
    p.write_text("not-json", encoding="utf-8")
    rc = gt.main(["--trend", str(p)])
    assert rc == 1
    assert "not valid JSON" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_alert_trend_gate_step() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 alert trend gate" in names
    assert "Upload Plan 2.8 alert trend gate" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 alert trend gate")
    assert "plan_2_8_alert_trend_gate.py" in step["run"]
    assert "--max-rising  5" in step["run"]
