"""Tests for ``scripts/smoke_smc_to_ibkr_adapter.py`` (C13/T1.2)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from scripts import smoke_smc_to_ibkr_adapter as mod
from scripts.smc_to_ibkr_adapter import (
    IBKRExecutionConfig,
    build_ibkr_intents_from_smc_setups,
)

# ---------------------------------------------------------------------------
# Frozen risk-limits loader
# ---------------------------------------------------------------------------


def _write_limits(tmp_path: Path, **overrides: object) -> Path:
    payload = {
        "max_open_positions": 5,
        "max_gross_exposure_pct": 200.0,
        "flatten_on_breach": True,
        "manual_halt": False,
        "frozen_at": "2026-04-28",
    }
    payload.update(overrides)
    p = tmp_path / "limits.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_risk_limits_loader_round_trips() -> None:
    limits = mod.RiskLimitsSnapshot.load(mod.DEFAULT_RISK_LIMITS_PATH)
    assert limits.max_open_positions >= 1
    assert limits.max_gross_exposure_pct > 0
    assert limits.frozen_at == "2026-04-28"


# ---------------------------------------------------------------------------
# Synthetic setups
# ---------------------------------------------------------------------------


def test_synthesise_setups_covers_two_families() -> None:
    setups = mod.synthesise_setups(trade_date=date(2026, 4, 28))
    families = {s["level_tag"].split("_", 1)[0] for s in setups}
    assert {"BOS", "OB"}.issubset(families)
    for s in setups:
        assert s["entry"] > 0
        assert s["stop_loss"] != s["entry"]
        assert s["quantity"] >= 1


# ---------------------------------------------------------------------------
# Risk-limit gate
# ---------------------------------------------------------------------------


def _make_intents(setups: list[dict[str, object]]) -> list[object]:
    cfg = IBKRExecutionConfig(host="127.0.0.1", paper_mode=True, client_id=71)
    return build_ibkr_intents_from_smc_setups(setups, cfg, size_scale=1.0)


def test_check_intents_passes_within_limits(tmp_path: Path) -> None:
    limits = mod.RiskLimitsSnapshot.load(_write_limits(tmp_path))
    intents = _make_intents(mod.synthesise_setups())
    res = mod.check_intents_against_limits(intents, limits, account_equity_usd=10_000.0)
    assert res.ok
    assert res.rejections == ()
    assert res.open_positions == len(intents)


def test_check_intents_rejects_when_open_positions_exceeds(
    tmp_path: Path,
) -> None:
    limits = mod.RiskLimitsSnapshot.load(_write_limits(tmp_path, max_open_positions=1))
    intents = _make_intents(mod.synthesise_setups())
    res = mod.check_intents_against_limits(intents, limits, account_equity_usd=1_000_000.0)
    assert not res.ok
    assert any("max_open_positions" in r for r in res.rejections)


def test_check_intents_rejects_when_gross_exposure_exceeds(
    tmp_path: Path,
) -> None:
    limits = mod.RiskLimitsSnapshot.load(_write_limits(tmp_path, max_gross_exposure_pct=1.0))
    intents = _make_intents(mod.synthesise_setups())
    res = mod.check_intents_against_limits(intents, limits, account_equity_usd=10_000.0)
    assert not res.ok
    assert any("gross_exposure_pct" in r for r in res.rejections)


def test_check_intents_manual_halt_short_circuits(tmp_path: Path) -> None:
    limits = mod.RiskLimitsSnapshot.load(_write_limits(tmp_path, manual_halt=True))
    intents = _make_intents(mod.synthesise_setups())
    res = mod.check_intents_against_limits(intents, limits, account_equity_usd=10_000.0)
    assert not res.ok
    assert any("manual_halt" in r for r in res.rejections)


def test_check_intents_rejects_zero_equity(tmp_path: Path) -> None:
    limits = mod.RiskLimitsSnapshot.load(_write_limits(tmp_path))
    intents = _make_intents(mod.synthesise_setups())
    with pytest.raises(ValueError, match="account_equity_usd"):
        mod.check_intents_against_limits(intents, limits, account_equity_usd=0.0)


# ---------------------------------------------------------------------------
# Mock-mode runner
# ---------------------------------------------------------------------------


def test_run_mock_writes_audit_and_passes(tmp_path: Path) -> None:
    audit = tmp_path / "smoke.jsonl"
    limits = mod.RiskLimitsSnapshot.load(_write_limits(tmp_path))
    res = mod.run_mock(
        setups=mod.synthesise_setups(),
        risk_limits=limits,
        account_equity_usd=10_000.0,
        size_scale=0.10,
        audit_path=audit,
    )
    assert res["mode"] == "mock"
    assert res["risk_ok"] is True
    assert res["intent_count"] >= 1
    rows = [json.loads(line) for line in audit.read_text().splitlines() if line]
    assert len(rows) == res["intent_count"]
    for row in rows:
        assert row["mode"] == "mock"
        assert row["risk_ok"] is True
        assert "intent" in row and row["intent"]["symbol"] in {"AAPL", "MSFT"}


def test_run_mock_records_rejections_when_limits_breached(
    tmp_path: Path,
) -> None:
    audit = tmp_path / "smoke.jsonl"
    limits = mod.RiskLimitsSnapshot.load(_write_limits(tmp_path, max_open_positions=0))
    res = mod.run_mock(
        setups=mod.synthesise_setups(),
        risk_limits=limits,
        account_equity_usd=10_000.0,
        size_scale=0.10,
        audit_path=audit,
    )
    assert res["risk_ok"] is False
    assert any("max_open_positions" in r for r in res["risk_rejections"])
    rows = [json.loads(line) for line in audit.read_text().splitlines() if line]
    assert all(row["risk_ok"] is False for row in rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_mock_exit_zero_on_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    limits_path = _write_limits(tmp_path)
    audit = tmp_path / "smoke.jsonl"
    rc = mod.main(
        [
            "--mode",
            "mock",
            "--risk-limits",
            str(limits_path),
            "--audit-path",
            str(audit),
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "mock"
    assert payload["risk_ok"] is True


def test_cli_mock_exit_two_on_breach(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    limits_path = _write_limits(tmp_path, manual_halt=True)
    rc = mod.main(
        [
            "--mode",
            "mock",
            "--risk-limits",
            str(limits_path),
            "--audit-path",
            str(tmp_path / "smoke.jsonl"),
        ]
    )
    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["risk_ok"] is False
