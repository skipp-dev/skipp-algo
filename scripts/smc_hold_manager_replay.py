"""Deterministic repository preflight for the Hold Manager R2.4 replay matrix.

This module mirrors the confirmed-bar transition contract in
``SMC_Hold_Manager.pine`` closely enough to pre-register and exercise every
R2.4 scenario before an operator runs the independent TradingView replay.

It is deliberately not TradingView evidence.  The generated artifact reports
``gateStatus = "partial"`` and keeps every case's ``tradingViewStatus`` at
``"pending"``.  R2-REPLAY may become complete only after the Pine runtime has
been compiled and the same cases have been observed in TradingView.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

from scripts.smc_atomic_write import atomic_write_text

ROOT: Final = Path(__file__).resolve().parents[1]
HOLD_MANAGER_SOURCE: Final = ROOT / "SMC_Hold_Manager.pine"
DEFAULT_OUTPUT: Final = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_replay_preflight.json"
)

PHASE_NONE: Final = 0
PHASE_ARMED: Final = 1
PHASE_IN_TRADE: Final = 2
PHASE_CLOSED: Final = 3

EXIT_NONE: Final = 0
EXIT_STOP: Final = 1
EXIT_TARGET_2: Final = 2
EXIT_TIME_STOP: Final = 3

PHASE_NAMES: Final = {
    PHASE_NONE: "NONE",
    PHASE_ARMED: "ARMED",
    PHASE_IN_TRADE: "IN_TRADE",
    PHASE_CLOSED: "CLOSED",
}
EXIT_NAMES: Final = {
    EXIT_NONE: "NONE",
    EXIT_STOP: "STOP",
    EXIT_TARGET_2: "TARGET_2",
    EXIT_TIME_STOP: "TIME_STOP",
}

MINUTE_MS: Final = 60_000
DAY_MS: Final = 24 * 60 * MINUTE_MS


def _required[T](value: T | None, label: str) -> T:
    """Return a required model value or fail closed at runtime."""

    if value is None:
        raise RuntimeError(f"required replay value is missing: {label}")
    return value


@dataclass(frozen=True)
class Plan:
    """One Engine BUS v2 plan sample on a confirmed bar."""

    schema: int = 7001
    zone_active: bool = True
    armed: bool = True
    confirmed: bool = False
    ready: bool = False
    trigger: float | None = 100.0
    invalidation: float | None = 95.0
    quality: float | None = 0.8
    source_kind: int | None = 1
    state_code: int | None = 1
    stop: float | None = 94.0
    target1: float | None = 110.0
    target2: float | None = 120.0

    @property
    def valid(self) -> bool:
        lifecycle_active = self.zone_active and (
            self.armed or self.confirmed or self.ready
        )
        metadata_ok = (
            self.quality is not None
            and self.source_kind is not None
            and self.state_code is not None
            and self.state_code >= 1
        )
        trigger = self.trigger
        invalidation = self.invalidation
        stop = self.stop
        target1 = self.target1
        target2 = self.target2
        levels = (trigger, invalidation, stop, target1, target2)
        levels_present = all(value is not None for value in levels)
        if not levels_present:
            return False
        trigger = _required(trigger, "trigger")
        invalidation = _required(invalidation, "invalidation")
        stop = _required(stop, "stop")
        target1 = _required(target1, "target1")
        target2 = _required(target2, "target2")
        levels_ok = (
            stop <= invalidation < trigger
            and target1 > trigger
            and target2 > target1
        )
        return (
            self.schema == 7001
            and lifecycle_active
            and metadata_ok
            and levels_ok
        )

    @property
    def identity(self) -> tuple[float | int | None, ...]:
        return (
            self.trigger,
            self.invalidation,
            self.stop,
            self.target1,
            self.target2,
            self.source_kind,
            self.schema,
        )


@dataclass(frozen=True)
class Bar:
    """Confirmed OHLC/BUS sample consumed by the repository model."""

    epoch_ms: int
    open: float
    high: float
    low: float
    close: float
    plan: Plan | None
    atr: float = 2.0
    event_warning: bool = False
    stale_context: bool = False
    confirmed: bool = True


@dataclass(frozen=True)
class ReplayConfig:
    """Hold-management inputs that affect deterministic transitions."""

    use_chandelier: bool = True
    atr_multiplier: float = 2.5
    breakeven: bool = True
    use_time_stop: bool = True
    time_stop_minutes: int = 90
    simple_mode: bool = False
    recovery_at_ms: int = 0


@dataclass
class Runtime:
    """State fields corresponding to the Pine ``HoldRuntime`` UDT."""

    phase: int = PHASE_NONE
    entry_price: float | None = None
    initial_stop: float | None = None
    active_stop: float | None = None
    target1: float | None = None
    target2: float | None = None
    entry_bar: int | None = None
    entry_time_ms: int | None = None
    protected_high: float | None = None
    target1_hit: bool = False
    terminal_exit_code: int = EXIT_NONE
    terminal_exit_bar: int | None = None
    terminal_exit_time_ms: int | None = None
    bus_generation: int = 0
    bus_generation_epoch_ms: int | None = None
    plan_symbol: str = ""
    plan_direction: int = 0
    plan_schema: int = 0
    plan_source_kind: int = 0
    plan_trigger: float | None = None
    plan_invalidation: float | None = None
    plan_generation: int = 0
    plan_epoch_ms: int | None = None
    last_blocked_generation: int = 0
    last_blocked_time_ms: int | None = None

    def clear_trade(self) -> None:
        """Match ``HoldRuntime.clear_trade`` without resetting BUS generation."""

        self.phase = PHASE_NONE
        self.entry_price = None
        self.initial_stop = None
        self.active_stop = None
        self.target1 = None
        self.target2 = None
        self.entry_bar = None
        self.entry_time_ms = None
        self.protected_high = None
        self.target1_hit = False
        self.terminal_exit_code = EXIT_NONE
        self.terminal_exit_bar = None
        self.terminal_exit_time_ms = None
        self.plan_symbol = ""
        self.plan_direction = 0
        self.plan_schema = 0
        self.plan_source_kind = 0
        self.plan_trigger = None
        self.plan_invalidation = None
        self.plan_generation = 0
        self.plan_epoch_ms = None


@dataclass(frozen=True)
class Observation:
    """One bar's hidden diagnostics and alert pulses."""

    bar_index: int
    epoch_ms: int
    phase: str
    plan_generation: int
    entry_epoch_ms: int | None
    protected_high: float | None
    target1_hit: bool
    active_stop: float | None
    terminal_exit: str
    terminal_exit_epoch_ms: int | None
    new_plan_blocked: bool
    event_warning: bool
    stale_context: bool
    alerts: tuple[str, ...]


