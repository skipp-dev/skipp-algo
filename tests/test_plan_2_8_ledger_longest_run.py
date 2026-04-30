"""Tests for ``scripts/plan_2_8_ledger_longest_run.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_longest_run.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_longest_run", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_longest_run"] = mod
    spec.loader.exec_module(mod)
    return mod


lr = _load()


def _r(status: str, at: str) -> dict[str, Any]:
    return {"status": status, "captured_at": at}


def test_empty_all_zero() -> None:
    rep = lr.compute([])
    for s in ("green", "amber", "red", "unknown"):
        assert rep["per_status"][s]["length"] == 0


def test_longest_tracked() -> None:
    rep = lr.compute([
        _r("green", "2026-04-10T00:00:00+00:00"),
        _r("green", "2026-04-11T00:00:00+00:00"),
        _r("green", "2026-04-12T00:00:00+00:00"),
        _r("amber", "2026-04-13T00:00:00+00:00"),
        _r("green", "2026-04-14T00:00:00+00:00"),
    ])
    assert rep["per_status"]["green"]["length"] == 3
    assert rep["per_status"]["green"]["start_at"] == "2026-04-10T00:00:00+00:00"
    assert rep["per_status"]["green"]["end_at"] == "2026-04-12T00:00:00+00:00"


def test_missing_status_zero() -> None:
    rep = lr.compute([_r("green", "2026-04-10T00:00:00+00:00")])
    assert rep["per_status"]["red"]["length"] == 0
    assert rep["per_status"]["red"]["start_at"] is None


def test_invalid_filtered() -> None:
    rep = lr.compute([
        _r("green", "2026-04-10T00:00:00+00:00"),
        _r("bogus", "2026-04-11T00:00:00+00:00"),
        _r("green", "2026-04-12T00:00:00+00:00"),
    ])
    # bogus skipped -> two consecutive green records
    assert rep["per_status"]["green"]["length"] == 2


def test_ties_kept_to_first() -> None:
    rep = lr.compute([
        _r("green", "2026-04-10T00:00:00+00:00"),
        _r("green", "2026-04-11T00:00:00+00:00"),
        _r("amber", "2026-04-12T00:00:00+00:00"),
        _r("green", "2026-04-13T00:00:00+00:00"),
        _r("green", "2026-04-14T00:00:00+00:00"),
    ])
    # Both green runs are length 2 - tie, first kept
    assert rep["per_status"]["green"]["length"] == 2
    assert rep["per_status"]["green"]["start_at"] == "2026-04-10T00:00:00+00:00"


def test_markdown_shape() -> None:
    md = lr.render_markdown(lr.compute([
        _r("green", "2026-04-10T00:00:00+00:00"),
    ]))
    assert "longest status run" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_r("green", "2026-04-10T00:00:00+00:00")) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    rc = lr.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["per_status"]["green"]["length"] == 1


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = lr.main(["--ledger", str(tmp_path / "nope.jsonl")])
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


def test_weekly_has_longest_run_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger longest run" in names
    assert "Upload Plan 2.8 ledger longest run" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger longest run")
    assert "plan_2_8_ledger_longest_run.py" in step["run"]
