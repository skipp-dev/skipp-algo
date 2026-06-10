"""Tests for ``scripts.run_smc_live_incubation`` (C8/T3)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from scripts.live_risk_limits import AccountState, RiskLimits
from scripts.run_smc_live_incubation import (
    _PHASE_DEFAULTS,
    main,
    run_live_incubation,
)
from scripts.smc_to_ibkr_adapter import IBKRExecutionConfig
from scripts.wsh_earnings_calendar import WSH_EVENTS_SCHEMA_VERSION

_FROZEN_NOW = datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC)


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


def test_audit_carries_variant_when_order_ref_is_synthesized(tmp_path: Path) -> None:
    """Regression for PR #286 review: setups without explicit order_ref
    get a synthesized one in build_ibkr_intents_from_smc_setups; the
    variant must still propagate to the audit row.
    """
    audit = tmp_path / "audit.jsonl"
    run_live_incubation(
        setup_records=[_setup(variant="smc_breaker_btc")],  # no order_ref
        gate_status_by_variant={"smc_breaker_btc": "green"},
        risk_limits=RiskLimits(),
        account_state=_healthy_state(),
        execution_cfg=IBKRExecutionConfig(),
        audit_path=audit,
        now=_FROZEN_NOW,
    )
    [record] = _read_audit(audit)
    assert record["variant"] == "smc_breaker_btc"
    assert record["intent_id"].startswith("smc-BTC-2026-04-26-port")


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


def test_cli_live_phase_requires_account_state_json(tmp_path: Path) -> None:
    """C-sprint deep-review C8 MINOR fix: live phases must refuse to run
    without an explicit ``--account-state-json`` snapshot. The default
    zero-AccountState would make the kill-switch silently no-op against
    drawdown / equity / P&L history.
    """
    setups = tmp_path / "setups.json"
    setups.write_text(json.dumps([_setup(variant="v")]), encoding="utf-8")
    statuses = tmp_path / "statuses.json"
    statuses.write_text(json.dumps({"v": "green"}), encoding="utf-8")
    audit = tmp_path / "audit.jsonl"

    for phase in ("live_small", "live_full"):
        with pytest.raises(SystemExit, match="account-state-json"):
            main([
                "--phase", phase,
                "--setups", str(setups),
                "--gate-statuses", str(statuses),
                "--audit-output", str(audit),
            ])


def test_cli_live_phase_loads_account_state_json(tmp_path: Path) -> None:
    setups = tmp_path / "setups.json"
    setups.write_text(json.dumps([_setup(variant="v")]), encoding="utf-8")
    statuses = tmp_path / "statuses.json"
    statuses.write_text(json.dumps({"v": "green"}), encoding="utf-8")
    audit = tmp_path / "audit.jsonl"

    snapshot = {
        "as_of": "2026-04-26",
        "equity": 100000.0,
        "starting_equity_today": 100000.0,
        "high_water_mark": 100000.0,
        "open_positions": 0,
        "gross_exposure_pct": 0.0,
        "last_n_pnls": [10.0, -5.0],
    }
    state_path = tmp_path / "account.json"
    state_path.write_text(json.dumps(snapshot), encoding="utf-8")

    rc = main([
        "--phase", "live_small",
        "--setups", str(setups),
        "--gate-statuses", str(statuses),
        "--audit-output", str(audit),
        "--account-state-json", str(state_path),
        "--phase-eval-report", str(_passing_eval_report(tmp_path, phase="paper")),
    ])
    assert rc == 0


def _passing_eval_report(tmp_path: Path, *, phase: str) -> Path:
    """Write a minimal passing phase-eval report (stat-review F1)."""
    from datetime import UTC, datetime

    payload = {
        "schema_version": "1.0.0",
        "phase": phase,
        "variant": "v",
        "all_passed": True,
        "computed_at": datetime.now(UTC).isoformat(),
        "results": [],
        "phase_promotion": "manual_signoff_only",
    }
    path = tmp_path / f"phase_eval_{phase}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_cli_live_phase_requires_phase_eval_report(tmp_path: Path) -> None:
    """Stat-review F1 (2026-06-10): live phases refuse to run without a
    machine-verified passing evaluation of the prior phase's criteria."""
    setups = tmp_path / "setups.json"
    setups.write_text(json.dumps([_setup(variant="v")]), encoding="utf-8")
    statuses = tmp_path / "statuses.json"
    statuses.write_text(json.dumps({"v": "green"}), encoding="utf-8")
    audit = tmp_path / "audit.jsonl"

    snapshot = {
        "as_of": "2026-04-26",
        "equity": 100000.0,
        "starting_equity_today": 100000.0,
        "high_water_mark": 100000.0,
        "open_positions": 0,
        "gross_exposure_pct": 0.0,
    }
    state_path = tmp_path / "account.json"
    state_path.write_text(json.dumps(snapshot), encoding="utf-8")

    for phase in ("live_small", "live_full"):
        with pytest.raises(SystemExit, match="phase-eval-report"):
            main([
                "--phase", phase,
                "--setups", str(setups),
                "--gate-statuses", str(statuses),
                "--audit-output", str(audit),
                "--account-state-json", str(state_path),
            ])


