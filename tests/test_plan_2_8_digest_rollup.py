"""Tests for ``scripts/plan_2_8_digest_rollup.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_rollup.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_digest_rollup", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_rollup"] = mod
    spec.loader.exec_module(mod)
    return mod


rl = _load()


def _snap(captured_at: str, fams: dict[tuple[str, str], tuple[int, float]]) -> dict:
    per_tf: dict[str, dict] = {}
    for (tf, fam), (n, hr) in fams.items():
        bucket = per_tf.setdefault(tf, {"n_events": 0, "hit_rate": 0.0, "families": {}})
        bucket["families"][fam] = {"n_events": n, "hit_rate": hr}
    return {"captured_at": captured_at, "scoring_root": "out/x",
            "files_scanned": 1, "per_tf": per_tf}


def _write(p: Path, snaps: list[dict]) -> None:
    p.write_text("\n".join(json.dumps(s) for s in snaps) + "\n",
                 encoding="utf-8")


def test_empty_history() -> None:
    r = rl.rollup([])
    assert r["status"] == "empty"
    assert r["slices"] == []


def test_one_snapshot_per_week_buckets_correctly() -> None:
    # Mondays: 2026-04-06, 2026-04-13, 2026-04-20.
    snaps = [
        _snap("2026-04-06T12:00:00Z", {("5m", "FVG"): (100, 0.40)}),
        _snap("2026-04-13T12:00:00Z", {("5m", "FVG"): (100, 0.50)}),
        _snap("2026-04-20T12:00:00Z", {("5m", "FVG"): (100, 0.60)}),
    ]
    r = rl.rollup(snaps, weeks=3)
    assert r["week_keys"] == ["2026-04-06", "2026-04-13", "2026-04-20"]
    assert r["slices"][0]["series"] == [0.4, 0.5, 0.6]
    assert r["slices"][0]["trend_pp"] == 0.2
    assert r["slices"][0]["latest"] == 0.6


def test_multiple_in_same_week_keeps_latest() -> None:
    snaps = [
        _snap("2026-04-06T00:00:00Z", {("5m", "FVG"): (100, 0.30)}),
        _snap("2026-04-08T00:00:00Z", {("5m", "FVG"): (100, 0.90)}),
    ]
    r = rl.rollup(snaps, weeks=1)
    assert r["slices"][0]["series"] == [0.9]


def test_below_min_events_emits_none() -> None:
    snaps = [
        _snap("2026-04-06T12:00:00Z", {("5m", "FVG"): (5, 0.40)}),
        _snap("2026-04-13T12:00:00Z", {("5m", "FVG"): (100, 0.60)}),
    ]
    r = rl.rollup(snaps, weeks=2, min_events=30)
    assert r["slices"][0]["series"] == [None, 0.6]
    assert r["slices"][0]["observed"] == 1


def test_weeks_parameter_limits_window() -> None:
    snaps = [
        _snap(f"2026-0{m}-06T12:00:00Z", {("5m", "FVG"): (100, 0.5)})
        for m in (1, 2, 3, 4)
    ]
    r = rl.rollup(snaps, weeks=2)
    assert len(r["week_keys"]) == 2


def test_render_markdown_contains_sparkline() -> None:
    snaps = [
        _snap("2026-04-06T12:00:00Z", {("5m", "FVG"): (100, 0.40)}),
        _snap("2026-04-13T12:00:00Z", {("5m", "FVG"): (100, 0.80)}),
    ]
    md = rl.render_markdown(rl.rollup(snaps, weeks=2))
    assert "Plan 2.8 rolling HR trend" in md
    assert "| 5m | FVG |" in md


def test_render_markdown_empty() -> None:
    md = rl.render_markdown(rl.rollup([]))
    assert "empty" in md


def test_sparkline_handles_missing_and_flat() -> None:
    assert "." in rl._sparkline([0.5, None, 0.5])
    assert rl._sparkline([0.5, 0.5, 0.5]).strip(".") != ""
    assert rl._sparkline([None, None]) == ".."


def test_cli_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    history = tmp_path / "h.jsonl"
    _write(history, [
        _snap("2026-04-06T12:00:00Z", {("5m", "FVG"): (100, 0.4)}),
        _snap("2026-04-13T12:00:00Z", {("5m", "FVG"): (100, 0.5)}),
    ])
    rc = rl.main([
        "--history", str(history), "--weeks", "2", "--format", "json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"


def test_cli_missing_history_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = rl.main(["--history", str(tmp_path / "nope.jsonl")])
    assert rc == 1
