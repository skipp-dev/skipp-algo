"""Tests for ``scripts.run_smc_live_incubation`` (C8/T3)."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from scripts.live_risk_limits import AccountState, RiskLimits
from scripts.run_smc_live_incubation import (
    _PHASE_DEFAULTS,
    main,
    run_live_incubation,
)
from scripts.smc_to_ibkr_adapter import IBKRExecutionConfig


_FROZEN_NOW = datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)


def _setup(variant: str = "smc_breaker_btc", **overrides) -> dict:
    base = {
        "variant": variant,
        "symbol": "BTC",
        "entry": 102.0,
        "stop_loss": 100.0,
        "take_profit": 104.0,
        "quantity": 100,
        "trade_date": "2026-04-26",
    }
    base.update(overrides)
    return base


def _healthy_state() -> AccountState:
    return AccountState(
        as_of=date(2026, 4, 26),
        equity=100_000.0,
        starting_equity_today=100_000.0,
        high_water_mark=100_000.0,
        open_positions=0,
        gross_exposure_pct=0.0,
        last_n_pnls=(),
    )


def _read_audit(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ── kill-switch path ───────────────────────────────────────────────


def test_halts_when_manual_kill_switch_engaged(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    summary = run_live_incubation(
        setup_records=[_setup()],
        gate_status_by_variant={"smc_breaker_btc": "green"},
        risk_limits=RiskLimits(manual_halt=True),
        account_state=_healthy_state(),
        execution_cfg=IBKRExecutionConfig(),
        audit_path=audit,
        now=_FROZEN_NOW,
    )
    assert summary["halted"] is True
    assert summary["intents_submitted"] == 0
    [record] = _read_audit(audit)
    assert record["action"] == "halted"
    assert record["kill_switch_triggered"] is True


# ── tradable filtering ────────────────────────────────────────────


def test_red_variants_are_blocked(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    summary = run_live_incubation(
        setup_records=[_setup(variant="bad_variant")],
        gate_status_by_variant={"bad_variant": "red"},
        risk_limits=RiskLimits(),
        account_state=_healthy_state(),
        execution_cfg=IBKRExecutionConfig(),
        audit_path=audit,
        now=_FROZEN_NOW,
    )
    assert summary["intents_submitted"] == 0
    assert summary["audit_records_written"] == 0


def test_unknown_variants_fail_closed(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    summary = run_live_incubation(
        setup_records=[_setup(variant="never_seen")],
        gate_status_by_variant={"smc_breaker_btc": "green"},
        risk_limits=RiskLimits(),
        account_state=_healthy_state(),
        execution_cfg=IBKRExecutionConfig(),
        audit_path=audit,
        now=_FROZEN_NOW,
    )
    assert summary["intents_submitted"] == 0


def test_green_and_amber_variants_are_tradable(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    summary = run_live_incubation(
        setup_records=[
            _setup(variant="green_one", symbol="BTC"),
            _setup(variant="amber_one", symbol="ETH"),
            _setup(variant="red_one", symbol="DOGE"),
        ],
        gate_status_by_variant={
            "green_one": "green",
            "amber_one": "amber",
            "red_one": "red",
        },
        risk_limits=RiskLimits(),
        account_state=_healthy_state(),
        execution_cfg=IBKRExecutionConfig(),
        audit_path=audit,
        now=_FROZEN_NOW,
    )
    assert summary["intents_submitted"] == 2
    audit_records = _read_audit(audit)
    symbols = {rec["symbol"] for rec in audit_records}
    assert symbols == {"BTC", "ETH"}


# ── audit log shape ──────────────────────────────────────────────


def test_audit_record_carries_phase_and_size_scale(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    run_live_incubation(
        setup_records=[_setup(variant="smc_breaker_btc")],
        gate_status_by_variant={"smc_breaker_btc": "green"},
        risk_limits=RiskLimits(),
        account_state=_healthy_state(),
        execution_cfg=IBKRExecutionConfig(),
        audit_path=audit,
        phase="live_small",
        size_scale=0.10,
        now=_FROZEN_NOW,
    )
    [record] = _read_audit(audit)
    assert record["phase"] == "live_small"
    assert record["size_scale"] == pytest.approx(0.10)
    assert record["entry_price"] == pytest.approx(102.0)
    assert record["stop_loss"] == pytest.approx(100.0)
    assert record["take_profit"] == pytest.approx(104.0)
    assert record["quantity"] == 10  # 100 × 0.10
    assert record["kill_switch_triggered"] is False


def test_audit_log_appends_across_runs(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    for sym in ("BTC", "ETH"):
        run_live_incubation(
            setup_records=[_setup(variant="v", symbol=sym)],
            gate_status_by_variant={"v": "green"},
            risk_limits=RiskLimits(),
            account_state=_healthy_state(),
            execution_cfg=IBKRExecutionConfig(),
            audit_path=audit,
            now=_FROZEN_NOW,
        )
    records = _read_audit(audit)
    assert [rec["symbol"] for rec in records] == ["BTC", "ETH"]


def test_atomic_write_leaves_no_tmp_file(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    run_live_incubation(
        setup_records=[_setup(variant="v")],
        gate_status_by_variant={"v": "green"},
        risk_limits=RiskLimits(),
        account_state=_healthy_state(),
        execution_cfg=IBKRExecutionConfig(),
        audit_path=audit,
        now=_FROZEN_NOW,
    )
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []


def test_custom_submit_fn_is_called(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    captured = []

    def fake_submit(intents):
        captured.extend(intents)
        return [
            {"intent_id": i.order_ref, "action": "filled", "fill_price": 102.5}
            for i in intents
        ]

    run_live_incubation(
        setup_records=[_setup(variant="v")],
        gate_status_by_variant={"v": "green"},
        risk_limits=RiskLimits(),
        account_state=_healthy_state(),
        execution_cfg=IBKRExecutionConfig(),
        audit_path=audit,
        submit_fn=fake_submit,
        now=_FROZEN_NOW,
    )
    assert len(captured) == 1
    [record] = _read_audit(audit)
    assert record["action"] == "filled"
    assert record["fill_price"] == pytest.approx(102.5)


# ── CLI ────────────────────────────────────────────────────────


def test_cli_main_runs_end_to_end(tmp_path: Path, capsys) -> None:
    setups = tmp_path / "setups.json"
    setups.write_text(json.dumps([_setup(variant="v")]), encoding="utf-8")
    statuses = tmp_path / "statuses.json"
    statuses.write_text(json.dumps({"v": "green"}), encoding="utf-8")
    audit = tmp_path / "audit.jsonl"

    rc = main(
        [
            "--phase", "paper",
            "--setups", str(setups),
            "--gate-statuses", str(statuses),
            "--audit-output", str(audit),
        ]
    )
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["phase"] == "paper"
    assert summary["intents_submitted"] == 1


def test_phase_defaults_table_is_complete() -> None:
    # All advertised phases must have both fields set.
    for phase, defaults in _PHASE_DEFAULTS.items():
        assert "size_scale" in defaults, f"phase {phase} missing size_scale"
        assert "paper_mode" in defaults, f"phase {phase} missing paper_mode"
