"""Tests for ``scripts/plan_2_8_ledger_unique_days.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_unique_days.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_unique_days", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_unique_days"] = mod
    spec.loader.exec_module(mod)
    return mod


ud = _load()


def _r(s: str, t: str) -> dict[str, Any]:
    return {"status": s, "captured_at": t}


def test_empty() -> None:
    assert ud.compute([])["unique_day_count"] == 0


def test_unique() -> None:
    recs = [
        _r("green", "2026-05-10T00:00:00Z"),
        _r("red", "2026-05-10T01:00:00Z"),
        _r("green", "2026-05-11T00:00:00Z"),
    ]
    rep = ud.compute(recs)
    assert rep["observation_count"] == 3
    assert rep["unique_day_count"] == 2


def test_invalid_status_skipped() -> None:
    recs = [
        _r("bogus", "2026-05-10T00:00:00Z"),
        _r("green", "2026-05-11T00:00:00Z"),
    ]
    assert ud.compute(recs)["unique_day_count"] == 1


def test_short_captured_at_skipped() -> None:
    recs = [_r("green", "short"), _r("green", "2026-05-10")]
    assert ud.compute(recs)["unique_day_count"] == 1


def test_markdown_shape() -> None:
    text = ud.render_markdown(ud.compute([_r("green", "2026-05-10")]))
    assert "unique_day_count" in text


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_r("green", "2026-05-10T00:00:00Z")) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    code = ud.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["unique_day_count"] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = ud.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_unique_days_steps() -> None:
    pytest.importorskip("yaml")
    data = _wf(WEEKLY)
    steps = data["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger unique days" in names
    assert "Upload Plan 2.8 ledger unique days" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger unique days")
    assert "plan_2_8_ledger_unique_days.py" in step["run"]
