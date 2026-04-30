"""Tests for ``scripts/plan_2_8_ledger_observations_per_day_mean.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_observations_per_day_mean.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_observations_per_day_mean", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_observations_per_day_mean"] = mod
    spec.loader.exec_module(mod)
    return mod


od = _load()


def _r(s: str, t: str) -> dict[str, Any]:
    return {"status": s, "captured_at": t}


def test_empty() -> None:
    assert od.compute([])["observations_per_day_mean"] == 0.0


def test_mean() -> None:
    recs = [
        _r("green", "2026-05-10T00:00:00Z"),
        _r("red", "2026-05-10T01:00:00Z"),
        _r("green", "2026-05-11T00:00:00Z"),
    ]
    rep = od.compute(recs)
    assert rep["unique_day_count"] == 2
    assert rep["observations_per_day_mean"] == 1.5


def test_markdown_shape() -> None:
    text = od.render_markdown(
        od.compute([_r("green", "2026-05-10T00:00:00Z")]))
    assert "observations_per_day_mean" in text


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_r("green", "2026-05-10T00:00:00Z")) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    code = od.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8")
    )["observations_per_day_mean"] == 1.0


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = od.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_obs_per_day_steps() -> None:
    pytest.importorskip("yaml")
    data = _wf(WEEKLY)
    steps = data["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger observations per day mean" in names
    assert "Upload Plan 2.8 ledger observations per day mean" in names
    step = next(s for s in steps
                if s.get("name")
                == "Plan 2.8 ledger observations per day mean")
    assert "plan_2_8_ledger_observations_per_day_mean.py" in step["run"]
