"""Tests for ``scripts/best_effort_failure_trend.py`` (W3, R4b audit)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.best_effort_failure_trend import (
    _failed_steps,
    _load_history,
    _parse_outcomes,
    digest,
    main,
    record,
)


def test_parse_outcomes_valid() -> None:
    parsed = _parse_outcomes(["a=success", "b=failure", "c=skipped"])
    assert parsed == {"a": "success", "b": "failure", "c": "skipped"}


def test_parse_outcomes_blank_value_becomes_unknown() -> None:
    assert _parse_outcomes(["a="]) == {"a": "unknown"}


def test_parse_outcomes_rejects_missing_equals() -> None:
    with pytest.raises(ValueError, match="name=value"):
        _parse_outcomes(["bogus"])


def test_failed_steps_filters_and_sorts() -> None:
    outcomes = {"z": "failure", "a": "failure", "b": "success"}
    assert _failed_steps(outcomes) == ["a", "z"]


def test_record_appends_and_writes_snapshot(tmp_path: Path) -> None:
    history = tmp_path / "hist.jsonl"
    snapshot = tmp_path / "snap.json"

    n_failed = record(
        history_path=history,
        snapshot_path=snapshot,
        outcomes={"gates": "success", "tv_post_release_raw": "failure"},
        run_id="123",
        run_url="https://example/123",
        ref="refs/heads/main",
    )
    assert n_failed == 1

    lines = history.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["failed"] == ["tv_post_release_raw"]
    assert rec["failed_count"] == 1
    assert rec["run_id"] == "123"

    snap = json.loads(snapshot.read_text(encoding="utf-8"))
    assert snap["failed"] == ["tv_post_release_raw"]


def test_record_is_append_only(tmp_path: Path) -> None:
    history = tmp_path / "hist.jsonl"
    snapshot = tmp_path / "snap.json"
    for i in range(3):
        record(
            history_path=history,
            snapshot_path=snapshot,
            outcomes={"gates": "success"},
            run_id=str(i),
            run_url="",
            ref="refs/heads/main",
        )
    assert len(history.read_text(encoding="utf-8").splitlines()) == 3


def test_load_history_tolerates_corrupt_lines(tmp_path: Path) -> None:
    history = tmp_path / "hist.jsonl"
    history.write_text(
        '{"run_id": "1", "outcomes": {}}\n'
        "this is not json\n"
        '{"run_id": "2", "outcomes": {}}\n'
        '{"truncated": ',  # truncated final line from a crashed run
        encoding="utf-8",
    )
    records = _load_history(history)
    assert [r["run_id"] for r in records] == ["1", "2"]


def test_digest_cold_start(tmp_path: Path) -> None:
    out = digest(history_path=tmp_path / "missing.jsonl", window=30)
    assert "cold start" in out


def test_digest_reports_failure_rate(tmp_path: Path) -> None:
    history = tmp_path / "hist.jsonl"
    snapshot = tmp_path / "snap.json"
    # 4 runs: tv_post_release_raw fails twice → 50%.
    outcome_seq = [
        {"tv_post_release_raw": "failure", "gates": "success"},
        {"tv_post_release_raw": "success", "gates": "success"},
        {"tv_post_release_raw": "failure", "gates": "success"},
        {"tv_post_release_raw": "success", "gates": "success"},
    ]
    for i, outcomes in enumerate(outcome_seq):
        record(
            history_path=history,
            snapshot_path=snapshot,
            outcomes=outcomes,
            run_id=str(i),
            run_url="",
            ref="refs/heads/main",
        )
    out = digest(history_path=history, window=30)
    assert "Runs analysed: **4**" in out
    assert "`tv_post_release_raw`" in out
    assert "50.0%" in out
    # Most recent run had no failures.
    assert "all clear" in out


def test_digest_no_failures_window(tmp_path: Path) -> None:
    history = tmp_path / "hist.jsonl"
    snapshot = tmp_path / "snap.json"
    record(
        history_path=history,
        snapshot_path=snapshot,
        outcomes={"gates": "success"},
        run_id="1",
        run_url="",
        ref="refs/heads/main",
    )
    out = digest(history_path=history, window=30)
    assert "No best-effort failures" in out


def test_main_record_then_digest(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    history = tmp_path / "hist.jsonl"
    snapshot = tmp_path / "snap.json"
    rc = main(
        [
            "record",
            "--history",
            str(history),
            "--snapshot",
            str(snapshot),
            "--run-id",
            "999",
            "--ref",
            "refs/heads/main",
            "--outcome",
            "tv_post_release_raw=failure",
            "--outcome",
            "gates=success",
        ]
    )
    assert rc == 0

    rc = main(["digest", "--history", str(history)])
    assert rc == 0
    captured = capsys.readouterr().out
    assert "Best-effort failure trend" in captured
    assert "`tv_post_release_raw`" in captured
