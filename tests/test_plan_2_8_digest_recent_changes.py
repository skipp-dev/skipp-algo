"""Tests for ``scripts/plan_2_8_digest_recent_changes.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_recent_changes.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_recent_changes", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_recent_changes"] = mod
    spec.loader.exec_module(mod)
    return mod


rc_mod = _load()


def _rec(ts: str, status: str) -> dict[str, Any]:
    return {"captured_at": ts, "status": status}


def test_empty_no_changes() -> None:
    rep = rc_mod.extract([], limit=10)
    assert rep["total_changes"] == 0
    assert rep["changes"] == []


def test_no_transitions_when_same_status() -> None:
    rep = rc_mod.extract([
        _rec("2026-04-20T00:00:00+00:00", "green"),
        _rec("2026-04-21T00:00:00+00:00", "green"),
    ], limit=10)
    assert rep["total_changes"] == 0


def test_counts_only_transitions() -> None:
    rep = rc_mod.extract([
        _rec("2026-04-18T00:00:00+00:00", "green"),
        _rec("2026-04-19T00:00:00+00:00", "green"),
        _rec("2026-04-20T00:00:00+00:00", "amber"),
        _rec("2026-04-21T00:00:00+00:00", "green"),
    ], limit=10)
    assert rep["total_changes"] == 2
    assert rep["changes"][0]["from"] == "green"
    assert rep["changes"][0]["to"] == "amber"


def test_limit_keeps_tail() -> None:
    recs = [
        _rec("2026-04-18T00:00:00+00:00", "green"),
        _rec("2026-04-19T00:00:00+00:00", "amber"),
        _rec("2026-04-20T00:00:00+00:00", "green"),
        _rec("2026-04-21T00:00:00+00:00", "amber"),
    ]
    rep = rc_mod.extract(recs, limit=1)
    assert len(rep["changes"]) == 1
    assert rep["changes"][0]["to"] == "amber"
    assert rep["total_changes"] == 3


def test_limit_must_be_positive() -> None:
    with pytest.raises(ValueError):
        rc_mod.extract([], limit=0)


def test_invalid_statuses_dropped() -> None:
    rep = rc_mod.extract([
        _rec("2026-04-18T00:00:00+00:00", "green"),
        _rec("2026-04-19T00:00:00+00:00", "bogus"),
        _rec("2026-04-20T00:00:00+00:00", "amber"),
    ], limit=10)
    assert rep["total_changes"] == 1


def test_markdown_shape() -> None:
    md = rc_mod.render_markdown(rc_mod.extract([
        _rec("2026-04-20T00:00:00+00:00", "green"),
        _rec("2026-04-21T00:00:00+00:00", "amber"),
    ], limit=10))
    assert "captured_at" in md
    assert "green" in md and "amber" in md


def test_markdown_empty() -> None:
    md = rc_mod.render_markdown(rc_mod.extract([], limit=10))
    assert "No status changes" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        "\n".join(json.dumps(r) for r in [
            _rec("2026-04-20T00:00:00+00:00", "green"),
            _rec("2026-04-21T00:00:00+00:00", "amber"),
        ]) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    rc = rc_mod.main([
        "--ledger", str(p), "--format", "json",
        "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["total_changes"] == 1


def test_cli_bad_limit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text("", encoding="utf-8")
    rc = rc_mod.main(["--ledger", str(p), "--limit", "0"])
    assert rc == 1
    assert ">= 1" in capsys.readouterr().err


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = rc_mod.main(["--ledger", str(tmp_path / "nope.jsonl")])
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


def test_weekly_has_recent_changes_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 recent status changes" in names
    assert "Upload Plan 2.8 recent status changes" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 recent status changes")
    assert "plan_2_8_digest_recent_changes.py" in step["run"]
    assert "--limit  10" in step["run"]
