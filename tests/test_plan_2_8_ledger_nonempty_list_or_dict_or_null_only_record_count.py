"""Tests for ``plan_2_8_ledger_nonempty_list_or_dict_or_null_only_record_count.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest


REPO = Path(__file__).resolve().parents[1]
NAME = "plan_2_8_ledger_nonempty_list_or_dict_or_null_only_record_count"
SCRIPT = REPO / "scripts" / f"{NAME}.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"
KEY = "nonempty_list_or_dict_or_null_only_record_count"
NM = "Plan 2.8 ledger nonempty list or dict or null only record count"


def _load():
    spec = importlib.util.spec_from_file_location(NAME, SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[NAME] = mod
    spec.loader.exec_module(mod)
    return mod


m = _load()


def test_empty(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text("", encoding="utf-8")
    assert m.compute(p)[KEY] == 0


def test_counts(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        '{}\n{"a":[1]}\n{"a":{"x":1}}\n{"a":null,"b":[1]}\n'
        '{"a":[]}\n{"a":{}}\n{"a":1}\n',
        encoding="utf-8",
    )
    rep = m.compute(p)
    assert rep["record_count"] == 7
    assert rep[KEY] == 3


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text('{"a":[1]}\n', encoding="utf-8")
    assert KEY in m.render_markdown(m.compute(p))


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text('{"a":[1]}\n', encoding="utf-8")
    out = tmp_path / "o.json"
    code = m.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))[KEY] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = m.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_nldn_steps() -> None:
    pytest.importorskip("yaml")
    data = _wf(WEEKLY)
    steps = data["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert NM in names
    assert f"Upload {NM}" in names
    step = next(s for s in steps if s.get("name") == NM)
    assert f"{NAME}.py" in step["run"]
