"""Live risk limits / kill-switch (Sprint C8 / T2).

Pure-stdlib pre-trade gate for the live incubation track. Every
order request must pass through :func:`check_risk_limits` before it
is forwarded to the broker adapter (Sprint C8 / T3). When the gate
trips the bot is required to:

1. Reject the candidate order.
2. Cancel all working orders.
3. Flatten open positions if ``RiskLimits.flatten_on_breach`` is True.
4. Persist the breach event for the next-day audit.

The module is intentionally side-effect-free — it returns a typed
decision; the orchestrator owns the cancel/flatten side. This keeps
unit tests deterministic and lets dry-runs evaluate "would I have
been killed" against historical streams.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field, fields
from datetime import date
from enum import StrEnum
from pathlib import Path

__all__ = [
    "AccountState",
    "BreachReason",
    "KillSwitchDecision",
    "RiskLimits",
    "check_risk_limits",
]


class BreachReason(StrEnum):
    DAILY_LOSS = "daily_loss_exceeded"
    MAX_OPEN_POSITIONS = "max_open_positions_exceeded"
    MAX_CONSECUTIVE_LOSSES = "max_consecutive_losses_exceeded"
    DRAWDOWN = "max_drawdown_exceeded"
    EXPOSURE = "max_gross_exposure_exceeded"
    MANUAL_HALT = "manual_halt"

    def __str__(self) -> str:  # for clean log output
        return self.value


@dataclass(frozen=True)
class RiskLimits:
    """Kill-switch thresholds for the live incubation track.

    The field defaults below are the canonical Phase-A values and are
    mirrored verbatim by ``configs/live_risk_limits.json``; a regression
    test (``tests/test_live_risk_limits_json_mirror.py``) asserts the two
    never drift apart. Construct ``RiskLimits()`` for the in-code defaults,
    or :meth:`from_json` to load a version-controlled / operator-supplied
    override from that JSON file.
    """

    max_daily_loss_pct: float = 2.0
    max_open_positions: int = 5
    max_consecutive_losses: int = 4
    max_drawdown_pct: float = 8.0
    max_gross_exposure_pct: float = 200.0
    flatten_on_breach: bool = True
    manual_halt: bool = False

    # Documentation-only keys tolerated alongside the typed limits in the
    # JSON config, so the file can carry provenance metadata without
    # tripping the unknown-key typo guard in :meth:`from_json`.
    _JSON_METADATA_KEYS = frozenset({"_comment", "frozen_at", "frozen_for"})

    @classmethod
    def from_json(cls, path: "str | Path") -> "RiskLimits":
        """Load and validate kill-switch limits from a JSON object file.

        Unknown, non-metadata keys are rejected: a typo in a
        safety-critical limit must fail loud rather than silently fall
        back to a default. Recognised metadata keys and any
        underscore-prefixed key are ignored; any omitted limit falls back
        to the dataclass default.
        """
        blob = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(blob, dict):
            raise ValueError(
                f"risk-limits JSON must be a JSON object, got "
                f"{type(blob).__name__}"
            )
        allowed = {f.name for f in fields(cls)}
        unknown = {
            key
            for key in blob
            if key not in allowed
            and key not in cls._JSON_METADATA_KEYS
            and not key.startswith("_")
        }
        if unknown:
            raise ValueError(
                f"risk-limits JSON {path} has unknown keys: "
                f"{sorted(unknown)!r}"
            )
        return cls(**{key: blob[key] for key in allowed if key in blob})


@dataclass(frozen=True)
class AccountState:
    """Snapshot of broker-derived account data passed in per check."""

    as_of: date
    equity: float
    starting_equity_today: float
    high_water_mark: float
    open_positions: int
    gross_exposure_pct: float
    last_n_pnls: Sequence[float] = field(default_factory=tuple)


@dataclass(frozen=True)
class KillSwitchDecision:
    engaged: bool
    reasons: tuple[BreachReason, ...] = ()
    detail: tuple[str, ...] = ()

    @property
    def primary_reason(self) -> BreachReason | None:
        return self.reasons[0] if self.reasons else None


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_daily_loss(state: AccountState, limits: RiskLimits) -> str | None:
    if state.starting_equity_today <= 0:
        return None
    pnl_pct = (
        (state.equity - state.starting_equity_today)
        / state.starting_equity_today
        * 100.0
    )
    if pnl_pct <= -abs(limits.max_daily_loss_pct):
        return f"daily_pnl={pnl_pct:.3f}% limit={-abs(limits.max_daily_loss_pct):.3f}%"
    return None


def _check_drawdown(state: AccountState, limits: RiskLimits) -> str | None:
    if state.high_water_mark <= 0:
        return None
    dd_pct = (state.equity - state.high_water_mark) / state.high_water_mark * 100.0
    if dd_pct <= -abs(limits.max_drawdown_pct):
        return f"drawdown={dd_pct:.3f}% limit={-abs(limits.max_drawdown_pct):.3f}%"
    return None


def _check_open_positions(state: AccountState, limits: RiskLimits) -> str | None:
    if state.open_positions > limits.max_open_positions:
        return f"open={state.open_positions} limit={limits.max_open_positions}"
    return None


def _check_exposure(state: AccountState, limits: RiskLimits) -> str | None:
    if state.gross_exposure_pct > limits.max_gross_exposure_pct:
        return (
            f"gross_exposure={state.gross_exposure_pct:.2f}% "
            f"limit={limits.max_gross_exposure_pct:.2f}%"
        )
    return None


def _check_consecutive_losses(
    state: AccountState, limits: RiskLimits
) -> str | None:
    streak = 0
    for p in reversed(list(state.last_n_pnls)):
        if p < 0:
            streak += 1
        else:
            break
    if streak >= limits.max_consecutive_losses:
        return f"loss_streak={streak} limit={limits.max_consecutive_losses}"
    return None


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


def check_risk_limits(
    state: AccountState, limits: RiskLimits
) -> KillSwitchDecision:
    """Run all gates. Returns a frozen decision; never raises."""

    reasons: list[BreachReason] = []
    details: list[str] = []

    if limits.manual_halt:
        reasons.append(BreachReason.MANUAL_HALT)
        details.append("manual_halt=True")

    pairs = (
        (BreachReason.DAILY_LOSS, _check_daily_loss(state, limits)),
        (BreachReason.DRAWDOWN, _check_drawdown(state, limits)),
        (BreachReason.MAX_OPEN_POSITIONS, _check_open_positions(state, limits)),
        (BreachReason.EXPOSURE, _check_exposure(state, limits)),
        (
            BreachReason.MAX_CONSECUTIVE_LOSSES,
            _check_consecutive_losses(state, limits),
        ),
    )
    for reason, detail in pairs:
        if detail is not None:
            reasons.append(reason)
            details.append(detail)

    return KillSwitchDecision(
        engaged=bool(reasons),
        reasons=tuple(reasons),
        detail=tuple(details),
    )
