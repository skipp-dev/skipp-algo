"""Tests for ``scripts/plan_2_8_ledger_first_green_age.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_first_green_age.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_first_green_age", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_first_green_age"] = mod
    spec.loader.exec_module(mod)
    return mod


fg = _load()


def test_empty() -> None:
    rep = fg.compute([])
    assert rep["age_hours"] is None
    assert rep["first_green_at"] is None


def test_no_green() -> None:
    rep = fg.compute([{"status": "red", "captured_at": "2026-04-20T00:00:00+00:00"}])
    assert rep["age_hours"] is None


def test_first_green_picks_earliest() -> None:
    now = datetime(2026, 4, 20, 10, 0, tzinfo=UTC)
    rep = fg.compute(
        [
            {"status": "red", "captured_at": "2026-04-20T00:00:00+00:00"},
            {"status": "GREEN", "captured_at": "2026-04-20T03:00:00+00:00"},
            {"status": "green", "captured_at": "2026-04-20T08:00:00+00:00"},
        ],
        now=now,
    )
    assert rep["age_hours"] == 7.0


def test_bad_timestamp_skipped() -> None:
    now = datetime(2026, 4, 20, 10, 0, tzinfo=UTC)
    rep = fg.compute(
        [
            {"status": "green", "captured_at": "bogus"},
            {"status": "green", "captured_at": "2026-04-20T09:00:00+00:00"},
        ],
        now=now,
    )
    assert rep["age_hours"] == 1.0


def test_markdown_na() -> None:
    md = fg.render_markdown(fg.compute([]))
    assert "age_hours: n/a" in md


def test_cli_fail_below(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(
            {"status": "green", "captured_at": "2026-04-20T09:00:00+00:00"},
        ) + "\n",
        encoding="utf-8",
    )
    rc = fg.main([
        "--ledger", str(p),
        "--now", "2026-04-20T10:00:00+00:00",
        "--fail-below-hours", "2",
    ])
    assert rc == 1


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(
            {"status": "green", "captured_at": "2026-04-20T00:00:00+00:00"},
        ) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    rc = fg.main([
        "--ledger", str(p),
        "--now", "2026-04-20T02:00:00+00:00",
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["age_hours"] == 2.0


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = fg.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "ledger not found" in capsys.readouterr().err


def test_cli_bad_now(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text("", encoding="utf-8")
    rc = fg.main(["--ledger", str(p), "--now", "bogus"])
    assert rc == 1
    assert "bad --now" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_first_green_age_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger first green age" in names
    assert "Upload Plan 2.8 ledger first green age" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger first green age")
    assert "plan_2_8_ledger_first_green_age.py" in step["run"]
