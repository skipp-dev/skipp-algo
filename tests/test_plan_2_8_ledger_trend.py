"""Tests for ``scripts/plan_2_8_ledger_trend.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_trend.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_trend", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_trend"] = mod
    spec.loader.exec_module(mod)
    return mod


lt = _load()


def _rec(ts: str, status: str) -> dict[str, Any]:
    return {"captured_at": ts, "status": status}


def test_empty_no_weeks() -> None:
    rep = lt.compute([])
    assert rep["weeks"] == []
    assert rep["skipped"] == 0


def test_buckets_same_iso_week() -> None:
    # 2026-04-20 is Monday of ISO week 17
    recs = [
        _rec("2026-04-20T12:00:00+00:00", "green"),
        _rec("2026-04-21T12:00:00+00:00", "amber"),
        _rec("2026-04-22T12:00:00+00:00", "green"),
    ]
    rep = lt.compute(recs)
    assert len(rep["weeks"]) == 1
    w = rep["weeks"][0]
    assert w["total"] == 3
    assert w["green"] == 2
    assert w["green_pct"] == round(2 / 3 * 100, 2)


def test_splits_weeks() -> None:
    recs = [
        _rec("2026-04-13T00:00:00+00:00", "green"),  # week 16
        _rec("2026-04-20T00:00:00+00:00", "amber"),  # week 17
    ]
    rep = lt.compute(recs)
    assert len(rep["weeks"]) == 2
    assert rep["weeks"][0]["week"] < rep["weeks"][1]["week"]


def test_invalid_records_counted_as_skipped() -> None:
    recs = [
        _rec("bad", "green"),
        _rec("2026-04-20T00:00:00+00:00", "bogus"),
        _rec("2026-04-20T00:00:00+00:00", "green"),
    ]
    rep = lt.compute(recs)
    assert rep["skipped"] == 2
    assert rep["weeks"][0]["total"] == 1


def test_markdown_shape() -> None:
    rep = lt.compute([_rec("2026-04-20T00:00:00+00:00", "green")])
    md = lt.render_markdown(rep)
    assert "| week |" in md
    assert "2026-W17" in md


def test_markdown_empty_has_placeholder() -> None:
    md = lt.render_markdown(lt.compute([]))
    assert "no records" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_rec("2026-04-20T00:00:00+00:00", "green")) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    rc = lt.main([
        "--ledger", str(p), "--format", "json",
        "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["weeks"][0]["green"] == 1


def test_cli_md(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text("", encoding="utf-8")
    out = tmp_path / "o.md"
    rc = lt.main([
        "--ledger", str(p), "--format", "md",
        "--output", str(out),
    ])
    assert rc == 0
    assert "green trend" in out.read_text(encoding="utf-8")


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = lt.main(["--ledger", str(tmp_path / "nope.jsonl")])
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


def test_weekly_has_trend_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger trend" in names
    assert "Upload Plan 2.8 ledger trend" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger trend")
    assert "plan_2_8_ledger_trend.py" in step["run"]
