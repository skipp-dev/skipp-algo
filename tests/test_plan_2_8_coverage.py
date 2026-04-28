"""Tests for ``scripts/plan_2_8_coverage.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_coverage.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_coverage", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_coverage"] = mod
    spec.loader.exec_module(mod)
    return mod


cov = _load()


def _snap(captured_at: str, fams: dict[tuple[str, str], int]) -> dict:
    per_tf: dict[str, dict] = {}
    for (tf, fam), n in fams.items():
        bucket = per_tf.setdefault(tf, {"n_events": 0, "hit_rate": 0.0, "families": {}})
        bucket["families"][fam] = {"n_events": n, "hit_rate": 0.5}
    return {"captured_at": captured_at, "scoring_root": "out/x",
            "files_scanned": 1, "per_tf": per_tf}


def _write(history: Path, snaps: list[dict]) -> None:
    history.write_text("\n".join(json.dumps(s) for s in snaps) + "\n",
                       encoding="utf-8")


def test_coverage_empty_when_no_snapshots() -> None:
    report = cov.coverage_report([])
    assert report["status"] == "empty"
    assert report["slices"] == []
    assert report["counts"] == {"total": 0, "ok": 0, "under": 0}


def test_coverage_flags_under_threshold_slices() -> None:
    snap = _snap("2026-04-21T07:00:00Z", {
        ("5m", "FVG"): 100,
        ("5m", "OB"):  10,
        ("15m", "FVG"): 25,
    })
    report = cov.coverage_report([snap], min_events=30)
    assert report["status"] == "ok"
    assert report["counts"] == {"total": 3, "ok": 1, "under": 2}
    under = {(s["tf"], s["family"]) for s in report["under_threshold"]}
    assert under == {("5m", "OB"), ("15m", "FVG")}


def test_coverage_uses_latest_snapshot() -> None:
    old = _snap("2026-04-14T07:00:00Z", {("5m", "FVG"): 10})
    new = _snap("2026-04-21T07:00:00Z", {("5m", "FVG"): 500})
    report = cov.coverage_report([old, new])
    assert report["latest_captured_at"] == "2026-04-21T07:00:00Z"
    assert report["counts"]["ok"] == 1


def test_render_markdown_ok_path() -> None:
    snap = _snap("2026-04-21T07:00:00Z", {("5m", "FVG"): 5})
    md = cov.render_markdown(cov.coverage_report([snap], min_events=30))
    assert "Plan 2.8 slice coverage" in md
    assert "Under threshold" in md
    assert "`2026-04-21T07:00:00Z`" in md


def test_render_markdown_all_ok_path() -> None:
    snap = _snap("2026-04-21T07:00:00Z", {("5m", "FVG"): 500})
    md = cov.render_markdown(cov.coverage_report([snap], min_events=30))
    assert "At or above" in md or "No action needed" in md


def test_render_markdown_empty() -> None:
    md = cov.render_markdown(cov.coverage_report([]))
    assert "empty" in md


def test_cli_emits_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    history = tmp_path / "h.jsonl"
    _write(history, [_snap("2026-04-21T07:00:00Z", {("5m", "FVG"): 100})])
    rc = cov.main(["--history", str(history), "--format", "json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["counts"]["ok"] == 1


def test_cli_fail_on_under_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    history = tmp_path / "h.jsonl"
    _write(history, [_snap("2026-04-21T07:00:00Z", {("5m", "FVG"): 1})])
    rc = cov.main([
        "--history", str(history),
        "--fail-on-under",
        "--format", "json",
    ])
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["under"] == 1


def test_cli_fail_on_under_noop_when_all_ok(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    history = tmp_path / "h.jsonl"
    _write(history, [_snap("2026-04-21T07:00:00Z", {("5m", "FVG"): 500})])
    rc = cov.main(["--history", str(history), "--fail-on-under"])
    assert rc == 0


def test_cli_missing_history_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = cov.main(["--history", str(tmp_path / "no.jsonl")])
    assert rc == 1
    assert "history not found" in capsys.readouterr().err
