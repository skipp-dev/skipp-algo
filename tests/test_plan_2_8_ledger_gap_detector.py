"""Tests for ``scripts/plan_2_8_ledger_gap_detector.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_gap_detector.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_gap_detector", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_gap_detector"] = mod
    spec.loader.exec_module(mod)
    return mod


gd = _load()


def _rec(ts: str) -> dict[str, Any]:
    return {"captured_at": ts, "status": "green"}


def test_empty_no_gaps() -> None:
    rep = gd.compute([], threshold_hours=24)
    assert rep["gap_count"] == 0


def test_single_record_no_gaps() -> None:
    rep = gd.compute(
        [_rec("2026-04-21T00:00:00+00:00")], threshold_hours=24,
    )
    assert rep["gap_count"] == 0


def test_small_gap_not_flagged() -> None:
    rep = gd.compute([
        _rec("2026-04-20T00:00:00+00:00"),
        _rec("2026-04-20T06:00:00+00:00"),
    ], threshold_hours=24)
    assert rep["gap_count"] == 0


def test_large_gap_flagged() -> None:
    rep = gd.compute([
        _rec("2026-04-10T00:00:00+00:00"),
        _rec("2026-04-15T00:00:00+00:00"),
    ], threshold_hours=24)
    assert rep["gap_count"] == 1
    assert rep["gaps"][0]["hours"] == pytest.approx(120.0, abs=0.01)


def test_boundary_not_flagged() -> None:
    # exactly 24h -> not > threshold
    rep = gd.compute([
        _rec("2026-04-10T00:00:00+00:00"),
        _rec("2026-04-11T00:00:00+00:00"),
    ], threshold_hours=24)
    assert rep["gap_count"] == 0


def test_unsorted_input_sorted_internally() -> None:
    rep = gd.compute([
        _rec("2026-04-15T00:00:00+00:00"),
        _rec("2026-04-10T00:00:00+00:00"),
    ], threshold_hours=24)
    assert rep["gap_count"] == 1


def test_invalid_ts_skipped() -> None:
    rep = gd.compute([
        _rec("bad"),
        _rec("2026-04-21T00:00:00+00:00"),
    ], threshold_hours=24)
    assert rep["record_count"] == 1


def test_markdown_no_gaps() -> None:
    md = gd.render_markdown(gd.compute([], threshold_hours=24))
    assert "(none)" in md


def test_markdown_with_gap() -> None:
    md = gd.render_markdown(gd.compute([
        _rec("2026-04-10T00:00:00+00:00"),
        _rec("2026-04-15T00:00:00+00:00"),
    ], threshold_hours=24))
    assert "120.00" in md


def test_cli_fail_on_gaps(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_rec("2026-04-10T00:00:00+00:00")) + "\n"
        + json.dumps(_rec("2026-04-15T00:00:00+00:00")) + "\n",
        encoding="utf-8",
    )
    rc = gd.main([
        "--ledger", str(p), "--threshold-hours", "24", "--fail-on-gaps",
    ])
    assert rc == 1


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_rec("2026-04-21T00:00:00+00:00")) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    rc = gd.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["record_count"] == 1


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = gd.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "ledger not found" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_gap_detector_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger gap detector" in names
    assert "Upload Plan 2.8 ledger gap detector" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger gap detector")
    assert "plan_2_8_ledger_gap_detector.py" in step["run"]
