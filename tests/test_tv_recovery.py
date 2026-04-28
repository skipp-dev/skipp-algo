"""Tests for idempotent TradingView recovery (ENG-WS5-03)."""
from __future__ import annotations

from scripts.tv_recovery import (
    KNOWN_FLAKES,
    RecoveryStep,
    execute_recovery,
    plan_recovery,
)


class TestPlanRecovery:
    def test_known_flakes_map_to_steps(self) -> None:
        assert plan_recovery("stale_modal_blocks_input") is RecoveryStep.CLOSE_MODAL
        assert plan_recovery("settings_row_dblclick_missed") is RecoveryStep.REINSERT_INPUT
        assert plan_recovery("pine_editor_not_focused") is RecoveryStep.ENSURE_PINE_EDITOR
        assert plan_recovery("publish_wizard_lost_focus") is RecoveryStep.REOPEN_PUBLISH_WIZARD

    def test_unknown_flake_returns_none(self) -> None:
        assert plan_recovery("totally-new-flake") is None

    def test_catalogue_is_complete(self) -> None:
        # All declared RecoveryStep values appear in the table — no
        # orphan recovery steps without a flake to trigger them.
        assert set(KNOWN_FLAKES.values()) == set(RecoveryStep)


class TestExecuteRecovery:
    def test_succeeds_on_first_attempt(self) -> None:
        calls: list[int] = []

        def runner(step: RecoveryStep, attempt: int) -> bool:
            calls.append(attempt)
            return True

        report = execute_recovery("stale_modal_blocks_input", runner)
        assert report.succeeded is True
        assert calls == [1]
        assert "attempt 1" in report.reason

    def test_idempotent_stop_after_success(self) -> None:
        # Once the runner returns True the loop must NOT keep retrying —
        # idempotency means at most one observable success.
        calls: list[int] = []

        def runner(step: RecoveryStep, attempt: int) -> bool:
            calls.append(attempt)
            return attempt == 2  # fail once, then succeed

        report = execute_recovery("settings_row_dblclick_missed", runner,
                                  max_attempts=5)
        assert report.succeeded is True
        assert calls == [1, 2]
        assert len(report.attempts) == 2

    def test_runner_exception_counts_as_failed_attempt(self) -> None:
        attempts = []

        def runner(step: RecoveryStep, attempt: int) -> bool:
            attempts.append(attempt)
            raise RuntimeError("UI gone")

        report = execute_recovery("pine_editor_not_focused", runner,
                                  max_attempts=2)
        assert report.succeeded is False
        assert attempts == [1, 2]
        assert "RuntimeError" in report.attempts[0].note

    def test_unknown_flake_reports_explicit_gap(self) -> None:
        report = execute_recovery("never-seen-before",
                                  lambda step, n: True)
        assert report.succeeded is False
        assert report.step is None
        assert "unknown TV flake" in report.reason

    def test_exhaustion_records_all_attempts(self) -> None:
        report = execute_recovery("publish_wizard_lost_focus",
                                  lambda step, n: False, max_attempts=3)
        assert report.succeeded is False
        assert len(report.attempts) == 3
        assert "did not succeed within 3 attempts" in report.reason

    def test_as_dict_is_diagnostic(self) -> None:
        report = execute_recovery("stale_modal_blocks_input",
                                  lambda step, n: True)
        d = report.as_dict()
        assert d["flake"] == "stale_modal_blocks_input"
        assert d["step"] == "close_modal"
        assert d["succeeded"] is True
        assert d["attempts"][0]["succeeded"] is True
