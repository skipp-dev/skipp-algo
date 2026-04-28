"""Tests for ``plan_2_8_ledger_json_valid_count.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_json_valid_count.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_json_valid_count", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_json_valid_count"] = mod
    spec.loader.exec_module(mod)
    return mod


jv = _load()


def test_empty(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text("", encoding="utf-8")
    assert jv.compute(p)["json_valid_count"] == 0


def test_mixed(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        '{"a":1}\nnot json\n{"b":2}\n\n',
        encoding="utf-8",
    )
    rep = jv.compute(p)
    assert rep["nonblank_line_count"] == 3
    assert rep["json_valid_count"] == 2


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text('{"a":1}\n', encoding="utf-8")
    assert "json_valid_count" in jv.render_markdown(jv.compute(p))


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text('{"a":1}\n', encoding="utf-8")
    out = tmp_path / "o.json"
    code = jv.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["json_valid_count"] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = jv.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_jv_steps() -> None:
    pytest.importorskip("yaml")
    data = _wf(WEEKLY)
    steps = data["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger json valid count" in names
    assert "Upload Plan 2.8 ledger json valid count" in names
    step = next(
        s for s in steps
        if s.get("name") == "Plan 2.8 ledger json valid count"
    )
    assert "plan_2_8_ledger_json_valid_count.py" in step["run"]
