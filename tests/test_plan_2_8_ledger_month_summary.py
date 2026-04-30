"""Tests for ``scripts/plan_2_8_ledger_month_summary.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_month_summary.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_month_summary", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_month_summary"] = mod
    spec.loader.exec_module(mod)
    return mod


ms = _load()


def _rec(ts: str, status: str) -> dict[str, Any]:
    return {"captured_at": ts, "status": status}


def test_empty_records() -> None:
    rep = ms.compute([])
    assert rep["months"] == []
    assert rep["skipped"] == 0


def test_single_month_counts() -> None:
    rep = ms.compute([
        _rec("2026-04-01T00:00:00+00:00", "green"),
        _rec("2026-04-08T00:00:00+00:00", "green"),
        _rec("2026-04-15T00:00:00+00:00", "amber"),
    ])
    assert len(rep["months"]) == 1
    m = rep["months"][0]
    assert m["month"] == "2026-04"
    assert m["green"] == 2
    assert m["amber"] == 1
    assert m["total"] == 3


def test_multiple_months_sorted() -> None:
    rep = ms.compute([
        _rec("2026-05-01T00:00:00+00:00", "green"),
        _rec("2026-04-01T00:00:00+00:00", "red"),
    ])
    assert [m["month"] for m in rep["months"]] == ["2026-04", "2026-05"]


def test_invalid_status_skipped() -> None:
    rep = ms.compute([
        _rec("2026-04-01T00:00:00+00:00", "bogus"),
        _rec("2026-04-02T00:00:00+00:00", "green"),
    ])
    assert rep["skipped"] == 1
    assert rep["months"][0]["total"] == 1


def test_invalid_timestamp_skipped() -> None:
    rep = ms.compute([
        _rec("not-a-date", "green"),
        _rec("2026-04-01T00:00:00+00:00", "green"),
    ])
    assert rep["skipped"] == 1


def test_markdown_empty_placeholder() -> None:
    md = ms.render_markdown(ms.compute([]))
    assert "_no records_" in md


def test_markdown_shape() -> None:
    md = ms.render_markdown(ms.compute([
        _rec("2026-04-01T00:00:00+00:00", "green"),
    ]))
    assert "2026-04" in md
    assert "green" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_rec("2026-04-01T00:00:00+00:00", "green")) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    rc = ms.main([
        "--ledger", str(p), "--format", "json",
        "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["months"][0]["month"] == "2026-04"


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ms.main(["--ledger", str(tmp_path / "nope.jsonl")])
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


def test_weekly_has_month_summary_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger month summary" in names
    assert "Upload Plan 2.8 ledger month summary" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger month summary")
    assert "plan_2_8_ledger_month_summary.py" in step["run"]
