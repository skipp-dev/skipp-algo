"""Tests for ``plan_2_8_ledger_top_key_count_total.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_top_key_count_total.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_top_key_count_total", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_top_key_count_total"] = mod
    spec.loader.exec_module(mod)
    return mod


tk = _load()


def test_empty(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text("", encoding="utf-8")
    assert tk.compute(p)["top_key_count_total"] == 0


def test_counts(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text('{}\n{"a":1}\n{"a":1,"b":2,"c":3}\n', encoding="utf-8")
    rep = tk.compute(p)
    assert rep["record_count"] == 3
    assert rep["top_key_count_total"] == 4


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text('{"a":1}\n', encoding="utf-8")
    assert "top_key_count_total" in tk.render_markdown(tk.compute(p))


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text('{"a":1,"b":2}\n', encoding="utf-8")
    out = tmp_path / "o.json"
    code = tk.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["top_key_count_total"] == 2


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = tk.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_tk_steps() -> None:
    pytest.importorskip("yaml")
    data = _wf(WEEKLY)
    steps = data["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger top key count total" in names
    assert "Upload Plan 2.8 ledger top key count total" in names
    step = next(
        s for s in steps
        if s.get("name") == "Plan 2.8 ledger top key count total"
    )
    assert "plan_2_8_ledger_top_key_count_total.py" in step["run"]
