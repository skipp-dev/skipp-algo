"""Tests for ``scripts/plan_2_8_ledger_weekday_histogram.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_weekday_histogram.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_weekday_histogram", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_weekday_histogram"] = mod
    spec.loader.exec_module(mod)
    return mod


wh = _load()


def _rec(ts: str) -> dict[str, Any]:
    return {"captured_at": ts, "status": "green"}


def test_empty_all_zero() -> None:
    rep = wh.compute([])
    assert rep["buckets"] == [0] * 7
    assert len(rep["empty_weekdays"]) == 7


def test_tuesday_bucket() -> None:
    # 2026-04-21 is a Tuesday
    rep = wh.compute([_rec("2026-04-21T00:00:00+00:00")])
    assert rep["buckets"][1] == 1
    assert rep["total"] == 1


def test_sunday_bucket() -> None:
    # 2026-04-19 is a Sunday
    rep = wh.compute([_rec("2026-04-19T00:00:00+00:00")])
    assert rep["buckets"][6] == 1


def test_tz_conversion() -> None:
    # 01:00 +02:00 on Tuesday -> 23:00 UTC Monday
    rep = wh.compute([_rec("2026-04-21T01:00:00+02:00")])
    assert rep["buckets"][0] == 1


def test_invalid_ts_skipped() -> None:
    rep = wh.compute([_rec("nope"), _rec("2026-04-21T00:00:00+00:00")])
    assert rep["skipped"] == 1


def test_markdown_shape() -> None:
    md = wh.render_markdown(wh.compute([
        _rec("2026-04-21T00:00:00+00:00"),
    ]))
    assert "weekday histogram" in md
    assert "| Tue |" in md


def test_cli_fail_on_empty_weekdays(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_rec("2026-04-21T00:00:00+00:00")) + "\n",
        encoding="utf-8",
    )
    rc = wh.main([
        "--ledger", str(p), "--fail-on-empty-weekdays", "3",
    ])
    assert rc == 1


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_rec("2026-04-21T00:00:00+00:00")) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    rc = wh.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["total"] == 1


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = wh.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "ledger not found" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_weekday_histogram_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger weekday histogram" in names
    assert "Upload Plan 2.8 ledger weekday histogram" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger weekday histogram")
    assert "plan_2_8_ledger_weekday_histogram.py" in step["run"]