class HoldReplay:
    """Confirmed-history interpreter for the Hold Manager transition contract."""

    def __init__(self, config: ReplayConfig | None = None) -> None:
        self.config = config or ReplayConfig()
        self.runtime = Runtime()
        self._previous_plan: Plan | None = None
        self._previous_plan_valid = False
        self._previous_epoch_ms = 0
        self.observations: list[Observation] = []

    def _stage_plan(self, plan: Plan, epoch_ms: int) -> None:
        trigger = _required(plan.trigger, "plan.trigger")
        stop = _required(plan.stop, "plan.stop")
        target1 = _required(plan.target1, "plan.target1")
        target2 = _required(plan.target2, "plan.target2")
        invalidation = _required(plan.invalidation, "plan.invalidation")
        source_kind = _required(plan.source_kind, "plan.source_kind")
        runtime = self.runtime
        runtime.phase = PHASE_ARMED
        runtime.entry_price = trigger
        runtime.initial_stop = stop
        runtime.active_stop = stop
        runtime.target1 = target1
        runtime.target2 = target2
        runtime.entry_bar = None
        runtime.entry_time_ms = None
        runtime.protected_high = None
        runtime.target1_hit = False
        runtime.terminal_exit_code = EXIT_NONE
        runtime.terminal_exit_bar = None
        runtime.terminal_exit_time_ms = None
        runtime.plan_symbol = "NASDAQ:TEST"
        runtime.plan_direction = 1
        runtime.plan_schema = plan.schema
        runtime.plan_source_kind = source_kind
        runtime.plan_trigger = trigger
        runtime.plan_invalidation = invalidation
        runtime.plan_generation = runtime.bus_generation
        runtime.plan_epoch_ms = epoch_ms
        runtime.last_blocked_generation = 0
        runtime.last_blocked_time_ms = None

    def step(self, bar: Bar, bar_index: int) -> Observation:
        """Apply one bar in the same transition order as the Pine source."""

        runtime = self.runtime
        plan_valid = bar.plan is not None and bar.plan.valid
        recovery_now = (
            bar.confirmed
            and self.config.recovery_at_ms > 0
            and bar.epoch_ms >= self.config.recovery_at_ms
            and self._previous_epoch_ms < self.config.recovery_at_ms
        )
        if recovery_now:
            runtime.clear_trade()
            runtime.last_blocked_generation = 0
            runtime.last_blocked_time_ms = None

        identity_changed = (
            plan_valid
            and self._previous_plan_valid
            and bar.plan is not None
            and self._previous_plan is not None
            and bar.plan.identity != self._previous_plan.identity
        )
        plan_event = plan_valid and (
            not self._previous_plan_valid or identity_changed
        )
        if bar.confirmed and plan_event:
            runtime.bus_generation += 1
            runtime.bus_generation_epoch_ms = bar.epoch_ms

        active_plan_matches = (
            plan_valid
            and bar.plan is not None
            and runtime.phase >= PHASE_ARMED
            and runtime.plan_symbol == "NASDAQ:TEST"
            and runtime.plan_direction == 1
            and runtime.plan_schema == bar.plan.schema
            and runtime.plan_source_kind == bar.plan.source_kind
            and runtime.plan_trigger == bar.plan.trigger
            and runtime.plan_invalidation == bar.plan.invalidation
            and runtime.plan_generation == runtime.bus_generation
        )
        new_plan_blocked = (
            bar.confirmed
            and runtime.phase == PHASE_IN_TRADE
            and plan_event
            and not active_plan_matches
        )
        if new_plan_blocked:
            runtime.last_blocked_generation = runtime.bus_generation
            runtime.last_blocked_time_ms = bar.epoch_ms

        may_accept_plan = runtime.phase in {PHASE_NONE, PHASE_CLOSED}
        if (
            bar.confirmed
            and not recovery_now
            and may_accept_plan
            and plan_event
            and bar.plan is not None
        ):
            self._stage_plan(bar.plan, bar.epoch_ms)

        if (
            bar.confirmed
            and not recovery_now
            and runtime.phase == PHASE_ARMED
            and plan_valid
            and bar.plan is not None
        ):
            runtime.entry_price = _required(
                bar.plan.trigger, "bar.plan.trigger"
            )
            runtime.initial_stop = _required(
                bar.plan.stop, "bar.plan.stop"
            )
            runtime.active_stop = _required(
                bar.plan.stop, "bar.plan.stop"
            )
            runtime.target1 = _required(
                bar.plan.target1, "bar.plan.target1"
            )
            runtime.target2 = _required(
                bar.plan.target2, "bar.plan.target2"
            )
            if plan_event:
                runtime.plan_schema = bar.plan.schema
                runtime.plan_source_kind = _required(
                    bar.plan.source_kind, "bar.plan.source_kind"
                )
                runtime.plan_trigger = bar.plan.trigger
                runtime.plan_invalidation = _required(
                    bar.plan.invalidation, "bar.plan.invalidation"
                )
                runtime.plan_generation = runtime.bus_generation
                runtime.plan_epoch_ms = runtime.bus_generation_epoch_ms

        if bar.confirmed and runtime.phase == PHASE_ARMED and not plan_valid:
            runtime.clear_trade()

        entry_event = False
        if (
            bar.confirmed
            and not recovery_now
            and runtime.phase == PHASE_ARMED
            and runtime.entry_price is not None
        ):
            entry_crossed = bar.high >= runtime.entry_price and (
                bar.low <= runtime.entry_price or bar.open > runtime.entry_price
            )
            if entry_crossed:
                entry_event = True
                runtime.phase = PHASE_IN_TRADE
                runtime.entry_bar = bar_index
                runtime.entry_time_ms = bar.epoch_ms
                runtime.protected_high = bar.high

        evaluate_trade = (
            bar.confirmed and not recovery_now and runtime.phase == PHASE_IN_TRADE
        )
        stop_before_management = runtime.active_stop
        stop_hit = (
            evaluate_trade
            and stop_before_management is not None
            and bar.low <= stop_before_management
        )
        target2_hit = (
            evaluate_trade
            and not stop_hit
            and runtime.target2 is not None
            and bar.high >= runtime.target2
        )
        time_stop_hit = (
            evaluate_trade
            and not stop_hit
            and not target2_hit
            and self.config.use_time_stop
            and not self.config.simple_mode
            and runtime.entry_time_ms is not None
            and (bar.epoch_ms - runtime.entry_time_ms)
            >= self.config.time_stop_minutes * MINUTE_MS
        )
        target1_event = (
            evaluate_trade
            and not stop_hit
            and not target2_hit
            and not runtime.target1_hit
            and runtime.target1 is not None
            and bar.high >= runtime.target1
        )

        exit_code = (
            EXIT_STOP
            if stop_hit
            else EXIT_TARGET_2
            if target2_hit
            else EXIT_TIME_STOP
            if time_stop_hit
            else EXIT_NONE
        )
        if exit_code != EXIT_NONE:
            runtime.phase = PHASE_CLOSED
            runtime.terminal_exit_code = exit_code
            runtime.terminal_exit_bar = bar_index
            runtime.terminal_exit_time_ms = bar.epoch_ms
        elif evaluate_trade:
            if target1_event:
                runtime.target1_hit = True
                if self.config.breakeven:
                    runtime.active_stop = max(
                        _required(
                            runtime.active_stop, "runtime.active_stop"
                        ),
                        _required(
                            runtime.entry_price, "runtime.entry_price"
                        ),
                    )
            runtime.protected_high = (
                bar.high
                if runtime.protected_high is None
                else max(runtime.protected_high, bar.high)
            )
            chandelier_next = (
                runtime.protected_high
                - bar.atr * self.config.atr_multiplier
            )
            if (
                self.config.use_chandelier
                and not self.config.simple_mode
                and runtime.active_stop is not None
            ):
                runtime.active_stop = max(
                    runtime.active_stop, chandelier_next
                )

        alerts: list[str] = []
        if entry_event:
            alerts.append("HM_ENTRY")
        if target1_event:
            alerts.append("HM_T1")
        if target2_hit:
            alerts.append("HM_T2")
        if stop_hit:
            alerts.append("HM_STOP")
        if time_stop_hit:
            alerts.append("HM_TIMESTOP")
        if exit_code != EXIT_NONE:
            alerts.append("HM_EXIT_ANY")

        observation = Observation(
            bar_index=bar_index,
            epoch_ms=bar.epoch_ms,
            phase=PHASE_NAMES[runtime.phase],
            plan_generation=runtime.plan_generation,
            entry_epoch_ms=runtime.entry_time_ms,
            protected_high=runtime.protected_high,
            target1_hit=runtime.target1_hit,
            active_stop=runtime.active_stop,
            terminal_exit=EXIT_NAMES[runtime.terminal_exit_code],
            terminal_exit_epoch_ms=runtime.terminal_exit_time_ms,
            new_plan_blocked=new_plan_blocked,
            event_warning=bar.event_warning,
            stale_context=bar.stale_context,
            alerts=tuple(alerts),
        )
        self.observations.append(observation)
        self._previous_plan = bar.plan
        self._previous_plan_valid = plan_valid
        self._previous_epoch_ms = bar.epoch_ms
        return observation

    def run(self, bars: list[Bar]) -> tuple[Observation, ...]:
        for index, bar in enumerate(bars):
            self.step(bar, index)
        return tuple(self.observations)


