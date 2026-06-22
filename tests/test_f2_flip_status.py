"""Tests for ``scripts.f2_flip_status`` (closes #45)."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.f2_flip_status import (
    FLIP_FROM,
    FLIP_TO,
    flip_status,
    main,
)


def _read_journal(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_flip_resets_state_and_journals(tmp_path: Path) -> None:
    state = tmp_path / "sprt_state.json"
    journal = tmp_path / "journal.jsonl"
    history = tmp_path / "rollback_history.json"
    state.write_text('{"n": 12, "k": 7, "llr": 0.42}', encoding="utf-8")
    history.write_text("[0.01, -0.02, 0.03]", encoding="utf-8")

    entry = flip_status(
        from_status=FLIP_FROM,
        to_status=FLIP_TO,
        state_path=state,
        journal_path=journal,
        rollback_history_path=history,
    )

    assert not state.exists()
    assert history.read_text(encoding="utf-8").startswith("[0.01")  # untouched
    journaled = _read_journal(journal)
    assert len(journaled) == 1
    assert journaled[0]["action"] == "sprt_state_reset"
    assert journaled[0]["reason"] == "status_flip_to_live"
    assert journaled[0]["state_existed"] is True
    assert journaled[0]["rollback_history_reset"] is False
    assert journaled[0] == entry


def test_flip_when_state_absent_still_journals(tmp_path: Path) -> None:
    state = tmp_path / "missing_state.json"
    journal = tmp_path / "journal.jsonl"
    history = tmp_path / "rollback_history.json"

    entry = flip_status(
        from_status=FLIP_FROM,
        to_status=FLIP_TO,
        state_path=state,
        journal_path=journal,
        rollback_history_path=history,
    )

    assert entry["state_existed"] is False
    assert _read_journal(journal) == [entry]


def test_non_flip_transition_is_noop(tmp_path: Path) -> None:
    state = tmp_path / "sprt_state.json"
    journal = tmp_path / "journal.jsonl"
    history = tmp_path / "rollback_history.json"
    state.write_text('{"n": 3}', encoding="utf-8")
    history.write_text("[0.01]", encoding="utf-8")

    entry = flip_status(
        from_status="shadow",
        to_status="plumbing_only",
        state_path=state,
        journal_path=journal,
        rollback_history_path=history,
    )

    assert entry["action"] == "noop"
    assert entry["reason"] == "non_flip_transition"
    assert state.exists()
    assert history.read_text(encoding="utf-8") == "[0.01]"
    assert _read_journal(journal) == [entry]


def test_reset_rollback_history_flag_truncates_ring(tmp_path: Path) -> None:
    state = tmp_path / "sprt_state.json"
    journal = tmp_path / "journal.jsonl"
    history = tmp_path / "rollback_history.json"
    history.write_text("[0.01, -0.02]", encoding="utf-8")

    entry = flip_status(
        from_status=FLIP_FROM,
        to_status=FLIP_TO,
        state_path=state,
        journal_path=journal,
        rollback_history_path=history,
        reset_rollback_history=True,
    )

    assert entry["rollback_history_reset"] is True
    assert json.loads(history.read_text(encoding="utf-8")) == []


def test_helper_is_idempotent_under_repeated_invocations(tmp_path: Path) -> None:
    state = tmp_path / "sprt_state.json"
    journal = tmp_path / "journal.jsonl"
    history = tmp_path / "rollback_history.json"
    state.write_text('{"n": 1}', encoding="utf-8")

    entry_first = flip_status(
        from_status=FLIP_FROM,
        to_status=FLIP_TO,
        state_path=state,
        journal_path=journal,
        rollback_history_path=history,
    )
    entry_second = flip_status(
        from_status=FLIP_FROM,
        to_status=FLIP_TO,
        state_path=state,
        journal_path=journal,
        rollback_history_path=history,
    )

    assert entry_first["state_existed"] is True
    assert entry_second["state_existed"] is False
    journaled = _read_journal(journal)
    assert len(journaled) == 2
    assert journaled[0] == entry_first
    assert journaled[1] == entry_second


def test_journal_parent_dir_is_created(tmp_path: Path) -> None:
    journal = tmp_path / "nested" / "deep" / "journal.jsonl"
    flip_status(
        from_status="shadow",
        to_status="plumbing_only",
        state_path=tmp_path / "state.json",
        journal_path=journal,
        rollback_history_path=tmp_path / "history.json",
    )
    assert journal.exists()


def test_cli_main_exits_zero(tmp_path: Path) -> None:
    state = tmp_path / "sprt_state.json"
    state.write_text('{"n": 1}', encoding="utf-8")
    journal = tmp_path / "journal.jsonl"
    history = tmp_path / "rollback_history.json"

    rc = main([
        "--from", FLIP_FROM,
        "--to", FLIP_TO,
        "--state-file", str(state),
        "--journal", str(journal),
        "--rollback-history", str(history),
    ])

    assert rc == 0
    assert not state.exists()
    assert len(_read_journal(journal)) == 1


# --- deploy_boundary: SPRT corpus reset on boundary change (issue #2770) ---


def test_live_to_live_with_changed_deploy_boundary_resets(tmp_path: Path) -> None:
    """deploy_boundary change while status stays live must trigger sprt_state_reset."""
    state = tmp_path / "sprt_state.json"
    journal = tmp_path / "journal.jsonl"
    history = tmp_path / "rollback_history.json"
    state.write_text('{"n": 10}', encoding="utf-8")

    # First call establishes boundary v1 (no previous entry → noop, state untouched).
    first = flip_status(
        from_status="live",
        to_status="live",
        state_path=state,
        journal_path=journal,
        rollback_history_path=history,
        deploy_boundary="v1",
    )
    assert first["action"] == "noop"
    assert first["reason"] == "deploy_boundary_established"
    assert state.exists(), "first establish-call must not touch state file"

    # Second call with different boundary must reset.
    entry = flip_status(
        from_status="live",
        to_status="live",
        state_path=state,
        journal_path=journal,
        rollback_history_path=history,
        deploy_boundary="v2",
    )

    assert not state.exists(), "state file must be deleted on deploy_boundary_change"
    assert entry["action"] == "sprt_state_reset"
    assert entry["reason"] == "deploy_boundary_change"
    assert entry["boundary"] == "v2"
    assert entry["state_existed"] is True


def test_live_to_live_with_unchanged_deploy_boundary_is_noop(tmp_path: Path) -> None:
    """Same deploy_boundary on repeated live→live calls must be a noop."""
    state = tmp_path / "sprt_state.json"
    journal = tmp_path / "journal.jsonl"
    history = tmp_path / "rollback_history.json"
    state.write_text('{"n": 10}', encoding="utf-8")

    flip_status(
        from_status="live",
        to_status="live",
        state_path=state,
        journal_path=journal,
        rollback_history_path=history,
        deploy_boundary="v1",
    )
    entry = flip_status(
        from_status="live",
        to_status="live",
        state_path=state,
        journal_path=journal,
        rollback_history_path=history,
        deploy_boundary="v1",
    )

    assert entry["action"] == "noop"
    assert entry["reason"] == "deploy_boundary_unchanged"
    assert entry["boundary"] == "v1"
    assert state.exists(), "state file must not be touched when boundary is unchanged"


def test_deploy_boundary_on_flip_transition_is_ignored(tmp_path: Path) -> None:
    """deploy_boundary param must not interfere with a real plumbing_only→live flip."""
    state = tmp_path / "sprt_state.json"
    journal = tmp_path / "journal.jsonl"
    history = tmp_path / "rollback_history.json"
    state.write_text('{"n": 5}', encoding="utf-8")

    entry = flip_status(
        from_status=FLIP_FROM,
        to_status=FLIP_TO,
        state_path=state,
        journal_path=journal,
        rollback_history_path=history,
        deploy_boundary="sha-abc123",
    )

    assert not state.exists(), "flip must still delete state file"
    assert entry["action"] == "sprt_state_reset"
    assert entry["reason"] == "status_flip_to_live"
    assert "boundary" not in entry, "flip entries must not include boundary field"


def test_deploy_boundary_cli_arg(tmp_path: Path) -> None:
    """--deploy-boundary CLI argument must reach flip_status."""
    state = tmp_path / "sprt_state.json"
    journal = tmp_path / "journal.jsonl"
    history = tmp_path / "rollback_history.json"
    state.write_text('{"n": 1}', encoding="utf-8")

    # First call: establish boundary v1 (noop).
    main([
        "--from", "live", "--to", "live",
        "--deploy-boundary", "v1",
        "--state-file", str(state),
        "--journal", str(journal),
        "--rollback-history", str(history),
    ])
    state.write_text('{"n": 2}', encoding="utf-8")

    # Second call: change boundary → reset.
    rc = main([
        "--from", "live", "--to", "live",
        "--deploy-boundary", "v2",
        "--state-file", str(state),
        "--journal", str(journal),
        "--rollback-history", str(history),
    ])

    assert rc == 0
    assert not state.exists()
    entries = _read_journal(journal)
    assert entries[-1]["reason"] == "deploy_boundary_change"
