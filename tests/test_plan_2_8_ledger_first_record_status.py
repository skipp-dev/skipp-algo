"""Tests for ``plan_2_8_ledger_first_record_status.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_first_record_status.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_first_record_status", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_first_record_status"] = mod
    spec.loader.exec_module(mod)
    return mod


fs = _load()


def _r(s: str) -> dict[str, Any]:
    return {"status": s, "captured_at": "2026-05-10T00:00:00Z"}


def test_empty() -> None:
    assert fs.compute([])["first_record_status"] == ""


def test_first() -> None:
    rs = [_r("amber"), _r("green"), _r("red")]
    assert fs.compute(rs)["first_record_status"] == "amber"


def test_skip_invalid() -> None:
    rs = [{"status": "bogus"}, _r("green")]
    assert fs.compute(rs)["first_record_status"] == "green"


def test_markdown_shape() -> None:
    body = fs.render_markdown(fs.compute([_r("red")]))
    assert "first_record_status" in body


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps(_r("unknown")) + "\n", encoding="utf-8")
    out = tmp_path / "o.json"
    code = fs.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["first_record_status"] == "unknown"


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = fs.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_fs_steps() -> None:
    pytest.importorskip("yaml")
    data = _wf(WEEKLY)
    steps = data["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger first record status" in names
    assert "Upload Plan 2.8 ledger first record status" in names
    step = next(
        s for s in steps
        if s.get("name") == "Plan 2.8 ledger first record status"
    )
    assert "plan_2_8_ledger_first_record_status.py" in step["run"]
