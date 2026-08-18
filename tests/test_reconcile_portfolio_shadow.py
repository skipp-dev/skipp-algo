from __future__ import annotations

import json
from pathlib import Path

from governance.portfolio_contract import PORTFOLIO_SNAPSHOT_SCHEMA_VERSION
from scripts.reconcile_portfolio_shadow import main, monitoring_report


def _snapshot(snapshot_id: str, positions: list[dict]) -> dict:
    return {
        "schema_version": PORTFOLIO_SNAPSHOT_SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "captured_at": "2026-08-18T13:00:00+00:00",
        "account": "DU1",
        "base_currency": "USD",
        "equity": 100_000.0,
        "available_funds": 50_000.0,
        "positions": positions,
        "complete": True,
    }


def _fill(execution_id: str, symbol: str, quantity: float) -> dict:
    return {
        "execution_id": execution_id,
        "symbol": symbol,
        "account": "DU1",
        "side": "BUY",
        "quantity": quantity,
        "price": 100.0,
    }


def test_commercial_fills_reach_the_same_reconciliation(tmp_path: Path) -> None:
    """2026-08-18 (Verdrahtungs-Sweep K8): die Commercial-Lane schreibt ihre
    Fills in eine SEPARATE Datei (portfolio_fills_commercial_<DATE>.json),
    die nie einen Leser hatte — nach dem Flip sähe die Abstimmung
    Positionsdeltas ohne die erklärenden Fills und meldete falsch rot.
    --fills ist jetzt append-fähig; beide Dateien zusammen stimmen ab,
    eine allein bleibt ehrlich unversöhnt (rc=2)."""
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    before.write_text(json.dumps(_snapshot("s-before", [])), encoding="utf-8")
    after.write_text(
        json.dumps(
            _snapshot(
                "s-after",
                [
                    {"symbol": "AAPL", "account": "DU1", "quantity": 5.0, "avg_cost": 100.0, "market_price": 100.0},
                    {"symbol": "MSFT", "account": "DU1", "quantity": 2.0, "avg_cost": 100.0, "market_price": 100.0},
                ],
            )
        ),
        encoding="utf-8",
    )
    phase_a = tmp_path / "fills_phase_a.json"
    commercial = tmp_path / "fills_commercial.json"
    phase_a.write_text(json.dumps([_fill("e1", "AAPL", 5.0)]), encoding="utf-8")
    commercial.write_text(json.dumps([_fill("e2", "MSFT", 2.0)]), encoding="utf-8")
    out = tmp_path / "report.json"

    rc_both = main(
        [
            "--before", str(before), "--after", str(after),
            "--fills", str(phase_a), "--fills", str(commercial),
            "--output", str(out),
        ]
    )
    assert rc_both == 0
    assert json.loads(out.read_text(encoding="utf-8"))["reconciled"] is True

    rc_single = main(
        [
            "--before", str(before), "--after", str(after),
            "--fills", str(phase_a),
            "--output", str(out),
        ]
    )
    assert rc_single == 2
    assert json.loads(out.read_text(encoding="utf-8"))["reconciled"] is False


def test_monitoring_report_omits_account_positions_and_snapshot_ids() -> None:
    report = {
        "schema_version": "1.0",
        "before_snapshot_id": "secret-before",
        "after_snapshot_id": "secret-after",
        "before_captured_at": "2026-08-08T13:28:00+00:00",
        "after_captured_at": "2026-08-08T21:05:00+00:00",
        "account": "DU123",
        "fill_count": 2,
        "duplicate_fill_ids": [],
        "symbols": [{"symbol": "AAPL"}],
        "max_abs_quantity_delta": 0.0,
        "reconciled": True,
    }

    result = monitoring_report(report)

    assert result["reconciled"] is True
    assert result["duplicate_fill_count"] == 0
    assert "account" not in result
    assert "symbols" not in result
    assert "before_snapshot_id" not in result
