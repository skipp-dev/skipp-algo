"""Tests for ``scripts/plan_2_8_ledger_first_observation.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_first_observation.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_first_observation", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_first_observation"] = mod
    spec.loader.exec_module(mod)
    return mod


fo = _load()


def _r(s: str, t: str) -> dict[str, Any]:
    return {"status": s, "captured_at": t}


def test_empty() -> None:
    assert fo.compute([])["first_captured_at"] == ""


def test_first() -> None:
    recs = [_r("green", "t1"), _r("red", "t2")]
    assert fo.compute(recs)["first_captured_at"] == "t1"


def test_skip_invalid_status() -> None:
    recs = [_r("bogus", "t0"), _r("green", "t1")]
    assert fo.compute(recs)["first_captured_at"] == "t1"


def test_skip_missing_captured_at() -> None:
    recs = [{"status": "green"}, _r("red", "t5")]
    assert fo.compute(recs)["first_captured_at"] == "t5"


def test_markdown_shape() -> None:
    text = fo.render_markdown(fo.compute([_r("green", "ts")]))
    assert "first_captured_at" in text


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_r("green", "ts-1")) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    code = fo.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["first_captured_at"] == "ts-1"


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = fo.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_first_observation_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger first observation" in names
    assert "Upload Plan 2.8 ledger first observation" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger first observation")
    assert "plan_2_8_ledger_first_observation.py" in step["run"]
