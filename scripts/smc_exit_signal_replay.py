"""Deterministic repository preflight for the R1 Exit Signal replay matrix.

The model mirrors the confirmed-bar state machine in ``SMC_Exit_Signal.pine``.
It exercises the gap, same-bar, precedence, fail-closed, and one-shot alert
edges before the independent TradingView fixture is run.

This is deliberately not TradingView evidence.  The generated artifact remains
``partial`` until the generated Pine fixture has compiled and every registered
case has been observed in TradingView.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from scripts.smc_atomic_write import atomic_write_text

ROOT: Final = Path(__file__).resolve().parents[1]
SOURCE: Final = ROOT / "SMC_Exit_Signal.pine"
DEFAULT_OUTPUT: Final = ROOT / "artifacts" / "governance" / "smc_exit_signal_replay_preflight.json"

FLAT: Final = 0
ARMED: Final = 1
IN_TRADE: Final = 2

ALERT_ENTER: Final = "EXIT_ENTER"
ALERT_STOP: Final = "EXIT_STOP"
ALERT_TP1: Final = "EXIT_TP1"
ALERT_TP2: Final = "EXIT_TP2"
ALERT_DEFENSIVE: Final = "EXIT_DEFENSIVE"
ALERT_ANY: Final = "EXIT_ANY"


@dataclass(frozen=True)
class Plan:
    schema: float | None = 7001.0
    armed: bool = True
    confirmed: bool = False
    ready: bool = False
    trigger: float | None = 100.0
    invalidation: float | None = 95.0
    stop: float | None = 94.0
    target1: float | None = 110.0
    target2: float | None = 120.0

    @property
    def any_state(self) -> bool:
        return self.schema_ok and (self.armed or self.confirmed or self.ready)

    @property
    def schema_ok(self) -> bool:
        return self.schema is not None and round(self.schema) == 7001

    @property
    def risk_ok(self) -> bool:
        levels = (
            self.trigger,
            self.invalidation,
            self.stop,
            self.target1,
            self.target2,
        )
        if not self.schema_ok or any(value is None for value in levels):
            return False
        trigger = float(self.trigger)
        invalidation = float(self.invalidation)
        stop = float(self.stop)
        target1 = float(self.target1)
        target2 = float(self.target2)
        return stop <= invalidation < trigger and target1 > trigger and target2 > target1


@dataclass(frozen=True)
class Bar:
    high: float
    close: float
    plan: Plan
    confirmed: bool = True


@dataclass
class Runtime:
    state: int = FLAT
    entry: float | None = None
    stop: float | None = None
    target1: float | None = None
    target2: float | None = None
    tp1_hit: bool = False
    collapse_count: int = 0

    def clear(self) -> None:
        self.state = FLAT
        self.entry = None
        self.stop = None
        self.target1 = None
        self.target2 = None
        self.tp1_hit = False
        self.collapse_count = 0


@dataclass(frozen=True)
class ReplayConfig:
    move_be_after_tp1: bool = True
    use_defensive_exit: bool = True
    defensive_grace_bars: int = 2
    confirm_bars_only: bool = True


DEFAULT_CONFIG: Final = ReplayConfig()


@dataclass(frozen=True)
class Case:
    case_id: str
    name: str
    bars: tuple[Bar, ...]
    expected_alerts: dict[str, int]
    expected_state: int


def step(
    runtime: Runtime,
    bar: Bar,
    config: ReplayConfig = DEFAULT_CONFIG,
) -> tuple[str, ...]:
    """Apply one Pine-equivalent bar and return its alert edges."""

    if config.confirm_bars_only and not bar.confirmed:
        return ()

    plan = bar.plan
    if runtime.state == FLAT and plan.any_state and plan.risk_ok:
        runtime.state = ARMED
        runtime.entry = plan.trigger
        runtime.stop = plan.stop
        runtime.target1 = plan.target1
        runtime.target2 = plan.target2

    if runtime.state == ARMED and plan.risk_ok:
        runtime.entry = plan.trigger
        runtime.stop = plan.stop
        runtime.target1 = plan.target1
        runtime.target2 = plan.target2

    alerts: list[str] = []
    if (
        runtime.state == ARMED
        and plan.any_state
        and plan.risk_ok
        and runtime.entry is not None
        and bar.high >= runtime.entry
    ):
        runtime.state = IN_TRADE
        runtime.tp1_hit = False
        runtime.collapse_count = 0
        alerts.append(ALERT_ENTER)

    if runtime.state == ARMED and (not plan.any_state or not plan.risk_ok):
        runtime.clear()

    stop_hit = False
    tp1_hit = False
    tp2_hit = False
    defensive = False

    if runtime.state == IN_TRADE:
        if runtime.stop is not None and bar.close < runtime.stop:
            stop_hit = True

        if not stop_hit and not runtime.tp1_hit and runtime.target1 is not None and bar.high >= runtime.target1:
            tp1_hit = True
            runtime.tp1_hit = True
            if config.move_be_after_tp1 and runtime.entry is not None:
                runtime.stop = max(float(runtime.stop), runtime.entry)

        if not stop_hit and runtime.target2 is not None and bar.high >= runtime.target2:
            tp2_hit = True

        if config.use_defensive_exit:
            if not plan.any_state:
                runtime.collapse_count += 1
            else:
                runtime.collapse_count = 0
            if runtime.collapse_count > config.defensive_grace_bars and not stop_hit and not tp2_hit:
                defensive = True

    if stop_hit:
        alerts.append(ALERT_STOP)
    if tp1_hit:
        alerts.append(ALERT_TP1)
    if tp2_hit:
        alerts.append(ALERT_TP2)
    if defensive:
        alerts.append(ALERT_DEFENSIVE)
    if stop_hit or tp2_hit or defensive:
        alerts.append(ALERT_ANY)
        runtime.clear()

    return tuple(alerts)


def _bar(
    high: float = 99.0,
    close: float = 98.0,
    plan: Plan | None = None,
    *,
    confirmed: bool = True,
) -> Bar:
    return Bar(
        high=high,
        close=close,
        plan=plan or Plan(),
        confirmed=confirmed,
    )


INACTIVE_PLAN: Final = Plan(armed=False, confirmed=False, ready=False)

CASES: Final[tuple[Case, ...]] = (
    Case("R1-01", "arm without entry", (_bar(),), {}, ARMED),
    Case(
        "R1-02",
        "gap across entry fires once",
        (_bar(), _bar(106.0, 104.0), _bar(106.0, 104.0)),
        {ALERT_ENTER: 1},
        IN_TRADE,
    ),
    Case(
        "R1-03",
        "entry and stop on the same bar",
        (_bar(101.0, 93.0),),
        {ALERT_ENTER: 1, ALERT_STOP: 1, ALERT_ANY: 1},
        FLAT,
    ),
    Case(
        "R1-04",
        "entry and Target 1 on the same bar",
        (_bar(112.0, 105.0),),
        {ALERT_ENTER: 1, ALERT_TP1: 1},
        IN_TRADE,
    ),
    Case(
        "R1-05",
        "entry and Target 2 on the same bar",
        (_bar(121.0, 105.0),),
        {ALERT_ENTER: 1, ALERT_TP1: 1, ALERT_TP2: 1, ALERT_ANY: 1},
        FLAT,
    ),
    Case(
        "R1-06",
        "stop wins over targets on the same bar",
        (_bar(101.0, 100.0), _bar(121.0, 93.0)),
        {ALERT_ENTER: 1, ALERT_STOP: 1, ALERT_ANY: 1},
        FLAT,
    ),
    Case(
        "R1-07",
        "Target 1 is a one-shot edge",
        (_bar(101.0, 100.0), _bar(111.0, 105.0), _bar(111.0, 105.0)),
        {ALERT_ENTER: 1, ALERT_TP1: 1},
        IN_TRADE,
    ),
    Case(
        "R1-08",
        "break-even stop follows Target 1",
        (
            _bar(101.0, 100.0),
            _bar(111.0, 105.0),
            _bar(105.0, 99.0),
        ),
        {ALERT_ENTER: 1, ALERT_TP1: 1, ALERT_STOP: 1, ALERT_ANY: 1},
        FLAT,
    ),
    Case(
        "R1-09",
        "defensive exit respects the exact grace window",
        (
            _bar(101.0, 100.0),
            _bar(105.0, 102.0, INACTIVE_PLAN),
            _bar(105.0, 102.0, INACTIVE_PLAN),
            _bar(105.0, 102.0, INACTIVE_PLAN),
        ),
        {ALERT_ENTER: 1, ALERT_DEFENSIVE: 1, ALERT_ANY: 1},
        FLAT,
    ),
    Case(
        "R1-10",
        "schema mismatch fails closed before entry",
        (_bar(121.0, 105.0, Plan(schema=7000.0)),),
        {},
        FLAT,
    ),
    Case(
        "R1-11",
        "incoherent risk plan fails closed before entry",
        (_bar(121.0, 105.0, Plan(stop=101.0)),),
        {},
        FLAT,
    ),
    Case(
        "R1-12",
        "unconfirmed update produces no edge",
        (_bar(121.0, 105.0, confirmed=False), _bar()),
        {},
        ARMED,
    ),
)


def run_case(case: Case) -> dict:
    runtime = Runtime()
    bar_alerts: list[tuple[str, ...]] = []
    counts: Counter[str] = Counter()
    for bar in case.bars:
        alerts = step(runtime, bar)
        bar_alerts.append(alerts)
        counts.update(alerts)

    actual = dict(sorted(counts.items()))
    if actual != case.expected_alerts or runtime.state != case.expected_state:
        raise AssertionError(
            f"{case.case_id} drifted: alerts={actual}, state={runtime.state}; "
            f"expected alerts={case.expected_alerts}, state={case.expected_state}"
        )

    return {
        "caseId": case.case_id,
        "name": case.name,
        "runCount": len(case.bars),
        "alertCounts": actual,
        "barAlerts": [list(alerts) for alerts in bar_alerts],
        "finalState": runtime.state,
        "repositoryPreflightStatus": "passed",
        "tradingViewStatus": "pending",
    }


def build_replay_preflight() -> dict:
    source_bytes = SOURCE.read_bytes()
    return {
        "schemaVersion": 1,
        "gate": "R1-REPLAY",
        "gateStatus": "partial",
        "repositoryPreflightStatus": "passed",
        "tradingViewStatus": "pending",
        "source": {
            "path": SOURCE.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
        },
        "caseCount": len(CASES),
        "cases": [run_case(case) for case in CASES],
        "alertExclusivity": {
            "actionableMode": "exit_signal",
            "forbiddenConcurrentMode": "hold_manager",
        },
        "limitations": [
            "The Python model is repository preflight, not execution evidence from the Pine runtime.",
            "TradingView compile, bar replay, alert-edge observation, and layout exclusivity require a separately authorized private run.",
        ],
        "openGates": [
            "Compile the generated private test-only fixture in TradingView.",
            "Run all registered cases and capture redacted per-case pulse evidence.",
            "Verify that Hold Manager actionable alerts are disabled in the Simple Management layout.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = json.dumps(build_replay_preflight(), indent=2, sort_keys=True) + "\n"
    atomic_write_text(payload, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
