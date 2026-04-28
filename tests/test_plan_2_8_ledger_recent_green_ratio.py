"""Tests for ``scripts/plan_2_8_ledger_recent_green_ratio.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_recent_green_ratio.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_recent_green_ratio", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_recent_green_ratio"] = mod
    spec.loader.exec_module(mod)
    return mod


gr = _load()


def _r(s: str) -> dict[str, Any]:
    return {"status": s}


def test_empty() -> None:
    rep = gr.compute([], 5)
    assert rep["window_size"] == 0
    assert rep["ratio"] is None


def test_all_green() -> None:
    rep = gr.compute([_r("green")] * 4, 5)
    assert rep["ratio"] == 1.0


def test_mixed_window() -> None:
    rep = gr.compute([_r("green"), _r("amber"), _r("green"), _r("red")], 4)
    assert rep["green_count"] == 2
    assert rep["ratio"] == 0.5


def test_last_n_truncation() -> None:
    recs = [_r("amber")] * 3 + [_r("green")] * 2
    rep = gr.compute(recs, 2)
    assert rep["window_size"] == 2
    assert rep["ratio"] == 1.0


def test_zero_means_all() -> None:
    rep = gr.compute([_r("green")] * 3 + [_r("red")], 0)
    assert rep["window_size"] == 4
    assert rep["ratio"] == 0.75


def test_invalid_filtered() -> None:
    rep = gr.compute([_r("bogus"), _r("green")], 5)
    assert rep["window_size"] == 1
    assert rep["ratio"] == 1.0


def test_markdown_shape() -> None:
    md = gr.render_markdown(gr.compute([_r("green")], 5))
    assert "recent green ratio" in md


def test_markdown_na_when_empty() -> None:
    md = gr.render_markdown(gr.compute([], 5))
    assert "ratio: n/a" in md


def test_cli_fail_below(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps(_r("red")) + "\n", encoding="utf-8")
    rc = gr.main([
        "--ledger", str(p), "--last-n", "5",
        "--fail-below-ratio", "0.5",
    ])
    assert rc == 1


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps(_r("green")) + "\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = gr.main([
        "--ledger", str(p), "--last-n", "5",
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["ratio"] == 1.0


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = gr.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_green_ratio_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger recent green ratio" in names
    assert "Upload Plan 2.8 ledger recent green ratio" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger recent green ratio")
    assert "plan_2_8_ledger_recent_green_ratio.py" in step["run"]
