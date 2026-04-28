"""Tests for ``scripts/plan_2_8_ledger_unique_statuses.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_unique_statuses.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_unique_statuses", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_unique_statuses"] = mod
    spec.loader.exec_module(mod)
    return mod


us = _load()


def test_empty() -> None:
    rep = us.compute([])
    assert rep["unique_count"] == 0
    assert rep["statuses"] == []


def test_mixed() -> None:
    rep = us.compute([
        {"status": "green"},
        {"status": "AMBER"},
        {"status": " red "},
        {"status": "green"},
        {"status": "bogus"},
    ])
    assert rep["unique_count"] == 3
    assert rep["statuses"] == ["amber", "green", "red"]
    assert rep["counts"]["green"] == 2


def test_non_string_skipped() -> None:
    rep = us.compute([{"status": 1}, {"status": None}])
    assert rep["unique_count"] == 0


def test_markdown_none() -> None:
    md = us.render_markdown(us.compute([]))
    assert "_none_" in md


def test_cli_fail_below(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps({"status": "green"}) + "\n", encoding="utf-8",
    )
    rc = us.main([
        "--ledger", str(p), "--fail-below-count", "2",
    ])
    assert rc == 1


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps({"status": "green"}) + "\n"
        + json.dumps({"status": "red"}) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    rc = us.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["unique_count"] == 2
    assert data["statuses"] == ["green", "red"]


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = us.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_unique_statuses_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger unique statuses" in names
    assert "Upload Plan 2.8 ledger unique statuses" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger unique statuses")
    assert "plan_2_8_ledger_unique_statuses.py" in step["run"]
