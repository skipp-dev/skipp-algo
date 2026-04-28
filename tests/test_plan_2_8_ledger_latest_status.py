"""Tests for ``scripts/plan_2_8_ledger_latest_status.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_latest_status.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_latest_status", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_latest_status"] = mod
    spec.loader.exec_module(mod)
    return mod


ls = _load()


def _write_ledger(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )


def test_latest_from_records() -> None:
    records = [
        {"captured_at": "2026-04-20T00:00:00+00:00", "status": "amber"},
        {"captured_at": "2026-04-21T00:00:00+00:00", "status": "green"},
    ]
    r = ls.latest(records)
    assert r["status"] == "green"
    assert r["captured_at"].startswith("2026-04-21")


def test_empty_returns_unknown() -> None:
    r = ls.latest([])
    assert r["status"] == "unknown"
    assert r["captured_at"] is None


def test_invalid_status_skipped() -> None:
    records = [
        {"captured_at": "2026-04-20T00:00:00+00:00", "status": "green"},
        {"captured_at": "2026-04-21T00:00:00+00:00", "status": "bogus"},
    ]
    r = ls.latest(records)
    assert r["status"] == "green"


def test_carries_run_url() -> None:
    records = [{
        "captured_at": "2026-04-21T00:00:00+00:00",
        "status":      "red",
        "run_url":     "https://example.test/run/1",
    }]
    r = ls.latest(records)
    assert r["run_url"] == "https://example.test/run/1"


def test_render_markdown_shape() -> None:
    md = ls.render_markdown({
        "status": "green",
        "captured_at": "2026-04-21T00:00:00+00:00",
        "run_url": None,
    })
    assert md.startswith("# Plan 2.8 latest status")
    assert "status:" in md


def test_cli_json_output(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    _write_ledger(p, [{
        "captured_at": "2026-04-21T00:00:00+00:00",
        "status":      "amber",
    }])
    out = tmp_path / "o.json"
    rc = ls.main([
        "--ledger", str(p),
        "--format", "json",
        "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "amber"


def test_cli_md_output(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    _write_ledger(p, [{
        "captured_at": "2026-04-21T00:00:00+00:00",
        "status":      "green",
    }])
    out = tmp_path / "o.md"
    rc = ls.main([
        "--ledger", str(p),
        "--format", "md",
        "--output", str(out),
    ])
    assert rc == 0
    assert "green" in out.read_text(encoding="utf-8")


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ls.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "ledger not found" in capsys.readouterr().err


def test_cli_empty_ledger_returns_unknown(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text("", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = ls.main([
        "--ledger", str(p),
        "--format", "json",
        "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "unknown"


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_latest_status_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 latest status" in names
    assert "Upload Plan 2.8 latest status" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 latest status")
    assert "plan_2_8_ledger_latest_status.py" in step["run"]
