"""Tests for ``scripts/plan_2_8_run_stamp.py``."""

from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_run_stamp.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_run_stamp", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_run_stamp"] = mod
    spec.loader.exec_module(mod)
    return mod


rs = _load()


def test_build_uses_explicit_args(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("GITHUB_RUN_ID", "GITHUB_SHA", "GITHUB_REF", "GITHUB_ACTOR"):
        monkeypatch.delenv(k, raising=False)
    now = _dt.datetime(2026, 4, 21, 12, 0, tzinfo=_dt.UTC)
    stamp = rs.build(
        run_id="123", run_url="https://x",
        sha="abc", ref="refs/heads/main", actor="me",
        now=now,
    )
    assert stamp["run_id"] == "123"
    assert stamp["run_url"] == "https://x"
    assert stamp["sha"] == "abc"
    assert stamp["ref"] == "refs/heads/main"
    assert stamp["actor"] == "me"
    assert stamp["captured_at"].startswith("2026-04-21T12:00:00")
    assert stamp["schema_version"] == 1


def test_build_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_RUN_ID", "envrun")
    monkeypatch.setenv("GITHUB_SHA", "envsha")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/dev")
    monkeypatch.setenv("GITHUB_ACTOR", "envactor")
    stamp = rs.build()
    assert stamp["run_id"] == "envrun"
    assert stamp["sha"] == "envsha"
    assert stamp["ref"] == "refs/heads/dev"
    assert stamp["actor"] == "envactor"


def test_build_null_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("GITHUB_RUN_ID", "GITHUB_SHA", "GITHUB_REF", "GITHUB_ACTOR"):
        monkeypatch.delenv(k, raising=False)
    stamp = rs.build()
    assert stamp["run_id"] is None
    assert stamp["run_url"] is None
    assert stamp["sha"] is None


def test_cli_writes_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    for k in ("GITHUB_RUN_ID", "GITHUB_SHA", "GITHUB_REF", "GITHUB_ACTOR"):
        monkeypatch.delenv(k, raising=False)
    out = tmp_path / "stamp.json"
    rc = rs.main([
        "--output", str(out),
        "--run-id", "99", "--run-url", "https://run/99",
        "--quiet",
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["run_id"] == "99"
    assert payload["run_url"] == "https://run/99"


def test_cli_creates_parent_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = tmp_path / "nested" / "deep" / "stamp.json"
    rc = rs.main(["--output", str(out), "--quiet"])
    assert rc == 0
    assert out.exists()


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_run_stamp_step() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 run stamp" in names
    assert "Upload Plan 2.8 run stamp" in names
    step = next(s for s in steps if s.get("name") == "Plan 2.8 run stamp")
    assert "plan_2_8_run_stamp.py" in step["run"]
    assert "RUN_URL" in step["run"]
