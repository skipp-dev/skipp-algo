"""Tests for ``scripts/plan_2_8_top_movers.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_top_movers.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_top_movers", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_top_movers"] = mod
    spec.loader.exec_module(mod)
    return mod


tm = _load()


def _snap(captured_at: str, families: dict[str, dict]) -> dict:
    per_tf: dict[str, dict] = {}
    for (tf, family), row in families.items():
        bucket = per_tf.setdefault(tf, {"n_events": 0, "hit_rate": 0.0, "families": {}})
        bucket["families"][family] = row
    return {"captured_at": captured_at, "scoring_root": "out/x",
            "files_scanned": 1, "per_tf": per_tf}


def _default_snap(captured_at: str, hr_5m_fvg: float,
                  hr_15m_ob: float, n: int = 100) -> dict:
    return _snap(captured_at, {
        ("5m", "FVG"):  {"n_events": n, "hit_rate": hr_5m_fvg},
        ("15m", "OB"):  {"n_events": n, "hit_rate": hr_15m_ob},
    })


def _write(history: Path, snaps: list[dict]) -> None:
    history.write_text("\n".join(json.dumps(s) for s in snaps) + "\n",
                       encoding="utf-8")


def test_top_movers_status_empty_when_no_snapshots() -> None:
    report = tm.top_movers([], lookback_days=7)
    assert report["status"] == "empty"
    assert report["gainers"] == []
    assert report["losers"] == []


def test_top_movers_status_warmup_when_only_one_in_window() -> None:
    snaps = [_default_snap("2026-04-21T07:00:00Z", 0.5, 0.5)]
    report = tm.top_movers(snaps, lookback_days=7)
    assert report["status"] == "warmup"
    assert report["latest_captured_at"] == "2026-04-21T07:00:00Z"


def test_top_movers_ranks_by_absolute_delta() -> None:
    snaps = [
        _default_snap("2026-04-14T07:00:00Z", 0.40, 0.50),
        _default_snap("2026-04-21T07:00:00Z", 0.55, 0.30),
    ]
    report = tm.top_movers(snaps, lookback_days=7, top_n=5)
    assert report["status"] == "ok"
    # Biggest gainer: 5m/FVG +0.15.
    assert report["gainers"][0]["tf"] == "5m"
    assert report["gainers"][0]["family"] == "FVG"
    assert pytest.approx(report["gainers"][0]["delta_pp"]) == 0.15
    # Biggest loser: 15m/OB -0.20.
    assert report["losers"][0]["tf"] == "15m"
    assert report["losers"][0]["family"] == "OB"
    assert pytest.approx(report["losers"][0]["delta_pp"]) == -0.20


def test_top_movers_respects_min_events_floor() -> None:
    snaps = [
        _default_snap("2026-04-14T07:00:00Z", 0.40, 0.50, n=10),  # below floor
        _default_snap("2026-04-21T07:00:00Z", 0.90, 0.50, n=10),
    ]
    report = tm.top_movers(snaps, lookback_days=7, min_events=30)
    assert report["gainers"] == []
    assert report["losers"] == []


def test_top_movers_honors_top_n() -> None:
    fams = [("5m", f"F{i}") for i in range(10)]
    earliest = _snap("2026-04-14T07:00:00Z",
                     {f: {"n_events": 100, "hit_rate": 0.5} for f in fams})
    latest = _snap("2026-04-21T07:00:00Z",
                   {f: {"n_events": 100, "hit_rate": 0.5 + 0.01 * i}
                    for i, f in enumerate(fams)})
    report = tm.top_movers([earliest, latest], lookback_days=7, top_n=3)
    assert len(report["gainers"]) == 3
    assert len(report["losers"]) == 3


def test_top_movers_uses_earliest_in_window() -> None:
    # Out-of-window snapshot should not become the baseline.
    snaps = [
        _default_snap("2026-01-01T00:00:00Z", 0.10, 0.10),
        _default_snap("2026-04-14T07:00:00Z", 0.40, 0.50),
        _default_snap("2026-04-21T07:00:00Z", 0.55, 0.30),
    ]
    report = tm.top_movers(snaps, lookback_days=7)
    assert report["earliest_captured_at"] == "2026-04-14T07:00:00Z"
    assert report["latest_captured_at"]   == "2026-04-21T07:00:00Z"


def test_render_markdown_ok_shape() -> None:
    snaps = [
        _default_snap("2026-04-14T07:00:00Z", 0.40, 0.50),
        _default_snap("2026-04-21T07:00:00Z", 0.55, 0.30),
    ]
    md = tm.render_markdown(tm.top_movers(snaps, lookback_days=7))
    assert "Plan 2.8 top movers" in md
    assert "Gainers" in md and "Losers" in md
    assert "+0.150" in md
    assert "-0.200" in md


def test_render_markdown_warmup() -> None:
    md = tm.render_markdown(tm.top_movers([], lookback_days=7))
    assert "status" in md
    assert "empty" in md


def test_cli_emits_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    history = tmp_path / "h.jsonl"
    _write(history, [
        _default_snap("2026-04-14T07:00:00Z", 0.40, 0.50),
        _default_snap("2026-04-21T07:00:00Z", 0.55, 0.30),
    ])
    rc = tm.main(["--history", str(history),
                  "--lookback-days", "7", "--format", "json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert len(payload["gainers"]) >= 1


def test_cli_writes_output(tmp_path: Path) -> None:
    history = tmp_path / "h.jsonl"
    _write(history, [
        _default_snap("2026-04-14T07:00:00Z", 0.40, 0.50),
        _default_snap("2026-04-21T07:00:00Z", 0.55, 0.30),
    ])
    out = tmp_path / "movers.md"
    rc = tm.main(["--history", str(history),
                  "--lookback-days", "7",
                  "--output", str(out)])
    assert rc == 0
    assert "Plan 2.8 top movers" in out.read_text(encoding="utf-8")


def test_cli_missing_history(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = tm.main(["--history", str(tmp_path / "no.jsonl")])
    assert rc == 1
    assert "history not found" in capsys.readouterr().err
