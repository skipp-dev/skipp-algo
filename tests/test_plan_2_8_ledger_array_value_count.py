"""Tests for ``plan_2_8_ledger_array_value_count.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_array_value_count.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_array_value_count", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_array_value_count"] = mod
    spec.loader.exec_module(mod)
    return mod


av = _load()


def test_empty(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text("", encoding="utf-8")
    assert av.compute(p)["array_value_count"] == 0


def test_counts(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        '{"a":[1,2],"b":1}\n{"c":[],"d":"x","e":[9]}\n{"f":{}}\n',
        encoding="utf-8",
    )
    rep = av.compute(p)
    assert rep["record_count"] == 3
    assert rep["array_value_count"] == 3


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text('{"a":[1]}\n', encoding="utf-8")
    assert "array_value_count" in av.render_markdown(av.compute(p))


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text('{"a":[1]}\n', encoding="utf-8")
    out = tmp_path / "o.json"
    code = av.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["array_value_count"] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = av.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_av_steps() -> None:
    pytest.importorskip("yaml")
    data = _wf(WEEKLY)
    steps = data["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger array value count" in names
    assert "Upload Plan 2.8 ledger array value count" in names
    step = next(
        s for s in steps
        if s.get("name") == "Plan 2.8 ledger array value count"
    )
    assert "plan_2_8_ledger_array_value_count.py" in step["run"]
