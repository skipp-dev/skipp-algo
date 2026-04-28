"""Tests for ``scripts/plan_2_8_ledger_amber_index_median.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_amber_index_median.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_amber_index_median", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_amber_index_median"] = mod
    spec.loader.exec_module(mod)
    return mod


am = _load()


def _r(s: str) -> dict[str, Any]:
    return {"status": s, "captured_at": "2026-05-10T00:00:00Z"}


def test_empty() -> None:
    assert am.compute([])["amber_index_median"] == -1.0


def test_no_amber() -> None:
    assert am.compute([_r("green")])["amber_index_median"] == -1.0


def test_median() -> None:
    # ambers at indices 1, 3 -> median = 2.0
    rep = am.compute(
        [_r("green"), _r("amber"), _r("red"), _r("amber")])
    assert rep["amber_index_median"] == 2.0


def test_markdown_shape() -> None:
    assert "amber_index_median" in am.render_markdown(
        am.compute([_r("amber")]))


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps(_r("amber")) + "\n", encoding="utf-8")
    out = tmp_path / "o.json"
    code = am.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["amber_index_median"] == 0.0


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = am.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_amber_median_steps() -> None:
    pytest.importorskip("yaml")
    data = _wf(WEEKLY)
    steps = data["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger amber index median" in names
    assert "Upload Plan 2.8 ledger amber index median" in names
    step = next(s for s in steps
                if s.get("name")
                == "Plan 2.8 ledger amber index median")
    assert "plan_2_8_ledger_amber_index_median.py" in step["run"]
