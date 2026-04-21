"""Tests for ``plan_2_8_ledger_duplicate_record_count.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_duplicate_record_count.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_duplicate_record_count", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_duplicate_record_count"] = mod
    spec.loader.exec_module(mod)
    return mod


dr = _load()


def test_empty() -> None:
    assert dr.compute([])["duplicate_record_count"] == 0


def test_duplicates() -> None:
    rs = [
        {"status": "green", "t": 1},
        {"status": "green", "t": 1},
        {"status": "amber", "t": 2},
        {"status": "green", "t": 1},
    ]
    assert dr.compute(rs)["duplicate_record_count"] == 2


def test_unique_zero() -> None:
    rs = [{"status": "green"}, {"status": "amber"}, {"status": "red"}]
    assert dr.compute(rs)["duplicate_record_count"] == 0


def test_markdown_shape() -> None:
    body = dr.render_markdown(dr.compute([]))
    assert "duplicate_record_count" in body


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps({"a": 1}) + "\n" + json.dumps({"a": 1}) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    code = dr.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["duplicate_record_count"] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = dr.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_dr_steps() -> None:
    pytest.importorskip("yaml")
    data = _wf(WEEKLY)
    steps = data["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger duplicate record count" in names
    assert "Upload Plan 2.8 ledger duplicate record count" in names
    step = next(
        s for s in steps
        if s.get("name") == "Plan 2.8 ledger duplicate record count"
    )
    assert "plan_2_8_ledger_duplicate_record_count.py" in step["run"]
