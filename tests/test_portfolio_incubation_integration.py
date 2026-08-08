from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from governance.portfolio_contract import PortfolioSnapshotV1
from governance.portfolio_risk import PortfolioRiskLimitsV1, PortfolioRiskMode
from scripts.live_risk_limits import AccountState, RiskLimits
from scripts.run_smc_live_incubation import run_live_incubation
from scripts.smc_to_ibkr_adapter import IBKRExecutionConfig

NOW = datetime(2026, 8, 8, 14, 0, tzinfo=UTC)


def _account_state() -> AccountState:
    return AccountState(
        as_of=date(2026, 8, 8),
        equity=10_000,
        starting_equity_today=10_000,
        high_water_mark=10_000,
        open_positions=0,
        gross_exposure_pct=0,
    )


def _snapshot() -> PortfolioSnapshotV1:
    return PortfolioSnapshotV1.build(
        captured_at=NOW,
        account="DU1",
        base_currency="USD",
        equity=10_000,
        available_funds=10_000,
        source="test",
        complete=True,
    )


def _setup() -> dict:
    return {
        "variant": "v",
        "symbol": "AAPL",
        "entry": 100,
        "stop_loss": 95,
        "take_profit": 110,
        "quantity": 100,
        "trade_date": "2026-08-08",
    }


def _read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_shadow_records_would_block_but_still_calls_submitter(tmp_path: Path) -> None:
    submitted = []

    def submit(intents):
        submitted.extend(intents)
        return [{"intent_id": item.order_ref, "action": "audit_only"} for item in intents]

    audit = tmp_path / "audit.jsonl"
    summary = run_live_incubation(
        setup_records=[_setup()],
        gate_status_by_variant={"v": "green"},
        risk_limits=RiskLimits(),
        account_state=_account_state(),
        execution_cfg=IBKRExecutionConfig(),
        audit_path=audit,
        submit_fn=submit,
        now=NOW,
        portfolio_snapshot=_snapshot(),
        portfolio_limits=PortfolioRiskLimitsV1(
            mode=PortfolioRiskMode.SHADOW,
            max_single_position_pct=5,
        ),
    )
    assert len(submitted) == 1
    assert summary["portfolio_risk"]["verdict"] == "resize"
    rows = _read(audit)
    assert rows[0]["action"] == "portfolio_risk_evaluated"
    assert rows[1]["portfolio_risk"]["verdict"] == "resize"


def test_enforce_blocks_submitter_and_audits_each_intent(tmp_path: Path) -> None:
    called = False

    def submit(intents):
        nonlocal called
        called = True
        return []

    audit = tmp_path / "audit.jsonl"
    summary = run_live_incubation(
        setup_records=[_setup()],
        gate_status_by_variant={"v": "green"},
        risk_limits=RiskLimits(),
        account_state=_account_state(),
        execution_cfg=IBKRExecutionConfig(),
        audit_path=audit,
        submit_fn=submit,
        now=NOW,
        portfolio_snapshot=_snapshot(),
        portfolio_limits=PortfolioRiskLimitsV1(
            mode=PortfolioRiskMode.ENFORCE,
            max_single_position_pct=5,
        ),
    )
    assert called is False
    assert summary["intents_passed_to_submitter"] == 0
    assert summary["intents_portfolio_blocked"] == 1
    rows = _read(audit)
    assert rows[1]["action"] == "portfolio_blocked"
    assert rows[1]["portfolio_risk"]["recommended_scale"] == 0.5


def test_portfolio_inputs_must_be_supplied_as_a_pair(tmp_path: Path) -> None:
    try:
        run_live_incubation(
            setup_records=[_setup()],
            gate_status_by_variant={"v": "green"},
            risk_limits=RiskLimits(),
            account_state=_account_state(),
            execution_cfg=IBKRExecutionConfig(),
            audit_path=tmp_path / "audit.jsonl",
            now=NOW,
            portfolio_snapshot=_snapshot(),
        )
    except ValueError as exc:
        assert "supplied together" in str(exc)
    else:
        raise AssertionError("missing portfolio limits must fail loud")


def test_direct_api_refuses_enforcement_outside_paper(tmp_path: Path) -> None:
    try:
        run_live_incubation(
            setup_records=[_setup()],
            gate_status_by_variant={"v": "green"},
            risk_limits=RiskLimits(),
            account_state=_account_state(),
            execution_cfg=IBKRExecutionConfig(),
            audit_path=tmp_path / "audit.jsonl",
            phase="live_small",
            now=NOW,
            portfolio_snapshot=_snapshot(),
            portfolio_limits=PortfolioRiskLimitsV1(mode=PortfolioRiskMode.ENFORCE),
        )
    except ValueError as exc:
        assert "restricted to phase='paper'" in str(exc)
    else:
        raise AssertionError("non-paper portfolio enforcement must fail closed")
