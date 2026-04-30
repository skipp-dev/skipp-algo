"""Tests for ``scripts/plan_2_8_history_rotate.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_history_rotate.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_history_rotate", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_history_rotate"] = mod
    spec.loader.exec_module(mod)
    return mod


rot = _load()


def _write(history: Path, snaps: list[dict], extra_lines: list[str] | None = None) -> None:
    lines = [json.dumps(s) for s in snaps]
    if extra_lines:
        lines.extend(extra_lines)
    history.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _snap(captured_at: str, scoring_root: str = "out/x") -> dict:
    return {"captured_at": captured_at, "scoring_root": scoring_root,
            "files_scanned": 1, "per_tf": {}}


def test_rotate_noop_when_nothing_to_drop(tmp_path: Path) -> None:
    history = tmp_path / "hist.jsonl"
    _write(history, [_snap("2026-04-21T07:00:00Z")])
    summary = rot.rotate(history_path=history, max_rows=10)
    assert summary["before"] == 1
    assert summary["after"] == 1
    assert summary["backup"] is None  # no rewrite
    # File untouched.
    assert history.read_text(encoding="utf-8").count("\n") == 1


def test_rotate_trims_by_max_rows_keeping_newest(tmp_path: Path) -> None:
    history = tmp_path / "hist.jsonl"
    snaps = [_snap(f"2026-04-{d:02d}T07:00:00Z") for d in range(1, 11)]
    _write(history, snaps)
    summary = rot.rotate(history_path=history, max_rows=3)
    assert summary["before"] == 10
    assert summary["after"] == 3
    assert summary["dropped_cap"] == 7
    assert summary["backup"] is not None
    # The three remaining rows are the three newest.
    surviving = [json.loads(ln) for ln in history.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert [s["captured_at"] for s in surviving] == [
        "2026-04-08T07:00:00Z", "2026-04-09T07:00:00Z", "2026-04-10T07:00:00Z",
    ]


def test_rotate_drops_by_max_age(tmp_path: Path) -> None:
    history = tmp_path / "hist.jsonl"
    snaps = [_snap(f"2026-04-{d:02d}T07:00:00Z") for d in range(1, 22)]
    _write(history, snaps)
    summary = rot.rotate(history_path=history, max_age_days=7)
    # Anchor is 2026-04-21; cutoff is 2026-04-14. Snapshots 2026-04-01..13 drop.
    assert summary["before"] == 21
    assert summary["dropped_age"] == 13
    assert summary["after"] == 8
    surviving = [json.loads(ln) for ln in history.read_text(encoding="utf-8").splitlines() if ln.strip()]
    oldest_kept = min(s["captured_at"] for s in surviving)
    assert oldest_kept == "2026-04-14T07:00:00Z"


def test_rotate_corrupt_lines_preserved_by_default(tmp_path: Path) -> None:
    history = tmp_path / "hist.jsonl"
    _write(
        history,
        [_snap("2026-04-21T07:00:00Z")],
        extra_lines=["not json either", "{bad"],
    )
    summary = rot.rotate(history_path=history, max_rows=10)
    # max_rows 10 but we have 1 valid snapshot + 2 corrupt lines; nothing trimmed.
    # Rotate is a no-op because nothing changed.
    assert summary["before"] == 3
    assert summary["after"] == 3
    assert summary["corrupt_kept"] == 2
    assert summary["corrupt_dropped"] == 0
    text = history.read_text(encoding="utf-8")
    assert "not json either" in text
    assert "{bad" in text


def test_rotate_drop_corrupt_removes_bad_lines(tmp_path: Path) -> None:
    history = tmp_path / "hist.jsonl"
    _write(
        history,
        [_snap("2026-04-21T07:00:00Z")],
        extra_lines=["garbage"],
    )
    summary = rot.rotate(history_path=history, drop_corrupt=True)
    assert summary["corrupt_dropped"] == 1
    assert summary["after"] == 1
    text = history.read_text(encoding="utf-8")
    assert "garbage" not in text


def test_rotate_writes_backup_and_restores_on_failure(tmp_path: Path) -> None:
    history = tmp_path / "hist.jsonl"
    snaps = [_snap(f"2026-04-{d:02d}T07:00:00Z") for d in range(1, 6)]
    _write(history, snaps)
    summary = rot.rotate(history_path=history, max_rows=2)
    assert summary["backup"] is not None
    backup = Path(summary["backup"])
    assert backup.exists()
    assert backup.read_text(encoding="utf-8").count("\n") == 5


def test_rotate_requires_positive_thresholds(tmp_path: Path) -> None:
    history = tmp_path / "hist.jsonl"
    _write(history, [_snap("2026-04-21T07:00:00Z")])
    with pytest.raises(ValueError, match="max_rows"):
        rot.rotate(history_path=history, max_rows=-1)
    with pytest.raises(ValueError, match="max_age_days"):
        rot.rotate(history_path=history, max_age_days=-1)


def test_rotate_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="history not found"):
        rot.rotate(history_path=tmp_path / "nope.jsonl", max_rows=1)


def test_cli_requires_at_least_one_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    history = tmp_path / "hist.jsonl"
    _write(history, [_snap("2026-04-21T07:00:00Z")])
    rc = rot.main(["--history", str(history)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "--max-age-days" in err and "--max-rows" in err


def test_cli_writes_summary_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    history = tmp_path / "hist.jsonl"
    snaps = [_snap(f"2026-04-{d:02d}T07:00:00Z") for d in range(1, 6)]
    _write(history, snaps)
    rc = rot.main([
        "--history", str(history),
        "--max-rows", "2",
    ])
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["before"] == 5
    assert summary["after"] == 2


def test_cli_error_on_missing_history(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = rot.main([
        "--history", str(tmp_path / "nope.jsonl"),
        "--max-rows", "10",
    ])
    assert rc == 1
    assert "history not found" in capsys.readouterr().err