def test_cli_live_full_rejects_paper_eval_report(tmp_path: Path) -> None:
    """live_full needs a passing live_small evaluation — a paper report
    must be rejected (wrong prior phase)."""
    setups = tmp_path / "setups.json"
    setups.write_text(json.dumps([_setup(variant="v")]), encoding="utf-8")
    statuses = tmp_path / "statuses.json"
    statuses.write_text(json.dumps({"v": "green"}), encoding="utf-8")
    audit = tmp_path / "audit.jsonl"

    snapshot = {
        "as_of": "2026-04-26",
        "equity": 100000.0,
        "starting_equity_today": 100000.0,
        "high_water_mark": 100000.0,
        "open_positions": 0,
        "gross_exposure_pct": 0.0,
    }
    state_path = tmp_path / "account.json"
    state_path.write_text(json.dumps(snapshot), encoding="utf-8")

    with pytest.raises(SystemExit, match="live_small"):
        main([
            "--phase", "live_full",
            "--setups", str(setups),
            "--gate-statuses", str(statuses),
            "--audit-output", str(audit),
            "--account-state-json", str(state_path),
            "--phase-eval-report",
            str(_passing_eval_report(tmp_path, phase="paper")),
        ])


def test_account_state_json_rejects_null_last_n_pnls(tmp_path: Path) -> None:
    """Copilot pass-4: explicit JSON null for last_n_pnls must produce a
    clear ValueError, not a raw TypeError from ``float(x) for x in None``."""
    from scripts.run_smc_live_incubation import _account_state_from_json

    state_path = tmp_path / "account.json"
    state_path.write_text(json.dumps({
        "as_of": "2026-04-26",
        "equity": 100000.0,
        "starting_equity_today": 100000.0,
        "high_water_mark": 100000.0,
        "open_positions": 0,
        "gross_exposure_pct": 0.0,
        "last_n_pnls": None,
    }), encoding="utf-8")
    # JSON ``null`` -> Python ``None`` -> documented "treat as empty".
    state = _account_state_from_json(state_path)
    assert state.last_n_pnls == ()


def test_account_state_json_rejects_non_iterable_last_n_pnls(tmp_path: Path) -> None:
    """A scalar last_n_pnls must produce a clear ValueError (not a TypeError)."""
    import pytest

    from scripts.run_smc_live_incubation import _account_state_from_json

    state_path = tmp_path / "account.json"
    state_path.write_text(json.dumps({
        "as_of": "2026-04-26",
        "equity": 100000.0,
        "starting_equity_today": 100000.0,
        "high_water_mark": 100000.0,
        "open_positions": 0,
        "gross_exposure_pct": 0.0,
        "last_n_pnls": 42,
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="last_n_pnls must be a list/tuple"):
        _account_state_from_json(state_path)


# ── T7.2 EarningsFilter integration ────────────────────────────────


def test_earnings_filter_blocks_intent_and_records_audit(tmp_path: Path) -> None:
    """When EarningsFilter blocks a symbol, no submit happens but an
    ``earnings_blocked`` audit row is written with the decision payload."""
    from scripts.run_smc_live_incubation import run_live_incubation
    from smc_integration.earnings_filter import EarningsFilter

    wsh = tmp_path / "wsh.jsonl"
    wsh.write_text(json.dumps({
        "symbol": "BTC",
        "con_id": 1,
        "event_type": "Earnings",
        "event_date": "2026-04-26",
        "event_time": None,
        "timezone": None,
        "confidence": "Confirmed",
        "source": "WSH",
        "schema_version": WSH_EVENTS_SCHEMA_VERSION,
    }) + "\n", encoding="utf-8")

    audit = tmp_path / "audit.jsonl"
    submitted: list = []

    def submit(intents):
        submitted.extend(intents)
        return [{"intent_id": i.order_ref, "action": "filled"} for i in intents]

    summary = run_live_incubation(
        setup_records=[_setup()],
        gate_status_by_variant={"smc_breaker_btc": "green"},
        risk_limits=RiskLimits(),
        account_state=_healthy_state(),
        execution_cfg=IBKRExecutionConfig(paper_mode=True),
        audit_path=audit,
        phase="paper",
        submit_fn=submit,
        now=_FROZEN_NOW,
        earnings_filter=EarningsFilter(events_jsonl=wsh),
    )

    assert summary["intents_submitted"] == 0
    assert summary["intents_earnings_blocked"] == 1
    assert submitted == []
    rows = _read_audit(audit)
    assert len(rows) == 1
    assert rows[0]["action"] == "earnings_blocked"
    assert rows[0]["earnings_filter"]["blocked"] is True


def test_earnings_filter_missing_jsonl_is_no_op(tmp_path: Path) -> None:
    """Phase-A invariant: missing WSH JSONL must NOT block any intent."""
    from scripts.run_smc_live_incubation import run_live_incubation
    from smc_integration.earnings_filter import EarningsFilter

    audit = tmp_path / "audit.jsonl"
    submit_calls: list = []

    def submit(intents):
        submit_calls.extend(intents)
        return [{"intent_id": i.order_ref, "action": "filled"} for i in intents]

    summary = run_live_incubation(
        setup_records=[_setup()],
        gate_status_by_variant={"smc_breaker_btc": "green"},
        risk_limits=RiskLimits(),
        account_state=_healthy_state(),
        execution_cfg=IBKRExecutionConfig(paper_mode=True),
        audit_path=audit,
        phase="paper",
        submit_fn=submit,
        now=_FROZEN_NOW,
        earnings_filter=EarningsFilter(events_jsonl=tmp_path / "missing.jsonl"),
    )

    assert summary["intents_submitted"] == 1
    assert summary["intents_earnings_blocked"] == 0
    assert len(submit_calls) == 1