@dataclass(frozen=True)
class CaseResult:
    """Stable repository-preflight result for one R2.4 matrix row."""

    case_id: str
    name: str
    repository_preflight_status: str
    tradingview_status: str
    run_count: int
    assertions: list[str]
    alert_counts: dict[str, int]
    final_diagnostics: dict[str, object]


def _bar(
    minute: int,
    *,
    open_: float = 99.0,
    high: float = 99.0,
    low: float = 98.0,
    close: float = 99.0,
    plan: Plan | None = None,
    atr: float = 2.0,
    event_warning: bool = False,
    stale_context: bool = False,
) -> Bar:
    return Bar(
        epoch_ms=minute * MINUTE_MS,
        open=open_,
        high=high,
        low=low,
        close=close,
        plan=plan,
        atr=atr,
        event_warning=event_warning,
        stale_context=stale_context,
    )


def _run(
    bars: list[Bar], config: ReplayConfig | None = None
) -> tuple[Observation, ...]:
    return HoldReplay(config).run(bars)


def _diagnostics(observation: Observation) -> dict[str, object]:
    return {
        "phase": observation.phase,
        "planGeneration": observation.plan_generation,
        "entryEpochMs": observation.entry_epoch_ms,
        "protectedHigh": observation.protected_high,
        "target1Hit": observation.target1_hit,
        "activeStop": observation.active_stop,
        "terminalExit": observation.terminal_exit,
        "terminalExitEpochMs": observation.terminal_exit_epoch_ms,
        "newPlanBlocked": observation.new_plan_blocked,
    }


