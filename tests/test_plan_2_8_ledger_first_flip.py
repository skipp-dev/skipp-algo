"""Tests for ``scripts/plan_2_8_ledger_first_flip.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_first_flip.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_first_flip", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_first_flip"] = mod
    spec.loader.exec_module(mod)
    return mod


ff = _load()


def _r(status: str, at: str = "2026-04-20T00:00:00+00:00") -> dict[str, Any]:
    return {"status": status, "captured_at": at}


def test_empty_no_flip() -> None:
    assert ff.compute([])["found"] is False


def test_no_transition_returns_false() -> None:
    assert ff.compute([_r("green"), _r("green")])["found"] is False


def test_reports_earliest_flip() -> None:
    rep = ff.compute([
        _r("green", "2026-04-18T00:00:00+00:00"),
        _r("amber", "2026-04-19T00:00:00+00:00"),
        _r("red",   "2026-04-20T00:00:00+00:00"),
    ])
    assert rep["found"] is True
    assert rep["from"] == "green"
    assert rep["to"]   == "amber"
    assert rep["at"]   == "2026-04-19T00:00:00+00:00"


def test_invalid_filtered() -> None:
    rep = ff.compute([
        _r("green", "2026-04-18T00:00:00+00:00"),
        _r("bogus", "2026-04-19T00:00:00+00:00"),
        _r("red",   "2026-04-20T00:00:00+00:00"),
    ])
    assert rep["from"] == "green"
    assert rep["to"]   == "red"


def test_markdown_none_placeholder() -> None:
    md = ff.render_markdown(ff.compute([]))
    assert "no flip" in md


def test_markdown_shape() -> None:
    md = ff.render_markdown(ff.compute([
        _r("green", "2026-04-18T00:00:00+00:00"),
        _r("amber", "2026-04-19T00:00:00+00:00"),
    ]))
    assert "first flip" in md
    assert "amber" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_r("green", "2026-04-18T00:00:00+00:00")) + "\n"
        + json.dumps(_r("amber", "2026-04-19T00:00:00+00:00")) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    rc = ff.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["to"] == "amber"


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ff.main(["--ledger", str(tmp_path / "nope.jsonl")])
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


def test_weekly_has_first_flip_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger first flip" in names
    assert "Upload Plan 2.8 ledger first flip" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger first flip")
    assert "plan_2_8_ledger_first_flip.py" in step["run"]
