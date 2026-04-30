"""Tests for ``scripts/plan_2_8_ledger_latest_captured_at.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_latest_captured_at.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_latest_captured_at", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_latest_captured_at"] = mod
    spec.loader.exec_module(mod)
    return mod


lc = _load()


def test_empty() -> None:
    assert lc.compute([]) == {"schema_version": 1, "found": False}


def test_tail_valid() -> None:
    now = datetime(2026, 4, 20, 10, 0, tzinfo=UTC)
    rep = lc.compute(
        [
            {"status": "red", "captured_at": "2026-04-20T00:00:00+00:00"},
            {"status": "green", "captured_at": "2026-04-20T09:00:00+00:00"},
        ],
        now=now,
    )
    assert rep["found"] is True
    assert rep["age_hours"] == 1.0


def test_tail_invalid_skipped() -> None:
    now = datetime(2026, 4, 20, 10, 0, tzinfo=UTC)
    rep = lc.compute(
        [
            {"status": "green", "captured_at": "2026-04-20T05:00:00+00:00"},
            {"status": "green", "captured_at": "bogus"},
        ],
        now=now,
    )
    assert rep["found"] is True
    assert rep["captured_at"] == "2026-04-20T05:00:00+00:00"


def test_markdown_none() -> None:
    md = lc.render_markdown(lc.compute([]))
    assert "_none_" in md


def test_cli_fail_above(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(
            {"status": "green", "captured_at": "2026-04-20T00:00:00+00:00"},
        ) + "\n",
        encoding="utf-8",
    )
    rc = lc.main([
        "--ledger", str(p),
        "--now", "2026-04-20T10:00:00+00:00",
        "--fail-above-hours", "5",
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
    rc = lc.main([
        "--ledger", str(p),
        "--now", "2026-04-20T01:00:00+00:00",
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["age_hours"] == 1.0


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = lc.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "ledger not found" in capsys.readouterr().err


def test_cli_bad_now(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text("", encoding="utf-8")
    rc = lc.main(["--ledger", str(p), "--now", "bogus"])
    assert rc == 1
    assert "bad --now" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_latest_captured_at_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger latest captured_at" in names
    assert "Upload Plan 2.8 ledger latest captured_at" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger latest captured_at")
    assert "plan_2_8_ledger_latest_captured_at.py" in step["run"]
