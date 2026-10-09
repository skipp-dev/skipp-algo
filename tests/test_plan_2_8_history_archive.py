"""Tests for ``scripts/plan_2_8_history_archive.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_history_archive.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_history_archive", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_history_archive"] = mod
    spec.loader.exec_module(mod)
    return mod


arch = _load()


def _rollup(scoring_root: str) -> dict:
    return {
        "schema_version": 1,
        "scoring_root": scoring_root,
        "files_scanned": 4,
        "per_tf": {
            "5m": {
                "n_events": 100, "hit_rate": 0.45, "symbols": ["A", "B"],
                "families": {
                    "FVG": {"n_events": 60, "hit_rate": 0.46},
                    "BOS": {"n_events": 40, "hit_rate": 0.43},
                },
            },
            "4H": {
                "n_events": 30, "hit_rate": 0.40, "symbols": ["A"],
                "families": {"BOS": {"n_events": 30, "hit_rate": 0.40}},
            },
        },
    }


def test_append_snapshot_writes_jsonl(tmp_path: Path) -> None:
    history = tmp_path / "hist.jsonl"
    res = arch.append_snapshot(
        rollup=_rollup("out/2026-04-21"),
        history_path=history,
        captured_at="2026-04-21T07:35:00Z",
    )
    assert res["appended"] is True
    assert res["history_size"] == 1
    line = history.read_text(encoding="utf-8").strip()
    snap = json.loads(line)
    assert snap["captured_at"] == "2026-04-21T07:35:00Z"
    assert snap["scoring_root"] == "out/2026-04-21"
    assert snap["per_tf"]["5m"]["families"]["FVG"]["hit_rate"] == pytest.approx(0.46)
    # Symbols field intentionally not in projection.
    assert "symbols" not in snap["per_tf"]["5m"]


def test_append_snapshot_is_idempotent(tmp_path: Path) -> None:
    history = tmp_path / "hist.jsonl"
    args = dict(
        rollup=_rollup("out/2026-04-21"),
        history_path=history,
        captured_at="2026-04-21T07:35:00Z",
    )
    first = arch.append_snapshot(**args)
    second = arch.append_snapshot(**args)
    assert first["appended"] is True
    assert second["appended"] is False
    assert history.read_text(encoding="utf-8").count("\n") == 1


def test_append_snapshot_dedup_key_includes_scoring_root(tmp_path: Path) -> None:
    history = tmp_path / "hist.jsonl"
    arch.append_snapshot(
        rollup=_rollup("out/2026-04-21"), history_path=history,
        captured_at="2026-04-21T07:35:00Z",
    )
    # Same timestamp, different scoring_root -> NEW snapshot.
    res = arch.append_snapshot(
        rollup=_rollup("out/2026-04-22"), history_path=history,
        captured_at="2026-04-21T07:35:00Z",
    )
    assert res["appended"] is True
    assert res["history_size"] == 2


def test_append_snapshot_tolerates_corrupt_existing_lines(tmp_path: Path) -> None:
    history = tmp_path / "hist.jsonl"
    history.write_text("not json\n", encoding="utf-8")
    res = arch.append_snapshot(
        rollup=_rollup("out/2026-04-21"), history_path=history,
        captured_at="2026-04-21T07:35:00Z",
    )
    assert res["appended"] is True
    # Original junk line is preserved (we never rewrite).
    text = history.read_text(encoding="utf-8")
    assert text.startswith("not json\n")
    assert text.count("\n") == 2


def test_append_snapshot_creates_history_parent(tmp_path: Path) -> None:
    history = tmp_path / "deeper" / "still" / "hist.jsonl"
    arch.append_snapshot(
        rollup=_rollup("out/x"), history_path=history,
        captured_at="2026-04-21T07:35:00Z",
    )
    assert history.exists()


def test_cli_writes_and_dedup(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rollup_path = tmp_path / "r.json"
    rollup_path.write_text(json.dumps(_rollup("out/x")), encoding="utf-8")
    history = tmp_path / "hist.jsonl"

    rc = arch.main([
        "--rollup", str(rollup_path),
        "--history", str(history),
        "--captured-at", "2026-04-21T07:35:00Z",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "appended snapshot" in out

    # Re-run is idempotent.
    rc = arch.main([
        "--rollup", str(rollup_path),
        "--history", str(history),
        "--captured-at", "2026-04-21T07:35:00Z",
    ])
    assert rc == 0
    assert "skipped" in capsys.readouterr().out


def test_cli_error_on_unreadable_rollup(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = arch.main([
        "--rollup", str(tmp_path / "missing.json"),
        "--history", str(tmp_path / "hist.jsonl"),
    ])
    assert rc == 1
    assert "unreadable rollup" in capsys.readouterr().err