def _counts(trace: tuple[Observation, ...]) -> dict[str, int]:
    counts = Counter(alert for row in trace for alert in row.alerts)
    return dict(sorted(counts.items()))


def _result(
    case_id: str,
    name: str,
    trace: tuple[Observation, ...],
    assertions: list[tuple[bool, str]],
    *,
    run_count: int = 1,
) -> CaseResult:
    failed = [description for passed, description in assertions if not passed]
    if failed:
        raise AssertionError(f"{case_id}: {'; '.join(failed)}")
    return CaseResult(
        case_id=case_id,
        name=name,
        repository_preflight_status="passed",
        tradingview_status="pending",
        run_count=run_count,
        assertions=[description for _passed, description in assertions],
        alert_counts=_counts(trace),
        final_diagnostics=_diagnostics(trace[-1]),
    )


def _case_arm_without_entry() -> CaseResult:
    plan = Plan()
    trace = _run([_bar(1, plan=plan), _bar(5, plan=plan)])
    return _result(
        "R2.4-01",
        "arm without entry",
        trace,
        [
            (trace[-1].phase == "ARMED", "state remains ARMED"),
            (_counts(trace).get("HM_ENTRY", 0) == 0, "no entry alert"),
        ],
    )


def _case_delayed_entry() -> CaseResult:
    plan = Plan()
    trace = _run(
        [
            _bar(1, plan=plan),
            _bar(200, plan=plan),
            _bar(205, high=105.0, low=99.0, close=103.0, plan=plan),
        ]
    )
    return _result(
        "R2.4-02",
        "delayed entry after a long wait",
        trace,
        [
            (trace[-1].phase == "IN_TRADE", "late trigger enters trade"),
            (
                trace[-1].entry_epoch_ms == 205 * MINUTE_MS,
                "entry epoch is the accepted bar",
            ),
        ],
    )


