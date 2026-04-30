"""Tests for ``scripts/plan_2_8_ledger_uptime_pct.py``."""

from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_uptime_pct.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_ledger_uptime_pct", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_uptime_pct"] = mod
    spec.loader.exec_module(mod)
    return mod


up = _load()


NOW = _dt.datetime(2026, 4, 21, 12, 0, tzinfo=_dt.UTC)


def _rec(days_ago: float, status: str) -> dict[str, Any]:
    ts = (NOW - _dt.timedelta(days=days_ago)).strftime(
        "%Y-%m-%dT%H:%M:%S%z",
    )
    return {"captured_at": ts, "status": status}


def test_no_records_zero_uptime() -> None:
    rep = up.compute([], weeks=4, now=NOW)
    assert rep["uptime_pct"] == 0.0
    assert rep["total_seconds"] == 0.0


def test_all_green_full_uptime() -> None:
    records = [_rec(14, "green"), _rec(7, "green"), _rec(0, "green")]
    rep = up.compute(records, weeks=4, now=NOW)
    assert rep["uptime_pct"] == 100.0
    assert rep["green_seconds"] == rep["total_seconds"]


def test_mixed_statuses() -> None:
    # 14d green -> 7d amber -> 0 green: half green in the spans
    records = [_rec(14, "green"), _rec(7, "amber"), _rec(0, "green")]
    rep = up.compute(records, weeks=4, now=NOW)
    assert rep["uptime_pct"] == 50.0


def test_window_anchor_used() -> None:
    # anchor sits outside the window; should still contribute as "before"
    records = [_rec(60, "green"), _rec(3, "amber"), _rec(0, "green")]
    rep = up.compute(records, weeks=1, now=NOW)
    assert rep["total_seconds"] > 0
    # within the 1-week window, amber->green: first segment 4 days
    # from cutoff to day-3 green... wait: anchor is the most-recent
    # record before cutoff, so anchor=(60d,green). From cutoff we
    # start as green. 4 days green, then 3 days amber.
    assert rep["uptime_pct"] == pytest.approx(4 / 7 * 100, abs=0.01)


def test_weeks_must_be_positive() -> None:
    with pytest.raises(ValueError):
        up.compute([], weeks=0, now=NOW)


def test_invalid_records_dropped() -> None:
    records = [
        _rec(7, "green"),
        {"captured_at": "bad", "status": "green"},
        {"captured_at": "2026-04-20T00:00:00+00:00", "status": "bogus"},
        _rec(0, "green"),
    ]
    rep = up.compute(records, weeks=4, now=NOW)
    assert rep["uptime_pct"] == 100.0


def test_render_markdown_shape() -> None:
    rep = up.compute([_rec(7, "green"), _rec(0, "green")],
                     weeks=2, now=NOW)
    md = up.render_markdown(rep)
    assert "uptime (last 2 wk)" in md
    assert "uptime:" in md


def test_cli_json_output(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        "\n".join(json.dumps(r) for r in [
            _rec(7, "green"), _rec(0, "green"),
        ]) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "u.json"
    rc = up.main([
        "--ledger", str(p), "--weeks", "4",
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["weeks"] == 4


def test_cli_fail_below(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        "\n".join(json.dumps(r) for r in [
            _rec(7, "amber"), _rec(0, "amber"),
        ]) + "\n",
        encoding="utf-8",
    )
    rc = up.main([
        "--ledger", str(p), "--weeks", "4",
        "--fail-below", "50",
    ])
    assert rc == 1


def test_cli_fail_below_pass(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        "\n".join(json.dumps(r) for r in [
            _rec(7, "green"), _rec(0, "green"),
        ]) + "\n",
        encoding="utf-8",
    )
    rc = up.main([
        "--ledger", str(p), "--weeks", "4",
        "--fail-below", "99",
    ])
    assert rc == 0


def test_cli_bad_weeks_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text("{}\n", encoding="utf-8")
    rc = up.main(["--ledger", str(p), "--weeks", "0"])
    assert rc == 1
    assert ">= 1" in capsys.readouterr().err


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = up.main(["--ledger", str(tmp_path / "nope.jsonl")])
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


def test_weekly_has_uptime_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger uptime" in names
    assert "Upload Plan 2.8 ledger uptime" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger uptime")
    assert "plan_2_8_ledger_uptime_pct.py" in step["run"]
    assert "--weeks  4" in step["run"]
