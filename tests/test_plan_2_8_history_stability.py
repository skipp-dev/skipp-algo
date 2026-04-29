"""Tests for ``scripts/plan_2_8_history_stability.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_history_stability.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_history_stability", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_history_stability"] = mod
    spec.loader.exec_module(mod)
    return mod


stab = _load()


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


def test_empty_history_returns_empty_status() -> None:
    r = stab.stability_report([])
    assert r["status"] == "empty"
    assert r["counts"] == {"total": 0, "stable": 0, "unstable": 0, "warmup": 0}


def test_flat_series_reports_stable() -> None:
    snaps = [
        _snap(f"2026-04-{d:02d}T07:00:00Z", {("5m", "FVG"): (100, 0.60)})
        for d in (10, 11, 12, 13)
    ]
    r = stab.stability_report(snaps, min_samples=3, stddev_threshold=0.01)
    assert r["counts"]["stable"] == 1
    assert r["counts"]["unstable"] == 0
    entry = r["slices"][0]
    assert entry["stable"] is True
    assert entry["hr_stddev"] == 0.0


def test_varying_series_reports_unstable() -> None:
    hrs = [0.40, 0.70, 0.45, 0.75]
    snaps = [
        _snap(f"2026-04-{d:02d}T07:00:00Z", {("5m", "FVG"): (100, hr)})
        for d, hr in zip((10, 11, 12, 13), hrs, strict=True)
    ]
    r = stab.stability_report(snaps, min_samples=3, stddev_threshold=0.03)
    assert r["counts"]["unstable"] == 1
    entry = r["slices"][0]
    assert entry["stable"] is False
    assert entry["hr_range"] > 0.3


def test_warmup_when_below_min_samples() -> None:
    snaps = [
        _snap("2026-04-10T07:00:00Z", {("5m", "FVG"): (100, 0.5)}),
        _snap("2026-04-11T07:00:00Z", {("5m", "FVG"): (100, 0.5)}),
    ]
    r = stab.stability_report(snaps, min_samples=3)
    assert r["counts"]["warmup"] == 1
    assert r["slices"][0]["stable"] is None


def test_slices_below_min_events_are_excluded() -> None:
    snaps = [
        _snap(f"2026-04-{d:02d}T07:00:00Z", {
            ("5m", "FVG"): (100, 0.6),
            ("5m", "OB"):  (5,   0.9),  # too thin
        })
        for d in (10, 11, 12, 13)
    ]
    r = stab.stability_report(snaps, min_events=30)
    fams = {(s["tf"], s["family"]) for s in r["slices"]}
    assert fams == {("5m", "FVG")}


def test_window_limits_considered_snapshots() -> None:
    snaps = []
    for i, hr in enumerate([0.30, 0.30, 0.80, 0.80, 0.80, 0.80]):
        snaps.append(_snap(
            f"2026-04-{10+i:02d}T07:00:00Z",
            {("5m", "FVG"): (100, hr)},
        ))
    # Only the last 3 snapshots (all 0.80) should feed the stddev.
    r = stab.stability_report(snaps, window=3, min_samples=3,
                              stddev_threshold=0.01)
    assert r["counts"]["stable"] == 1
    assert r["slices"][0]["hr_stddev"] == 0.0


def test_render_markdown_ok_and_empty() -> None:
    snaps = [
        _snap(f"2026-04-{d:02d}T07:00:00Z", {("5m", "FVG"): (100, 0.60)})
        for d in (10, 11, 12, 13)
    ]
    md = stab.render_markdown(stab.stability_report(snaps))
    assert "Plan 2.8 slice stability" in md
    assert "No slices exceed" in md or "Unstable" in md
    md_empty = stab.render_markdown(stab.stability_report([]))
    assert "empty" in md_empty


def test_cli_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    history = tmp_path / "h.jsonl"
    snaps = [
        _snap(f"2026-04-{d:02d}T07:00:00Z", {("5m", "FVG"): (100, 0.6)})
        for d in (10, 11, 12, 13)
    ]
    _write(history, snaps)
    rc = stab.main([
        "--history", str(history), "--format", "json",
        "--window", "4", "--min-samples", "3",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["counts"]["total"] == 1


def test_cli_fail_on_unstable_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    history = tmp_path / "h.jsonl"
    hrs = [0.30, 0.70, 0.30, 0.70]
    _write(history, [
        _snap(f"2026-04-{d:02d}T07:00:00Z", {("5m", "FVG"): (100, hr)})
        for d, hr in zip((10, 11, 12, 13), hrs, strict=True)
    ])
    rc = stab.main([
        "--history", str(history),
        "--fail-on-unstable", "--stddev-threshold", "0.05",
        "--min-samples", "3", "--format", "json",
    ])
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["unstable"] == 1


def test_cli_missing_history_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = stab.main(["--history", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "history not found" in capsys.readouterr().err


def test_cli_writes_output_file(tmp_path: Path) -> None:
    history = tmp_path / "h.jsonl"
    _write(history, [
        _snap(f"2026-04-{d:02d}T07:00:00Z", {("5m", "FVG"): (100, 0.6)})
        for d in (10, 11, 12, 13)
    ])
    out = tmp_path / "report.md"
    rc = stab.main([
        "--history", str(history), "--output", str(out),
        "--min-samples", "3",
    ])
    assert rc == 0
    assert out.exists()
    assert "Plan 2.8 slice stability" in out.read_text(encoding="utf-8")
