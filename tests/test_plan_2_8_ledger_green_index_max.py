"""Tests for ``scripts/plan_2_8_ledger_green_index_max.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_green_index_max.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_green_index_max", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_green_index_max"] = mod
    spec.loader.exec_module(mod)
    return mod


gm = _load()


def _r(s: str) -> dict[str, Any]:
    return {"status": s, "captured_at": "2026-05-10T00:00:00Z"}


def test_empty() -> None:
    assert gm.compute([])["green_index_max"] == -1


def test_last() -> None:
    rep = gm.compute([_r("green"), _r("amber"), _r("green")])
    assert rep["green_index_max"] == 2


def test_markdown_shape() -> None:
    body = gm.render_markdown(gm.compute([_r("green")]))
    assert "green_index_max" in body


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_r("amber")) + "\n" + json.dumps(_r("green")) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    code = gm.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["green_index_max"] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = gm.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_green_max_steps() -> None:
    pytest.importorskip("yaml")
    data = _wf(WEEKLY)
    steps = data["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger green index max" in names
    assert "Upload Plan 2.8 ledger green index max" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger green index max")
    assert "plan_2_8_ledger_green_index_max.py" in step["run"]
