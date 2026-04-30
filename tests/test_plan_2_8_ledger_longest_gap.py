"""Tests for ``scripts/plan_2_8_ledger_longest_gap.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_longest_gap.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_longest_gap", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_longest_gap"] = mod
    spec.loader.exec_module(mod)
    return mod


lg = _load()


def _r(t: str) -> dict[str, Any]:
    return {"status": "green", "captured_at": t}


def test_empty_not_found() -> None:
    rep = lg.compute([])
    assert rep["found"] is False


def test_single_not_found() -> None:
    rep = lg.compute([_r("2026-04-20T00:00:00+00:00")])
    assert rep["found"] is False


def test_finds_longest() -> None:
    rep = lg.compute([
        _r("2026-04-20T00:00:00+00:00"),
        _r("2026-04-20T01:00:00+00:00"),
        _r("2026-04-20T05:00:00+00:00"),  # 4h gap
        _r("2026-04-20T06:00:00+00:00"),
    ])
    assert rep["found"] is True
    assert rep["longest_hours"] == 4.0
    assert rep["start_at"] == "2026-04-20T01:00:00+00:00"
    assert rep["end_at"] == "2026-04-20T05:00:00+00:00"


def test_invalid_skipped() -> None:
    rep = lg.compute([
        _r("2026-04-20T00:00:00+00:00"),
        {"status": "bogus", "captured_at": "x"},
        _r("2026-04-20T02:00:00+00:00"),
    ])
    assert rep["longest_hours"] == 2.0


def test_markdown_found() -> None:
    md = lg.render_markdown(lg.compute([
        _r("2026-04-20T00:00:00+00:00"),
        _r("2026-04-20T01:00:00+00:00"),
    ]))
    assert "longest_hours" in md


def test_markdown_empty() -> None:
    md = lg.render_markdown(lg.compute([]))
    assert "_none_" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_r("2026-04-20T00:00:00+00:00")) + "\n"
        + json.dumps(_r("2026-04-20T01:00:00+00:00")) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    rc = lg.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["longest_hours"] == 1.0


def test_cli_fail_above(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_r("2026-04-20T00:00:00+00:00")) + "\n"
        + json.dumps(_r("2026-04-20T05:00:00+00:00")) + "\n",
        encoding="utf-8",
    )
    rc = lg.main(["--ledger", str(p), "--fail-above-hours", "1"])
    assert rc == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = lg.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_longest_gap_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger longest gap" in names
    assert "Upload Plan 2.8 ledger longest gap" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger longest gap")
    assert "plan_2_8_ledger_longest_gap.py" in step["run"]
