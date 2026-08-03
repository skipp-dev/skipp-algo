"""Tests for ``scripts/smoke_smc_to_ibkr_adapter.py`` (C13/T1.2)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import ClassVar

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
    assert rows, "no audit row was written — the per-row checks below would pass vacuously"
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
    assert rows, "a breached run must still be audited — an empty file would pass vacuously"
    assert all(row["risk_ok"] is False for row in rows)


# ---------------------------------------------------------------------------
# Live-mode runner (fake ib_async — no gateway required)
# ---------------------------------------------------------------------------
#
# S2's actual guarantee is BEHAVIORAL: every order the live smoke places must
# be non-marketable (a BUY limit far below the entry) so the ack/cancel
# round-trip can never fill. Until 2026-07-08 nothing exercised the live
# placement path — a sign flip (* 1.5) or a dropped multiplier would have
# sailed through CI and the smoke would quietly buy stock. These tests fake
# ib_async at the import seam and assert on the prices actually handed to
# placeOrder, NOT by re-computing the formula.


class _FakeOrderStatus:
    def __init__(self) -> None:
        self.status = "Submitted"


class _FakeTrade:
    def __init__(self, order: object) -> None:
        self.order = order
        self.orderStatus = _FakeOrderStatus()


class _FakeStock:
    def __init__(self, symbol: str, exchange: str, currency: str) -> None:
        self.symbol = symbol
        self.exchange = exchange
        self.currency = currency


class _FakeLimitOrder:
    def __init__(self, action: str, quantity: int, price: float, tif: str | None = None) -> None:
        self.action = action
        self.totalQuantity = quantity
        self.lmtPrice = price
        self.tif = tif
        self.orderId = 0
        self.orderRef = ""


class _FakeIB:
    instances: ClassVar[list[_FakeIB]] = []

    def __init__(self) -> None:
        self.placed: list[tuple[_FakeStock, _FakeLimitOrder]] = []
        self.cancelled: list[_FakeLimitOrder] = []
        self._trades: list[_FakeTrade] = []
        self.wrapper = type("W", (), {"accounts": ["DU1234567"]})()
        _FakeIB.instances.append(self)

    def connect(self, host: str, port: int, clientId: int, timeout: float) -> None:
        pass

    def sleep(self, seconds: float) -> None:
        pass

    def placeOrder(self, contract: _FakeStock, order: _FakeLimitOrder) -> _FakeTrade:
        order.orderId = len(self.placed) + 1
        self.placed.append((contract, order))
        trade = _FakeTrade(order)
        self._trades.append(trade)
        return trade

    def cancelOrder(self, order: _FakeLimitOrder) -> None:
        self.cancelled.append(order)
        for trade in self._trades:
            if trade.order is order:
                trade.orderStatus.status = "Cancelled"

    def reqAllOpenOrders(self) -> list[_FakeTrade]:
        return []

    def disconnect(self) -> None:
        pass


def _install_fake_ib_async(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    fake = types.ModuleType("ib_async")
    fake.IB = _FakeIB  # type: ignore[attr-defined]
    fake.LimitOrder = _FakeLimitOrder  # type: ignore[attr-defined]
    fake.Stock = _FakeStock  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ib_async", fake)
    _FakeIB.instances.clear()


def test_run_live_places_only_non_marketable_buys_and_cancels_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_ib_async(monkeypatch)
    audit = tmp_path / "smoke.jsonl"
    limits = mod.RiskLimitsSnapshot.load(_write_limits(tmp_path))
    setups = mod.synthesise_setups()
    res = mod.run_live(
        setups=setups,
        risk_limits=limits,
        account_equity_usd=10_000.0,
        size_scale=0.10,
        host="127.0.0.1",
        port=mod.DEFAULT_PAPER_PORT,
        client_id=71,
        timeout_seconds=0.1,
        audit_path=audit,
    )
    assert res["mode"] == "live"
    assert res["submitted"] is True and res["risk_ok"] is True
    assert res["clean"] is True
    assert res["leftover_open_orders"] == []

    (ib,) = _FakeIB.instances
    assert len(ib.placed) == res["intent_count"] >= 1

    # Compare against the same production intent builder run_live uses —
    # entry_limit is the marketable reference price per symbol/ref.
    cfg = IBKRExecutionConfig(host="127.0.0.1", paper_mode=True, client_id=71)
    intents = build_ibkr_intents_from_smc_setups(setups, cfg, size_scale=0.10)
    entry_by_ref = {f"{i.order_ref}-smoke": float(i.entry_limit) for i in intents}

    for contract, order in ib.placed:
        entry = entry_by_ref[str(order.orderRef)]
        # The S2 core guarantee: strictly below the entry with a wide margin
        # (catches a dropped/flipped multiplier), penny-quantised, >= 0.01.
        assert order.action == "BUY"
        assert 0.01 <= order.lmtPrice <= 0.6 * entry, (
            f"{contract.symbol}: smoke price {order.lmtPrice} is not safely "
            f"non-marketable vs entry {entry}"
        )
        assert order.lmtPrice == round(order.lmtPrice, 2), "price must be penny-quantised"
        assert str(order.orderRef).endswith("-smoke")

    # Every placed order must have been cancelled (none may rest working).
    assert {id(o) for o in ib.cancelled} == {id(o) for _, o in ib.placed}

    rows = [json.loads(line) for line in audit.read_text().splitlines() if line]
    assert rows, "no audit row was written — the terminal check below would pass vacuously"
    assert len(rows) == res["intent_count"]
    assert all(row["round_trip"]["terminal"] for row in rows)


def test_run_live_aborts_on_non_paper_accounts_before_placing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S5: a live account behind the paper port must abort BEFORE any order."""
    _install_fake_ib_async(monkeypatch)
    limits = mod.RiskLimitsSnapshot.load(_write_limits(tmp_path))

    real_init = _FakeIB.__init__

    def _live_accounts_init(self: _FakeIB) -> None:
        real_init(self)
        self.wrapper.accounts = ["U9999999"]  # no DU prefix -> live account

    monkeypatch.setattr(_FakeIB, "__init__", _live_accounts_init)
    with pytest.raises(SystemExit, match="DU"):
        mod.run_live(
            setups=mod.synthesise_setups(),
            risk_limits=limits,
            account_equity_usd=10_000.0,
            size_scale=0.10,
            host="127.0.0.1",
            port=mod.DEFAULT_PAPER_PORT,
            client_id=71,
            timeout_seconds=0.1,
        )
    (ib,) = _FakeIB.instances
    assert ib.placed == [], "S5 must abort before any order is placed"


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
