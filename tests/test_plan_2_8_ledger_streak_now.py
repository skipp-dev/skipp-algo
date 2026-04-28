"""Tests for ``scripts/plan_2_8_ledger_streak_now.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_streak_now.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_streak_now", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_streak_now"] = mod
    spec.loader.exec_module(mod)
    return mod


sn = _load()


def _rec(ts: str, status: str) -> dict[str, Any]:
    return {"captured_at": ts, "status": status}


def test_empty_zero_streak() -> None:
    rep = sn.compute([])
    assert rep["status"] is None
    assert rep["length"] == 0


def test_single_record_length_one() -> None:
    rep = sn.compute([_rec("2026-04-21T00:00:00+00:00", "green")])
    assert rep["length"] == 1
    assert rep["status"] == "green"


def test_counts_trailing_run_only() -> None:
    rep = sn.compute([
        _rec("2026-04-18T00:00:00+00:00", "amber"),
        _rec("2026-04-19T00:00:00+00:00", "green"),
        _rec("2026-04-20T00:00:00+00:00", "green"),
        _rec("2026-04-21T00:00:00+00:00", "green"),
    ])
    assert rep["length"] == 3
    assert rep["started_at"].startswith("2026-04-19")


def test_breaks_on_change() -> None:
    rep = sn.compute([
        _rec("2026-04-20T00:00:00+00:00", "green"),
        _rec("2026-04-21T00:00:00+00:00", "amber"),
    ])
    assert rep["length"] == 1
    assert rep["status"] == "amber"


def test_invalid_records_skipped() -> None:
    rep = sn.compute([
        _rec("2026-04-20T00:00:00+00:00", "green"),
        _rec("2026-04-20T00:00:00+00:00", "bogus"),
        _rec("2026-04-21T00:00:00+00:00", "green"),
    ])
    assert rep["length"] == 2


def test_markdown_shape() -> None:
    md = sn.render_markdown(sn.compute([
        _rec("2026-04-21T00:00:00+00:00", "green"),
    ]))
    assert "current streak" in md
    assert "green" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_rec("2026-04-21T00:00:00+00:00", "green")) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    rc = sn.main([
        "--ledger", str(p), "--format", "json",
        "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "green"


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = sn.main(["--ledger", str(tmp_path / "nope.jsonl")])
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


def test_weekly_has_streak_now_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger streak now" in names
    assert "Upload Plan 2.8 ledger streak now" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger streak now")
    assert "plan_2_8_ledger_streak_now.py" in step["run"]
