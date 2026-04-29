"""Tests for ``scripts/plan_2_8_ledger_status_today.py``."""

from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_status_today.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_status_today", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_status_today"] = mod
    spec.loader.exec_module(mod)
    return mod


st = _load()


def _rec(ts: str, status: str) -> dict[str, Any]:
    return {"captured_at": ts, "status": status}


def test_finds_same_day() -> None:
    rep = st.find_today(
        [_rec("2026-04-21T06:00:00+00:00", "green")],
        target=_dt.date(2026, 4, 21),
    )
    assert rep["found"] is True
    assert rep["status"] == "green"


def test_not_found_when_wrong_day() -> None:
    rep = st.find_today(
        [_rec("2026-04-20T23:59:00+00:00", "green")],
        target=_dt.date(2026, 4, 21),
    )
    assert rep["found"] is False


def test_returns_latest_of_day() -> None:
    rep = st.find_today(
        [
            _rec("2026-04-21T01:00:00+00:00", "amber"),
            _rec("2026-04-21T23:00:00+00:00", "green"),
        ],
        target=_dt.date(2026, 4, 21),
    )
    assert rep["status"] == "green"


def test_invalid_records_skipped() -> None:
    rep = st.find_today(
        [
            {"captured_at": "bad", "status": "green"},
            _rec("2026-04-21T06:00:00+00:00", "bogus"),
            _rec("2026-04-21T07:00:00+00:00", "amber"),
        ],
        target=_dt.date(2026, 4, 21),
    )
    assert rep["status"] == "amber"


def test_markdown_missing() -> None:
    md = st.render_markdown({
        "date": "2026-04-21",
        "found": False,
        "status": None,
        "captured_at": None,
        "run_url": None,
    })
    assert "No ledger record" in md


def test_markdown_found() -> None:
    md = st.render_markdown({
        "date": "2026-04-21",
        "found": True,
        "status": "green",
        "captured_at": "2026-04-21T06:00:00+00:00",
        "run_url": None,
    })
    assert "green" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_rec("2026-04-21T06:00:00+00:00", "green")) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    rc = st.main([
        "--ledger", str(p), "--date", "2026-04-21",
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["found"] is True


def test_cli_bad_date(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text("", encoding="utf-8")
    rc = st.main(["--ledger", str(p), "--date", "nope"])
    assert rc == 1
    assert "invalid --date" in capsys.readouterr().err


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = st.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "ledger not found" in capsys.readouterr().err


def test_cli_default_date_is_today(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text("", encoding="utf-8")
    rc = st.main(["--ledger", str(p), "--format", "json"])
    assert rc == 0


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_status_today_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 status today" in names
    assert "Upload Plan 2.8 status today" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 status today")
    assert "plan_2_8_ledger_status_today.py" in step["run"]
