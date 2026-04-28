"""Tests for ``plan_2_8_ledger_unique_status_count.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_unique_status_count.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_unique_status_count", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_unique_status_count"] = mod
    spec.loader.exec_module(mod)
    return mod


us = _load()


def _r(s: str) -> dict[str, Any]:
    return {"status": s, "captured_at": "2026-05-10T00:00:00Z"}


def test_empty() -> None:
    assert us.compute([])["unique_status_count"] == 0


def test_unique_all_same() -> None:
    rep = us.compute([_r("green"), _r("green"), _r("green")])
    assert rep["unique_status_count"] == 1


def test_all_four() -> None:
    rep = us.compute(
        [_r("green"), _r("amber"), _r("red"), _r("unknown")])
    assert rep["unique_status_count"] == 4


def test_markdown_shape() -> None:
    body = us.render_markdown(us.compute([_r("green")]))
    assert "unique_status_count" in body


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        "".join(json.dumps(_r(s)) + "\n" for s in ("green", "red", "green")),
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    code = us.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["unique_status_count"] == 2


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = us.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_us_steps() -> None:
    pytest.importorskip("yaml")
    data = _wf(WEEKLY)
    steps = data["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger unique status count" in names
    assert "Upload Plan 2.8 ledger unique status count" in names
    step = next(
        s for s in steps
        if s.get("name") == "Plan 2.8 ledger unique status count"
    )
    assert "plan_2_8_ledger_unique_status_count.py" in step["run"]
