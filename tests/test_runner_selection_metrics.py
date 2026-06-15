"""Tests for the runner-selection aggregate metrics (scripts/runner_selection_metrics.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import runner_selection_metrics as rsm


def test_build_event_normalises_blanks_to_none() -> None:
    event = rsm.build_event(
        reason="  matched_idle_self_hosted_runner ",
        runner_environment="self-hosted",
        matched_runner_name="   ",
        workflow="smc-library-refresh",
        event_name="schedule",
        run_id="",
        timestamp="2026-06-15T10:00:00Z",
    )
    assert event["reason"] == "matched_idle_self_hosted_runner"
    assert event["runner_environment"] == "self-hosted"
    assert event["matched_runner_name"] is None  # blank → None
    assert event["run_id"] is None  # blank → None
    assert event["ts"] == "2026-06-15T10:00:00Z"


def test_build_event_defaults_timestamp_when_absent() -> None:
    event = rsm.build_event(reason="x", runner_environment="github-hosted")
    assert event["ts"].endswith("Z")
    assert len(event["ts"]) == len("2026-06-15T10:00:00Z")


def test_append_and_load_roundtrip(tmp_path: Path) -> None:
    metrics = tmp_path / "nested" / "runner_selection.jsonl"
    e1 = rsm.build_event(reason="matched_idle_self_hosted_runner", runner_environment="self-hosted", timestamp="2026-06-15T10:00:00Z")
    e2 = rsm.build_event(reason="no_idle_matching_self_hosted_runner", runner_environment="github-hosted", timestamp="2026-06-15T11:00:00Z")
    rsm.append_event(metrics, e1)
    rsm.append_event(metrics, e2)

    loaded = rsm.load_events(metrics)
    assert loaded == [e1, e2]
    # File is valid JSON-Lines.
    lines = metrics.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert all(json.loads(line) for line in lines)


def test_load_events_skips_blank_and_corrupt_lines(tmp_path: Path) -> None:
    metrics = tmp_path / "m.jsonl"
    metrics.write_text(
        '{"reason":"a","runner_environment":"self-hosted","ts":"2026-06-15T10:00:00Z"}\n'
        "\n"
        "{ not valid json\n"
        '{"reason":"b","runner_environment":"github-hosted","ts":"2026-06-15T12:00:00Z"}\n',
        encoding="utf-8",
    )
    events = rsm.load_events(metrics)
    assert [e["reason"] for e in events] == ["a", "b"]


def test_load_events_missing_file_returns_empty(tmp_path: Path) -> None:
    assert rsm.load_events(tmp_path / "does-not-exist.jsonl") == []


def test_summarize_counts_and_rates() -> None:
    events = [
        rsm.build_event(reason="matched_idle_self_hosted_runner", runner_environment="self-hosted", timestamp="2026-06-15T10:00:00Z"),
        rsm.build_event(reason="matched_idle_self_hosted_runner", runner_environment="self-hosted", timestamp="2026-06-15T11:00:00Z"),
        rsm.build_event(reason="no_idle_matching_self_hosted_runner", runner_environment="github-hosted", timestamp="2026-06-15T12:00:00Z"),
        rsm.build_event(reason="no_idle_matching_self_hosted_runner:forced_required_self_hosted", runner_environment="self-hosted", timestamp="2026-06-15T13:00:00Z"),
    ]
    summary = rsm.summarize(events)
    assert summary["total"] == 4
    assert summary["matched_self_hosted"] == 2
    assert summary["hosted_fallback"] == 1
    assert summary["self_hosted_match_rate"] == 0.5
    assert summary["hosted_fallback_rate"] == 0.25
    assert summary["by_runner_environment"] == {"github-hosted": 1, "self-hosted": 3}
    assert summary["first_event_ts"] == "2026-06-15T10:00:00Z"
    assert summary["last_event_ts"] == "2026-06-15T13:00:00Z"


def test_summarize_empty_is_safe() -> None:
    summary = rsm.summarize([])
    assert summary["total"] == 0
    assert summary["self_hosted_match_rate"] == 0.0
    assert summary["hosted_fallback_rate"] == 0.0
    assert summary["first_event_ts"] is None


def test_render_summary_md_contains_key_fields() -> None:
    events = [
        rsm.build_event(reason="matched_idle_self_hosted_runner", runner_environment="self-hosted", timestamp="2026-06-15T10:00:00Z"),
        rsm.build_event(reason="no_idle_matching_self_hosted_runner", runner_environment="github-hosted", timestamp="2026-06-15T12:00:00Z"),
    ]
    md = rsm.render_summary_md(rsm.summarize(events))
    assert "# Runner Selection Metrics" in md
    assert "Self-hosted matched:" in md
    assert "GitHub-hosted fallback:" in md
    assert "`matched_idle_self_hosted_runner`" in md
    assert "`github-hosted`" in md


def test_cli_append_then_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    metrics = tmp_path / "m.jsonl"
    rc = rsm.main(
        [
            "append",
            "--metrics-file", str(metrics),
            "--reason", "matched_idle_self_hosted_runner",
            "--runner-environment", "self-hosted",
            "--matched-runner-name", "smc-win-01",
            "--workflow", "smc-library-refresh",
            "--run-id", "12345",
            "--timestamp", "2026-06-15T10:00:00Z",
        ]
    )
    assert rc == 0
    capsys.readouterr()  # discard the append command's stdout
    rc = rsm.main(["summary", "--metrics-file", str(metrics), "--format", "json"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["total"] == 1
    assert payload["matched_self_hosted"] == 1


def test_cli_append_writes_summary_md(tmp_path: Path) -> None:
    metrics = tmp_path / "m.jsonl"
    summary_md = tmp_path / "summary.md"
    rc = rsm.main(
        [
            "append",
            "--metrics-file", str(metrics),
            "--summary-md", str(summary_md),
            "--reason", "no_idle_matching_self_hosted_runner",
            "--runner-environment", "github-hosted",
        ]
    )
    assert rc == 0
    assert summary_md.exists()
    assert "# Runner Selection Metrics" in summary_md.read_text(encoding="utf-8")
