"""Tests for ``scripts/plan_2_8_digest_archive.py`` + batch #69 wiring."""

from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_archive.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_digest_archive", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_archive"] = mod
    spec.loader.exec_module(mod)
    return mod


da = _load()


def _seed_digest(p: Path, captured_at: str | None, alerts: list | None = None) -> None:
    payload: dict[str, Any] = {"alerts": alerts or []}
    if captured_at is not None:
        payload["captured_at"] = captured_at
    p.write_text(json.dumps(payload), encoding="utf-8")


def test_archive_uses_captured_at(tmp_path: Path) -> None:
    src = tmp_path / "digest.json"
    _seed_digest(src, "2026-04-21T12:00:00Z")
    arc = tmp_path / "arc"
    rep = da.archive(src, arc)
    assert (arc / "2026-04-21.json").exists()
    assert rep["target"] == "2026-04-21.json"


def test_archive_falls_back_to_today(tmp_path: Path) -> None:
    src = tmp_path / "digest.json"
    _seed_digest(src, None)
    arc = tmp_path / "arc"
    rep = da.archive(src, arc)
    today = _dt.date.today().isoformat()
    assert (arc / f"{today}.json").exists()
    assert rep["target"] == f"{today}.json"


def test_archive_uses_fallback_when_captured_at_invalid(tmp_path: Path) -> None:
    src = tmp_path / "digest.json"
    _seed_digest(src, "not-a-date")
    arc = tmp_path / "arc"
    rep = da.archive(src, arc, fallback_date="2026-01-01")
    assert (arc / "2026-01-01.json").exists()
    assert rep["target"] == "2026-01-01.json"


def test_same_date_overwrites(tmp_path: Path) -> None:
    src = tmp_path / "digest.json"
    _seed_digest(src, "2026-04-21T12:00:00Z", alerts=[{"tf": "5m"}])
    arc = tmp_path / "arc"
    da.archive(src, arc)
    # Overwrite with different payload.
    _seed_digest(src, "2026-04-21T12:00:00Z", alerts=[{"tf": "15m"}])
    rep = da.archive(src, arc)
    assert rep["target"] == "2026-04-21.json"
    stored = json.loads((arc / "2026-04-21.json").read_text(encoding="utf-8"))
    assert stored["alerts"] == [{"tf": "15m"}]


def test_rotation_removes_oldest(tmp_path: Path) -> None:
    arc = tmp_path / "arc"
    arc.mkdir()
    # Seed 5 pre-existing dated archives.
    for day in ("2026-01-01", "2026-01-08", "2026-01-15",
                "2026-01-22", "2026-01-29"):
        (arc / f"{day}.json").write_text("{}", encoding="utf-8")
    src = tmp_path / "digest.json"
    _seed_digest(src, "2026-02-05T00:00:00Z")
    rep = da.archive(src, arc, keep=3)
    remaining = sorted(p.name for p in arc.glob("*.json"))
    assert remaining == ["2026-01-22.json", "2026-01-29.json",
                         "2026-02-05.json"]
    assert "2026-01-01.json" in rep["removed"]
    assert "2026-01-08.json" in rep["removed"]
    assert "2026-01-15.json" in rep["removed"]


def test_rotation_keeps_all_below_threshold(tmp_path: Path) -> None:
    arc = tmp_path / "arc"
    src = tmp_path / "digest.json"
    _seed_digest(src, "2026-01-01T00:00:00Z")
    rep = da.archive(src, arc, keep=10)
    assert rep["removed"] == []


def test_latest_two_returns_two_most_recent(tmp_path: Path) -> None:
    arc = tmp_path / "arc"
    arc.mkdir()
    for day in ("2026-01-01", "2026-01-08", "2026-01-15"):
        (arc / f"{day}.json").write_text("{}", encoding="utf-8")
    two = da.latest_two(arc)
    assert [p.name for p in two] == ["2026-01-08.json", "2026-01-15.json"]


def test_latest_two_empty_dir(tmp_path: Path) -> None:
    arc = tmp_path / "arc"
    arc.mkdir()
    assert da.latest_two(arc) == []


def test_cli_emit_latest_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    arc = tmp_path / "arc"
    arc.mkdir()
    (arc / "2026-01-01.json").write_text("{}", encoding="utf-8")
    src = tmp_path / "digest.json"
    _seed_digest(src, "2026-02-01T00:00:00Z")
    rc = da.main([
        "--digest", str(src), "--archive-dir", str(arc),
        "--emit-latest-two",
    ])
    assert rc == 0
    lines = capsys.readouterr().out.strip().splitlines()
    # First lines are the JSON report; last two are the paths.
    paths = lines[-2:]
    assert paths[-1].endswith("2026-02-01.json")
    assert paths[-2].endswith("2026-01-01.json")


def test_cli_missing_digest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = da.main([
        "--digest", str(tmp_path / "nope.json"),
        "--archive-dir", str(tmp_path / "arc"),
    ])
    assert rc == 1
    assert "digest not found" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_status_snapshot_step() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 status snapshot" in names
    assert "Upload Plan 2.8 status snapshot" in names
    step = next(s for s in steps if s.get("name") == "Plan 2.8 status snapshot")
    assert "plan_2_8_status_snapshot.py" in step["run"]


def test_weekly_has_runbook_toc_step() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 runbook TOC sidebar" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 runbook TOC sidebar")
    assert "plan_2_8_runbook_toc.py" in step["run"]
    assert "runbook_toc.md" in step["run"]
