"""Deterministic A0-Fast load, cost and chaos-probe tests."""

from __future__ import annotations

from open_prep.a0_load_probe import (
    A0LoadBudget,
    A0LoadScenario,
    default_a0_load_scenarios,
    run_a0_load_probe,
)


def test_default_probe_covers_required_scenarios_and_bounded_drop_policy() -> None:
    report = run_a0_load_probe(
        default_a0_load_scenarios(duration_seconds=4, all_symbol_count=1_200),
        A0LoadBudget(),
    )
    names = {row["scenario"]["name"] for row in report["scenarios"]}
    assert names == {
        "normal_200",
        "normal_900",
        "normal_max_symbols",
        "open_burst_900",
        "slow_consumer_900",
        "disconnect_900",
        "restart_bootstrap_900",
    }
    slow = next(row for row in report["scenarios"] if row["scenario"]["name"] == "slow_consumer_900")
    assert slow["records_dropped"] > 0
    assert slow["invariants"]["bounded_queue"] is True
    assert slow["invariants"]["drop_policy_observable"] is True
    assert report["drop_policy"] == "drop_oldest_then_require_historical_resync"


def test_probe_fails_when_explicit_resource_budget_is_exceeded() -> None:
    scenario = A0LoadScenario(
        "budget_failure",
        symbol_count=10,
        duration_seconds=2,
        buffer_capacity=20,
        consumer_bars_per_second=20,
    )
    report = run_a0_load_probe(
        [scenario],
        A0LoadBudget(max_wire_mb=0.000001),
    )
    assert report["passed"] is False
    assert report["scenarios"][0]["budget_checks"]["wire"] is False


def test_disconnect_and_restart_require_historical_resync() -> None:
    rows = run_a0_load_probe(
        default_a0_load_scenarios(duration_seconds=4),
        A0LoadBudget(),
    )["scenarios"]
    disconnect = next(row for row in rows if row["scenario"]["name"] == "disconnect_900")
    restart = next(row for row in rows if row["scenario"]["name"] == "restart_bootstrap_900")
    assert disconnect["disconnects"] == 1
    assert disconnect["databento_usage"]["historical_requests"] > 0
    assert restart["restarts"] == 1
    assert restart["resyncs_completed"] > 0
