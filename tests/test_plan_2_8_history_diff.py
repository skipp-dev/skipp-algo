"""Tests for ``scripts/plan_2_8_history_diff.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_history_diff.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_history_diff", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_history_diff"] = mod
    spec.loader.exec_module(mod)
    return mod


hd = _load()


def _snap(captured_at: str, hr: float, n: int = 100,
          scoring_root: str = "out/x") -> dict:
    return {
        "captured_at": captured_at, "scoring_root": scoring_root,
        "files_scanned": 1,
        "per_tf": {
            "5m":  {"n_events": n, "hit_rate": hr,
                    "families": {"FVG": {"n_events": n, "hit_rate": hr}}},
            "15m": {"n_events": n, "hit_rate": hr - 0.05,
                    "families": {"FVG": {"n_events": n, "hit_rate": hr - 0.05}}},
        },
    }


def _write(history: Path, snaps: list[dict]) -> None:
    history.write_text("\n".join(json.dumps(s) for s in snaps) + "\n",
                       encoding="utf-8")


def test_diff_returns_per_tf_and_per_family_deltas() -> None:
    a = _snap("2026-04-14T07:00:00Z", 0.40)
    b = _snap("2026-04-21T07:00:00Z", 0.50)
    diff = hd.diff_snapshots(a, b)
    assert diff["prev"]["captured_at"] == "2026-04-14T07:00:00Z"
    assert diff["latest"]["captured_at"] == "2026-04-21T07:00:00Z"
    tfs = {r["tf"]: r for r in diff["per_tf"]}
    assert pytest.approx(tfs["5m"]["delta_pp"]) == 0.10
    assert pytest.approx(tfs["15m"]["delta_pp"]) == 0.10
    fams = {(r["tf"], r["family"]): r for r in diff["per_family"]}
    assert pytest.approx(fams[("5m", "FVG")]["delta_pp"]) == 0.10


def test_diff_handles_missing_tf_in_one_snapshot() -> None:
    a = _snap("2026-04-14T07:00:00Z", 0.40)
    b = _snap("2026-04-21T07:00:00Z", 0.50)
    del b["per_tf"]["15m"]
    diff = hd.diff_snapshots(a, b)
    tfs = {r["tf"]: r for r in diff["per_tf"]}
    assert tfs["15m"]["delta_pp"] is None
    assert tfs["15m"]["hr_latest"] is None
    assert tfs["5m"]["delta_pp"] is not None


def test_diff_render_markdown_smoke() -> None:
    a = _snap("2026-04-14T07:00:00Z", 0.40)
    b = _snap("2026-04-21T07:00:00Z", 0.50)
    md = hd.render_markdown(hd.diff_snapshots(a, b))
    assert "Plan 2.8 history snapshot diff" in md
    assert "2026-04-14T07:00:00Z" in md
    assert "+0.100" in md
    assert "Per-TF" in md
    assert "Per-TF x family" in md


def test_cli_defaults_to_last_two_snapshots(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    history = tmp_path / "h.jsonl"
    _write(history, [
        _snap("2026-04-07T07:00:00Z", 0.30),
        _snap("2026-04-14T07:00:00Z", 0.40),
        _snap("2026-04-21T07:00:00Z", 0.55),
    ])
    rc = hd.main(["--history", str(history), "--format", "json"])
    assert rc == 0
    diff = json.loads(capsys.readouterr().out)
    assert diff["prev"]["captured_at"] == "2026-04-14T07:00:00Z"
    assert diff["latest"]["captured_at"] == "2026-04-21T07:00:00Z"


def test_cli_select_by_captured_at(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    history = tmp_path / "h.jsonl"
    _write(history, [
        _snap("2026-04-07T07:00:00Z", 0.30),
        _snap("2026-04-14T07:00:00Z", 0.40),
        _snap("2026-04-21T07:00:00Z", 0.55),
    ])
    rc = hd.main([
        "--history", str(history),
        "--prev-captured-at",   "2026-04-07T07:00:00Z",
        "--latest-captured-at", "2026-04-21T07:00:00Z",
        "--format", "json",
    ])
    assert rc == 0
    diff = json.loads(capsys.readouterr().out)
    assert diff["prev"]["captured_at"] == "2026-04-07T07:00:00Z"


def test_cli_errors_when_too_few_snapshots(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    history = tmp_path / "h.jsonl"
    _write(history, [_snap("2026-04-21T07:00:00Z", 0.5)])
    rc = hd.main(["--history", str(history)])
    assert rc == 1
    assert "at least 2" in capsys.readouterr().err


def test_cli_errors_on_unknown_captured_at(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    history = tmp_path / "h.jsonl"
    _write(history, [
        _snap("2026-04-14T07:00:00Z", 0.4),
        _snap("2026-04-21T07:00:00Z", 0.5),
    ])
    rc = hd.main([
        "--history", str(history),
        "--prev-captured-at", "1999-01-01T00:00:00Z",
    ])
    assert rc == 1
    assert "no snapshot with captured_at" in capsys.readouterr().err


def test_cli_writes_output_file(tmp_path: Path) -> None:
    history = tmp_path / "h.jsonl"
    _write(history, [
        _snap("2026-04-14T07:00:00Z", 0.4),
        _snap("2026-04-21T07:00:00Z", 0.5),
    ])
    out = tmp_path / "diff.md"
    rc = hd.main(["--history", str(history), "--output", str(out)])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "Plan 2.8 history snapshot diff" in text
    assert "+0.100" in text


def test_cli_missing_history_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = hd.main(["--history", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "history not found" in capsys.readouterr().err