def _case_time_stop_starts_at_entry() -> CaseResult:
    plan = Plan()
    trace = _run(
        [
            _bar(1, plan=plan),
            _bar(200, plan=plan),
            _bar(205, high=105.0, low=99.0, close=103.0, plan=plan),
            _bar(294, high=106.0, low=101.0, close=104.0, plan=plan),
            _bar(295, high=106.0, low=101.0, close=104.0, plan=plan),
        ],
        ReplayConfig(use_chandelier=False),
    )
    return _result(
        "R2.4-03",
        "time-stop starts only at entry",
        trace,
        [
            (trace[-2].phase == "IN_TRADE", "89 minutes does not exit"),
            (trace[-1].terminal_exit == "TIME_STOP", "90 minutes exits"),
            (
                _counts(trace).get("HM_TIMESTOP", 0) == 1,
                "one time-stop alert",
            ),
        ],
    )


def _case_entry_and_target1_same_bar() -> CaseResult:
    plan = Plan()
    trace = _run(
        [_bar(1, high=115.0, low=99.0, close=112.0, plan=plan)],
        ReplayConfig(use_chandelier=False),
    )
    return _result(
        "R2.4-04",
        "entry and Target 1 on one bar",
        trace,
        [
            (trace[-1].phase == "IN_TRADE", "trade remains open"),
            (trace[-1].target1_hit, "Target 1 is retained"),
            (trace[-1].active_stop == 100.0, "stop moves to break-even"),
            (_counts(trace).get("HM_T1", 0) == 1, "one Target-1 alert"),
        ],
    )


def _case_entry_and_stop_same_bar() -> CaseResult:
    plan = Plan()
    trace = _run([_bar(1, high=105.0, low=93.0, close=96.0, plan=plan)])
    return _result(
        "R2.4-05",
        "entry and stop on one bar",
        trace,
        [
            (trace[-1].terminal_exit == "STOP", "stop wins same-bar"),
            (_counts(trace).get("HM_ENTRY", 0) == 1, "one entry alert"),
            (_counts(trace).get("HM_STOP", 0) == 1, "one stop alert"),
            (_counts(trace).get("HM_EXIT_ANY", 0) == 1, "one master exit"),
        ],
    )


def _case_gap_across_entry() -> CaseResult:
    plan = Plan()
    trace = _run(
        [
            _bar(1, plan=plan),
            _bar(
                2,
                open_=104.0,
                high=106.0,
                low=103.0,
                close=105.0,
                plan=plan,
            ),
        ],
        ReplayConfig(use_chandelier=False),
    )
    return _result(
        "R2.4-06",
        "gap across entry",
        trace,
        [
            (trace[-1].phase == "IN_TRADE", "opening gap enters trade"),
            (_counts(trace).get("HM_ENTRY", 0) == 1, "one entry alert"),
        ],
    )


