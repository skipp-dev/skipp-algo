"""Tests for ``scripts/plan_2_8_ledger_status_first_last.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_status_first_last.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_status_first_last", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_status_first_last"] = mod
    spec.loader.exec_module(mod)
    return mod


fl = _load()


def _r(st: str, t: str) -> dict[str, Any]:
    return {"status": st, "captured_at": t}


def test_empty() -> None:
    rep = fl.compute([])
    assert rep["status_count"] == 0
    assert rep["entries"] == []


def test_single_status() -> None:
    rep = fl.compute([
        _r("green", "2026-04-20T00:00:00+00:00"),
        _r("green", "2026-04-20T01:00:00+00:00"),
    ])
    assert rep["status_count"] == 1
    e = rep["entries"][0]
    assert e == {
        "status": "green",
        "first":  "2026-04-20T00:00:00+00:00",
        "last":   "2026-04-20T01:00:00+00:00",
    }


def test_multi_status_order() -> None:
    rep = fl.compute([
        _r("red",     "2026-04-20T00:00:00+00:00"),
        _r("green",   "2026-04-20T01:00:00+00:00"),
        _r("amber",   "2026-04-20T02:00:00+00:00"),
        _r("red",     "2026-04-20T03:00:00+00:00"),
    ])
    statuses = [e["status"] for e in rep["entries"]]
    assert statuses == ["green", "amber", "red"]


def test_invalid_ignored() -> None:
    rep = fl.compute([_r("bogus", "2026-04-20T00:00:00+00:00")])
    assert rep["status_count"] == 0


def test_markdown_shape(tmp_path: Path) -> None:
    md = fl.render_markdown(fl.compute([
        _r("green", "2026-04-20T00:00:00+00:00"),
    ]))
    assert "green" in md
    assert "first=" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_r("green", "2026-04-20T00:00:00+00:00")) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    rc = fl.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["status_count"] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = fl.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_first_last_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger status first/last" in names
    assert "Upload Plan 2.8 ledger status first/last" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger status first/last")
    assert "plan_2_8_ledger_status_first_last.py" in step["run"]
