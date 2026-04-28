"""Tests for ``plan_2_8_ledger_total_byte_size.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_total_byte_size.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_total_byte_size", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_total_byte_size"] = mod
    spec.loader.exec_module(mod)
    return mod


tb = _load()


def test_empty(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_bytes(b"")
    assert tb.compute(p)["total_byte_size"] == 0


def test_bytes(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_bytes(b"hello\nworld")
    assert tb.compute(p)["total_byte_size"] == 11


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_bytes(b"x")
    body = tb.render_markdown(tb.compute(p))
    assert "total_byte_size" in body


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_bytes(b"abc")
    out = tmp_path / "o.json"
    code = tb.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["total_byte_size"] == 3


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = tb.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_tb_steps() -> None:
    pytest.importorskip("yaml")
    data = _wf(WEEKLY)
    steps = data["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger total byte size" in names
    assert "Upload Plan 2.8 ledger total byte size" in names
    step = next(
        s for s in steps
        if s.get("name") == "Plan 2.8 ledger total byte size"
    )
    assert "plan_2_8_ledger_total_byte_size.py" in step["run"]
