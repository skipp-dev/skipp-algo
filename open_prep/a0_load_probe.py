"""Deterministic bounded-load and chaos probe for the A0-Fast stream path."""

from __future__ import annotations

import resource
import time
import tracemalloc
from dataclasses import asdict, dataclass
from typing import Any

from .a0_stream_buffer import BoundedBarBuffer
from .a0_stream_state import StreamBar

_WIRE_BYTES_PER_OHLCV_1S = 104


@dataclass(frozen=True, slots=True)
class A0LoadBudget:
    max_cpu_seconds: float = 10.0
    max_peak_memory_mb: float = 256.0
    max_wire_mb: float = 500.0
    max_drop_fraction: float = 0.50
    max_historical_requests: int = 10_000


@dataclass(frozen=True, slots=True)
class A0LoadScenario:
    name: str
    symbol_count: int
    duration_seconds: int
    buffer_capacity: int
    consumer_bars_per_second: int
    open_burst_multiplier: int = 1
    open_burst_seconds: int = 0
    disconnect_at_second: int | None = None
    restart_at_second: int | None = None
    bootstrap_at_start: bool = False
    expect_drops: bool = False

    def validate(self) -> None:
        if self.symbol_count < 1 or self.duration_seconds < 1:
            raise ValueError("symbol_count and duration_seconds must be positive")
        if self.buffer_capacity < 1 or self.consumer_bars_per_second < 0:
            raise ValueError("buffer_capacity must be positive and consumer rate non-negative")
        if self.open_burst_multiplier < 1 or self.open_burst_seconds < 0:
            raise ValueError("burst configuration is invalid")


def default_a0_load_scenarios(
    *,
    duration_seconds: int = 8,
    all_symbol_count: int | None = None,
) -> list[A0LoadScenario]:
    scenarios = [
        _normal_scenario("normal_200", 200, duration_seconds),
        _normal_scenario("normal_900", 900, duration_seconds),
        A0LoadScenario(
            "open_burst_900",
            900,
            duration_seconds,
            buffer_capacity=5_400,
            consumer_bars_per_second=2_700,
            open_burst_multiplier=3,
            open_burst_seconds=min(2, duration_seconds),
        ),
        A0LoadScenario(
            "slow_consumer_900",
            900,
            duration_seconds,
            buffer_capacity=1_800,
            consumer_bars_per_second=300,
            expect_drops=True,
        ),
        A0LoadScenario(
            "disconnect_900",
            900,
            duration_seconds,
            buffer_capacity=3_600,
            consumer_bars_per_second=1_800,
            disconnect_at_second=min(2, duration_seconds - 1),
        ),
        A0LoadScenario(
            "restart_bootstrap_900",
            900,
            duration_seconds,
            buffer_capacity=3_600,
            consumer_bars_per_second=1_800,
            restart_at_second=min(2, duration_seconds - 1),
            bootstrap_at_start=True,
        ),
    ]
    if all_symbol_count is not None:
        scenarios.append(
            _normal_scenario("normal_max_symbols", all_symbol_count, duration_seconds)
        )
    return scenarios


def _normal_scenario(name: str, symbols: int, duration: int) -> A0LoadScenario:
    return A0LoadScenario(
        name,
        symbols,
        duration,
        buffer_capacity=max(2_048, symbols * 4),
        consumer_bars_per_second=symbols * 2,
    )


def run_a0_load_probe(
    scenarios: list[A0LoadScenario],
    budget: A0LoadBudget,
) -> dict[str, Any]:
    results = [_run_scenario(scenario, budget) for scenario in scenarios]
    return {
        "schema_version": 1,
        "probe_kind": "deterministic_synthetic",
        "budget_source": "provisional_a0_002_v1",
        "drop_policy": "drop_oldest_then_require_historical_resync",
        "record_wire_bytes_assumption": _WIRE_BYTES_PER_OHLCV_1S,
        "budget": asdict(budget),
        "passed": all(result["passed"] for result in results),
        "scenarios": results,
    }


