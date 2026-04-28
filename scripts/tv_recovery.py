"""Idempotent TradingView retry / reinsert recovery (ENG-WS5-03).

Known TradingView UI flakes (transient modal close failure, settings
row dblclick miss, ensure-pine-editor seam blip, publish wizard
re-open) need named, deterministic recovery paths. This module
offers a small idempotency layer so the validation script can replay
recovery without producing nondeterministic outcomes.

DoD:
- bekannte TV-Flakes fuehren nicht zu nondeterministischem Verhalten,
- Recovery-Pfade sind idempotent,
- Validation bleibt lesbar und diagnosetauglich.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class RecoveryStep(str, Enum):
    CLOSE_MODAL = "close_modal"
    REINSERT_INPUT = "reinsert_input"
    ENSURE_PINE_EDITOR = "ensure_pine_editor"
    REOPEN_PUBLISH_WIZARD = "reopen_publish_wizard"


# Catalogued TV flakes mapped to their canonical recovery step. Adding
# a new flake here is the single source of truth — validation scripts
# never hand-roll recovery branches outside this table.
KNOWN_FLAKES: dict[str, RecoveryStep] = {
    "stale_modal_blocks_input": RecoveryStep.CLOSE_MODAL,
    "settings_row_dblclick_missed": RecoveryStep.REINSERT_INPUT,
    "pine_editor_not_focused": RecoveryStep.ENSURE_PINE_EDITOR,
    "publish_wizard_lost_focus": RecoveryStep.REOPEN_PUBLISH_WIZARD,
}


DEFAULT_MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class RecoveryAttempt:
    step: RecoveryStep
    attempt: int
    succeeded: bool
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "step": self.step.value,
            "attempt": self.attempt,
            "succeeded": self.succeeded,
            "note": self.note,
        }


@dataclass(frozen=True)
class RecoveryReport:
    flake: str
    step: RecoveryStep | None
    attempts: tuple[RecoveryAttempt, ...] = field(default_factory=tuple)
    succeeded: bool = False
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "flake": self.flake,
            "step": self.step.value if self.step else None,
            "attempts": [a.as_dict() for a in self.attempts],
            "succeeded": self.succeeded,
            "reason": self.reason,
        }


def plan_recovery(flake: str) -> RecoveryStep | None:
    """Map a flake name to its canonical recovery step (or None)."""
    return KNOWN_FLAKES.get(flake)


def execute_recovery(
    flake: str,
    runner: Callable[[RecoveryStep, int], bool],
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> RecoveryReport:
    """Run the canonical recovery for ``flake`` idempotently.

    The runner callable is invoked at most ``max_attempts`` times;
    each call returns True on success. Retries past the first
    successful attempt are NOT performed (idempotent stop). If the
    flake is unknown the report records the gap explicitly so it
    surfaces in validation logs without ambiguity.
    """
    step = plan_recovery(flake)
    if step is None:
        return RecoveryReport(
            flake=flake, step=None, attempts=(), succeeded=False,
            reason=f"unknown TV flake {flake!r}; no canonical recovery step",
        )

    attempts: list[RecoveryAttempt] = []
    for attempt in range(1, max_attempts + 1):
        try:
            ok = bool(runner(step, attempt))
        except Exception as exc:
            attempts.append(RecoveryAttempt(
                step=step, attempt=attempt, succeeded=False,
                note=f"runner raised {type(exc).__name__}: {exc}",
            ))
            continue
        attempts.append(RecoveryAttempt(
            step=step, attempt=attempt, succeeded=ok,
        ))
        if ok:
            return RecoveryReport(
                flake=flake, step=step, attempts=tuple(attempts),
                succeeded=True,
                reason=f"recovered via {step.value} on attempt {attempt}",
            )

    return RecoveryReport(
        flake=flake, step=step, attempts=tuple(attempts),
        succeeded=False,
        reason=(
            f"recovery {step.value} for {flake!r} did not succeed within "
            f"{max_attempts} attempts"
        ),
    )
