"""Tests for ``scripts/plan_2_8_ledger_green_streak_history.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_green_streak_history.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_green_streak_history", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_green_streak_history"] = mod
    spec.loader.exec_module(mod)
    return mod


gh = _load()


def _r(st: str, t: str) -> dict[str, Any]:
    return {"status": st, "captured_at": t}


def test_empty() -> None:
    rep = gh.compute([])
    assert rep["segment_count"] == 0
    assert rep["entries"] == []


def test_single_segment() -> None:
    rep = gh.compute([
        _r("green", "2026-04-20T00:00:00+00:00"),
        _r("green", "2026-04-20T01:00:00+00:00"),
    ])
    assert rep["segment_count"] == 1
    assert rep["entries"][0]["length"] == 2
    assert rep["entries"][0]["hours"] == 1.0


def test_multiple_segments() -> None:
    rep = gh.compute([
        _r("green", "2026-04-20T00:00:00+00:00"),
        _r("green", "2026-04-20T01:00:00+00:00"),
        _r("red",   "2026-04-20T02:00:00+00:00"),
        _r("green", "2026-04-20T03:00:00+00:00"),
    ])
    assert rep["segment_count"] == 2
    assert [e["length"] for e in rep["entries"]] == [2, 1]
    assert [e["index"] for e in rep["entries"]] == [1, 2]


def test_only_reds() -> None:
    rep = gh.compute([_r("red", "2026-04-20T00:00:00+00:00")])
    assert rep["segment_count"] == 0


def test_invalid_skipped() -> None:
    rep = gh.compute([
        _r("green", "2026-04-20T00:00:00+00:00"),
        {"status": "bogus", "captured_at": "x"},
        _r("green", "2026-04-20T01:00:00+00:00"),
    ])
    assert rep["segment_count"] == 1
    assert rep["entries"][0]["length"] == 2


def test_markdown_shape() -> None:
    md = gh.render_markdown(gh.compute([
        _r("green", "2026-04-20T00:00:00+00:00"),
    ]))
    assert "#1" in md
    assert "len=1" in md


def test_markdown_empty() -> None:
    md = gh.render_markdown(gh.compute([]))
    assert "_none_" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_r("green", "2026-04-20T00:00:00+00:00")) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    rc = gh.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["segment_count"] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = gh.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_green_streak_history_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger green streak history" in names
    assert "Upload Plan 2.8 ledger green streak history" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger green streak history")
    assert "plan_2_8_ledger_green_streak_history.py" in step["run"]