def _run_scenario(
    scenario: A0LoadScenario,
    budget: A0LoadBudget,
) -> dict[str, Any]:
    scenario.validate()
    cpu_started = time.process_time()
    tracemalloc.start()
    symbols = tuple(f"S{index:05d}" for index in range(scenario.symbol_count))
    buffer = BoundedBarBuffer(scenario.buffer_capacity)
    pending_resync = set(symbols) if scenario.bootstrap_at_start else set()
    produced = 0
    processed = 0
    resyncs = 0
    historical_requests = 0
    disconnects = 0
    restarts = 0
    max_depth = 0
    dropped_total = 0
    try:
        for second in range(scenario.duration_seconds):
            if second == scenario.disconnect_at_second:
                disconnects += 1
                pending_resync.update(symbols)
                continue
            if second == scenario.restart_at_second:
                restarts += 1
                pending_resync.update(symbols)
                dropped_total += buffer.snapshot().depth
                buffer = BoundedBarBuffer(scenario.buffer_capacity)

            multiplier = (
                scenario.open_burst_multiplier
                if second < scenario.open_burst_seconds
                else 1
            )
            for burst_index in range(multiplier):
                for symbol_index, symbol in enumerate(symbols):
                    sequence = second * multiplier + burst_index
                    offer = buffer.offer(StreamBar(
                        symbol=symbol,
                        close=100.0,
                        volume=100,
                        ts_event=float(second),
                        ts_recv=float(second) + 0.01,
                        sequence=sequence * scenario.symbol_count + symbol_index,
                    ))
                    produced += 1
                    if offer.dropped is not None:
                        dropped_total += 1
                        pending_resync.add(offer.dropped.symbol)

            for _ in range(scenario.consumer_bars_per_second):
                item = buffer.take(timeout=0)
                if item is None:
                    break
                processed += 1
                if item.resync_required or item.bar.symbol in pending_resync:
                    resyncs += 1
                    historical_requests += 1
                    pending_resync.discard(item.bar.symbol)
                    buffer.acknowledge_resync(item.bar.symbol)
            snapshot = buffer.snapshot()
            max_depth = max(max_depth, snapshot.high_watermark)
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    cpu_seconds = time.process_time() - cpu_started
    final_snapshot = buffer.snapshot()
    drop_fraction = dropped_total / produced if produced else 0.0
    wire_mb = produced * _WIRE_BYTES_PER_OHLCV_1S / 1_000_000.0
    peak_memory_mb = peak_bytes / 1_000_000.0
    peak_rss_mb = _peak_rss_mb()
    invariants = {
        "bounded_queue": max_depth <= scenario.buffer_capacity,
        "drop_policy_observable": (
            dropped_total == 0 or resyncs > 0 or bool(pending_resync)
        ),
        "slow_reader_expectation": (dropped_total > 0) == scenario.expect_drops,
        "disconnect_observable": (
            scenario.disconnect_at_second is None or disconnects == 1
        ),
        "restart_observable": scenario.restart_at_second is None or restarts == 1,
    }
    budget_checks = {
        "cpu": cpu_seconds <= budget.max_cpu_seconds,
        "peak_memory": peak_rss_mb <= budget.max_peak_memory_mb,
        "wire": wire_mb <= budget.max_wire_mb,
        "drop_fraction": drop_fraction <= budget.max_drop_fraction,
        "historical_requests": historical_requests <= budget.max_historical_requests,
    }
    return {
        "scenario": asdict(scenario),
        "passed": all(invariants.values()) and all(budget_checks.values()),
        "records_produced": produced,
        "records_processed": processed,
        "records_remaining": final_snapshot.depth,
        "queue_high_watermark": max_depth,
        "records_dropped": dropped_total,
        "drop_fraction": round(drop_fraction, 6),
        "resyncs_completed": resyncs,
        "resync_symbols_outstanding": len(pending_resync),
        "disconnects": disconnects,
        "restarts": restarts,
        "databento_usage": {
            "live_records": produced,
            "estimated_wire_mb": round(wire_mb, 6),
            "historical_requests": historical_requests,
        },
        "resources": {
            "cpu_seconds": round(cpu_seconds, 6),
            "peak_tracemalloc_mb": round(peak_memory_mb, 6),
            "process_peak_rss_mb": round(peak_rss_mb, 6),
        },
        "invariants": invariants,
        "budget_checks": budget_checks,
    }


def _peak_rss_mb() -> float:
    rss = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    rss_bytes = rss * 1024.0 if rss < 10_000_000 else rss
    return rss_bytes / 1_000_000.0
