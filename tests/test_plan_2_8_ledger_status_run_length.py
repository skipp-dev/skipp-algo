"""Tests for ``scripts/plan_2_8_ledger_status_run_length.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_status_run_length.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_status_run_length", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_status_run_length"] = mod
    spec.loader.exec_module(mod)
    return mod


rl = _load()


def _r(status: str, at: str = "2026-04-20T00:00:00+00:00") -> dict[str, Any]:
    return {"status": status, "captured_at": at}


def test_empty() -> None:
    rep = rl.compute([])
    assert rep["segment_count"] == 0


def test_single_run() -> None:
    rep = rl.compute([
        _r("green", "2026-04-18T00:00:00+00:00"),
        _r("green", "2026-04-19T00:00:00+00:00"),
        _r("green", "2026-04-20T00:00:00+00:00"),
    ])
    assert rep["segment_count"] == 1
    assert rep["segments"][0]["length"] == 3
    assert rep["segments"][0]["start_at"] == "2026-04-18T00:00:00+00:00"
    assert rep["segments"][0]["end_at"] == "2026-04-20T00:00:00+00:00"


def test_multiple_segments() -> None:
    rep = rl.compute([
        _r("green", "2026-04-18T00:00:00+00:00"),
        _r("amber", "2026-04-19T00:00:00+00:00"),
        _r("amber", "2026-04-20T00:00:00+00:00"),
        _r("red",   "2026-04-21T00:00:00+00:00"),
    ])
    assert rep["segment_count"] == 3
    assert [s["status"] for s in rep["segments"]] == ["green", "amber", "red"]
    assert [s["length"] for s in rep["segments"]] == [1, 2, 1]


def test_invalid_filtered() -> None:
    rep = rl.compute([
        _r("green"), _r("bogus"), _r("green"),
    ])
    # bogus skipped -> sequence is green,green (one run)
    assert rep["segment_count"] == 1


def test_markdown_shape() -> None:
    md = rl.render_markdown(rl.compute([_r("green")]))
    assert "run lengths" in md
    assert "green" in md


def test_markdown_empty_placeholder() -> None:
    md = rl.render_markdown(rl.compute([]))
    assert "_none_" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps(_r("green")) + "\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = rl.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["segment_count"] == 1


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = rl.main(["--ledger", str(tmp_path / "nope.jsonl")])
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


def test_weekly_has_run_length_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger status run length" in names
    assert "Upload Plan 2.8 ledger status run length" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger status run length")
    assert "plan_2_8_ledger_status_run_length.py" in step["run"]