def _case_gap_across_stop() -> CaseResult:
    plan = Plan()
    trace = _run(
        [
            _bar(1, high=105.0, low=99.0, close=103.0, plan=plan),
            _bar(
                2,
                open_=90.0,
                high=92.0,
                low=88.0,
                close=89.0,
                plan=plan,
            ),
        ],
        ReplayConfig(use_chandelier=False),
    )
    return _result(
        "R2.4-07",
        "gap across stop",
        trace,
        [
            (trace[-1].terminal_exit == "STOP", "gap closes at stop reason"),
            (_counts(trace).get("HM_STOP", 0) == 1, "one stop alert"),
        ],
    )


def _case_break_even_after_target1() -> CaseResult:
    plan = Plan()
    trace = _run(
        [
            _bar(1, high=105.0, low=99.0, close=103.0, plan=plan),
            _bar(2, high=112.0, low=101.0, close=111.0, plan=plan),
        ],
        ReplayConfig(use_chandelier=False),
    )
    return _result(
        "R2.4-08",
        "break-even after Target 1",
        trace,
        [
            (trace[-1].target1_hit, "Target 1 state is true"),
            (trace[-1].active_stop == 100.0, "active stop is entry"),
        ],
    )


def _case_chandelier_never_decreases() -> CaseResult:
    plan = Plan()
    trace = _run(
        [
            _bar(1, high=105.0, low=99.0, close=103.0, plan=plan, atr=2.0),
            _bar(2, high=112.0, low=101.0, close=110.0, plan=plan, atr=2.0),
            _bar(3, high=111.0, low=108.0, close=109.0, plan=plan, atr=4.0),
        ]
    )
    stops = [
        row.active_stop for row in trace if row.active_stop is not None
    ]
    return _result(
        "R2.4-09",
        "Chandelier stop never decreases",
        trace,
        [
            (stops == sorted(stops), "active stop is monotonic"),
            (trace[-1].protected_high == 112.0, "protected high is retained"),
        ],
    )


def _case_target2_exit() -> CaseResult:
    plan = Plan()
    trace = _run(
        [
            _bar(1, high=105.0, low=99.0, close=103.0, plan=plan),
            _bar(2, high=121.0, low=101.0, close=120.0, plan=plan),
        ],
        ReplayConfig(use_chandelier=False),
    )
    return _result(
        "R2.4-10",
        "Target 2 full exit",
        trace,
        [
            (trace[-1].terminal_exit == "TARGET_2", "Target 2 closes trade"),
            (_counts(trace).get("HM_T2", 0) == 1, "one Target-2 alert"),
            (_counts(trace).get("HM_EXIT_ANY", 0) == 1, "one master exit"),
        ],
    )


def _case_reset_each_state() -> CaseResult:
    plan = Plan()
    traces = [
        _run(
            [_bar(1, plan=None), _bar(2, plan=None)],
            ReplayConfig(recovery_at_ms=2 * MINUTE_MS),
        ),
        _run(
            [_bar(1, plan=plan), _bar(2, plan=plan)],
            ReplayConfig(recovery_at_ms=2 * MINUTE_MS),
        ),
        _run(
            [
                _bar(1, high=105.0, low=99.0, close=103.0, plan=plan),
                _bar(2, high=106.0, low=101.0, close=104.0, plan=plan),
            ],
            ReplayConfig(
                use_chandelier=False,
                recovery_at_ms=2 * MINUTE_MS,
            ),
        ),
        _run(
            [
                _bar(1, high=105.0, low=93.0, close=96.0, plan=plan),
                _bar(2, plan=plan),
            ],
            ReplayConfig(recovery_at_ms=2 * MINUTE_MS),
        ),
    ]
    combined = tuple(row for trace in traces for row in trace)
    return _result(
        "R2.4-11",
        "reset during each state",
        combined,
        [
            (
                all(trace[-1].phase == "NONE" for trace in traces),
                "NONE, ARMED, IN_TRADE, and CLOSED reset to NONE",
            ),
            (
                all(
                    trace[-1].terminal_exit == "NONE" for trace in traces
                ),
                "terminal exit is cleared",
            ),
        ],
        run_count=len(traces),
    )


def _case_reload_armed() -> CaseResult:
    plan = Plan()
    bars = [_bar(1, plan=plan), _bar(2, plan=plan)]
    first = _run(bars)
    replay = _run(bars)
    return _result(
        "R2.4-12",
        "reload during Armed",
        replay,
        [
            (first == replay, "full confirmed replay is identical"),
            (replay[-1].phase == "ARMED", "reconstructed phase is ARMED"),
        ],
    )


def _case_reload_in_trade() -> CaseResult:
    plan = Plan()
    bars = [
        _bar(1, plan=plan),
        _bar(2, high=105.0, low=99.0, close=103.0, plan=plan),
        _bar(3, high=112.0, low=101.0, close=111.0, plan=plan),
    ]
    config = ReplayConfig(use_chandelier=False)
    first = _run(bars, config)
    replay = _run(bars, config)
    return _result(
        "R2.4-13",
        "reload during In Trade",
        replay,
        [
            (first == replay, "full confirmed replay is identical"),
            (
                replay[-1].phase == "IN_TRADE",
                "reconstructed phase is IN_TRADE",
            ),
            (replay[-1].target1_hit, "Target-1 state survives replay"),
        ],
    )


def _case_new_plan_in_trade() -> CaseResult:
    first_plan = Plan()
    second_plan = Plan(
        trigger=102.0,
        invalidation=97.0,
        stop=96.0,
        target1=112.0,
        target2=122.0,
    )
    trace = _run(
        [
            _bar(
                1,
                high=105.0,
                low=99.0,
                close=103.0,
                plan=first_plan,
            ),
            _bar(
                2,
                high=106.0,
                low=101.0,
                close=104.0,
                plan=second_plan,
            ),
        ],
        ReplayConfig(use_chandelier=False),
    )
    return _result(
        "R2.4-14",
        "new plan while In Trade",
        trace,
        [
            (trace[-1].new_plan_blocked, "new plan is reported blocked"),
            (trace[-1].plan_generation == 1, "active generation is unchanged"),
            (trace[-1].phase == "IN_TRADE", "active trade remains open"),
        ],
    )


def _case_schema_mismatch() -> CaseResult:
    trace = _run([_bar(1, plan=Plan(schema=7002))])
    return _result(
        "R2.4-15",
        "schema mismatch",
        trace,
        [
            (trace[-1].phase == "NONE", "schema mismatch fails closed"),
            (_counts(trace) == {}, "no alerts"),
        ],
    )


def _case_missing_bus_input() -> CaseResult:
    trace = _run([_bar(1, plan=Plan(target2=None))])
    return _result(
        "R2.4-16",
        "missing BUS input",
        trace,
        [
            (trace[-1].phase == "NONE", "missing level fails closed"),
            (_counts(trace) == {}, "no alerts"),
        ],
    )


def _case_stale_micro_profile() -> CaseResult:
    plan = Plan()
    trace = _run(
        [
            _bar(
                1,
                high=105.0,
                low=99.0,
                close=103.0,
                plan=plan,
                stale_context=True,
            )
        ],
        ReplayConfig(use_chandelier=False),
    )
    return _result(
        "R2.4-17",
        "stale Micro-Profile context",
        trace,
        [
            (trace[-1].phase == "IN_TRADE", "context does not fake an exit"),
            (trace[-1].stale_context, "stale context remains observable"),
            (_counts(trace).get("HM_EXIT_ANY", 0) == 0, "no exit alert"),
        ],
    )


def _case_event_warning() -> CaseResult:
    plan = Plan()
    trace = _run(
        [
            _bar(
                1,
                high=105.0,
                low=99.0,
                close=103.0,
                plan=plan,
                event_warning=True,
            ),
            _bar(
                2,
                high=106.0,
                low=101.0,
                close=104.0,
                plan=plan,
                event_warning=True,
            ),
        ],
        ReplayConfig(use_chandelier=False),
    )
    return _result(
        "R2.4-18",
        "event warning without forced false exit",
        trace,
        [
            (trace[-1].phase == "IN_TRADE", "warning does not close trade"),
            (trace[-1].event_warning, "event warning remains observable"),
            (_counts(trace).get("HM_EXIT_ANY", 0) == 0, "no false exit"),
        ],
    )


def _case_no_duplicate_alerts() -> CaseResult:
    plan = Plan()
    trace = _run(
        [
            _bar(1, high=105.0, low=99.0, close=103.0, plan=plan),
            _bar(2, high=112.0, low=101.0, close=111.0, plan=plan),
            _bar(3, high=113.0, low=101.0, close=112.0, plan=plan),
            _bar(4, high=106.0, low=99.0, close=100.0, plan=plan),
        ],
        ReplayConfig(use_chandelier=False),
    )
    counts = _counts(trace)
    return _result(
        "R2.4-19",
        "no duplicate edge alerts",
        trace,
        [
            (counts.get("HM_ENTRY", 0) == 1, "entry pulses once"),
            (counts.get("HM_T1", 0) == 1, "Target 1 pulses once"),
            (counts.get("HM_STOP", 0) == 1, "stop pulses once"),
            (counts.get("HM_EXIT_ANY", 0) == 1, "master exit pulses once"),
        ],
    )


def _case_non_intraday() -> CaseResult:
    plan = Plan()
    bars = [
        Bar(
            epoch_ms=DAY_MS,
            open=99.0,
            high=105.0,
            low=99.0,
            close=103.0,
            plan=plan,
        ),
        Bar(
            epoch_ms=2 * DAY_MS,
            open=104.0,
            high=106.0,
            low=101.0,
            close=104.0,
            plan=plan,
        ),
    ]
    trace = _run(bars, ReplayConfig(use_chandelier=False))
    return _result(
        "R2.4-20",
        "non-intraday timeframe behavior",
        trace,
        [
            (
                trace[-1].terminal_exit == "TIME_STOP",
                "daily elapsed time uses milliseconds",
            ),
            (
                _counts(trace).get("HM_TIMESTOP", 0) == 1,
                "one time-stop alert",
            ),
        ],
    )


CASE_BUILDERS: Final[tuple[Callable[[], CaseResult], ...]] = (
    _case_arm_without_entry,
    _case_delayed_entry,
    _case_time_stop_starts_at_entry,
    _case_entry_and_target1_same_bar,
    _case_entry_and_stop_same_bar,
    _case_gap_across_entry,
    _case_gap_across_stop,
    _case_break_even_after_target1,
    _case_chandelier_never_decreases,
    _case_target2_exit,
    _case_reset_each_state,
    _case_reload_armed,
    _case_reload_in_trade,
    _case_new_plan_in_trade,
    _case_schema_mismatch,
    _case_missing_bus_input,
    _case_stale_micro_profile,
    _case_event_warning,
    _case_no_duplicate_alerts,
    _case_non_intraday,
)


def build_replay_preflight() -> dict[str, object]:
    """Return the stable, fail-closed R2.4 repository evidence payload."""

    source_bytes = HOLD_MANAGER_SOURCE.read_bytes()
    cases = []
    for builder in CASE_BUILDERS:
        result = asdict(builder())
        cases.append(
            {
                "caseId": result["case_id"],
                "name": result["name"],
                "repositoryPreflightStatus": result[
                    "repository_preflight_status"
                ],
                "tradingViewStatus": result["tradingview_status"],
                "runCount": result["run_count"],
                "assertions": result["assertions"],
                "alertCounts": result["alert_counts"],
                "finalDiagnostics": result["final_diagnostics"],
            }
        )
    return {
        "schemaVersion": 1,
        "requirementId": "R2-REPLAY",
        "gateStatus": "partial",
        "repositoryPreflightStatus": "passed",
        "tradingViewStatus": "pending",
        "source": {
            "path": HOLD_MANAGER_SOURCE.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
        },
        "caseCount": len(cases),
        "cases": cases,
        "openGates": [
            (
                "Compile the pinned source in TradingView and retain the "
                "twenty-case diagnostic and alert evidence."
            ),
            (
                "Match TradingView HM hidden diagnostics and alert counts "
                "against this repository preflight."
            ),
        ],
        "limitations": [
            (
                "This Python transition model is a repository preflight, not "
                "execution evidence from the Pine runtime."
            ),
            (
                "No compile, binding, chart reload, Bar Replay, or alert-log "
                "claim is made by this artifact."
            ),
        ],
    }


def write_replay_preflight(path: Path = DEFAULT_OUTPUT) -> None:
    """Write the deterministic preflight payload with stable formatting."""

    atomic_write_text(  # tempfile+os.replace; also mkdirs the parent
        json.dumps(build_replay_preflight(), indent=2, sort_keys=True) + "\n",
        path,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="destination for the deterministic JSON evidence artifact",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when the existing artifact differs from generated content",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    expected = (
        json.dumps(build_replay_preflight(), indent=2, sort_keys=True) + "\n"
    )
    if args.check:
        if not args.output.exists():
            raise SystemExit(f"missing replay preflight: {args.output}")
        actual = args.output.read_text(encoding="utf-8")
        if actual != expected:
            raise SystemExit(
                f"stale replay preflight: regenerate {args.output}"
            )
        return 0
    atomic_write_text(expected, args.output)  # tempfile+os.replace; mkdirs parent
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
