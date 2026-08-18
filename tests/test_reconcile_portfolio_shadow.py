from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from governance.portfolio_contract import (
    PORTFOLIO_SNAPSHOT_SCHEMA_VERSION,
    PortfolioSnapshotV1,
    PositionSnapshot,
)
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


def _write_snapshot(path: Path, *, quantity: float, captured_at: datetime) -> None:
    snapshot = PortfolioSnapshotV1.build(
        captured_at=captured_at,
        account="DU123",
        base_currency="USD",
        equity=100_000.0,
        available_funds=50_000.0,
        positions=(
            PositionSnapshot(
                symbol="AAPL",
                account="DU123",
                quantity=quantity,
                avg_cost=190.0,
                market_price=200.0,
                stop_price=195.0,
                sector="Technology",
                strategy_families=("OB",),
            ),
        ),
        working_orders=(),
        source="test",
        complete=True,
    )
    path.write_text(json.dumps(snapshot.to_dict()), encoding="utf-8")


def _aapl_fill(execution_id: str, quantity: float) -> dict:
    # Nicht `_fill`: das 3-Parameter-Pendant von Sweep K8 weiter oben würde
    # sonst beim Modul-Import verschattet und sein Test bräche mit TypeError.
    return {
        "execution_id": execution_id,
        "symbol": "AAPL",
        "account": "DU123",
        "side": "BUY",
        "quantity": quantity,
        "price": 200.0,
    }


def test_repeated_fills_flags_reconcile_orb_and_commercial_as_one_delta(
    tmp_path: Path,
) -> None:
    """The session's position delta is caused by ALL fills files together.

    2026-08-18 (Doppelgaenger-Sweep E5): the reconcile driver computed a
    separate commercial fills file and then never handed it to the portfolio
    reconciliation — a commercial fill surfaced as an unexplained position
    delta. ``--fills`` is repeatable now; this test proves the merge is what
    explains the delta (the ORB file alone must NOT reconcile).
    """
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    _write_snapshot(before, quantity=100, captured_at=datetime(2026, 8, 18, 13, 25, tzinfo=UTC))
    _write_snapshot(after, quantity=130, captured_at=datetime(2026, 8, 18, 21, 5, tzinfo=UTC))
    orb_fills = tmp_path / "fills_orb.json"
    orb_fills.write_text(json.dumps([_aapl_fill("exec-orb-1", 10)]), encoding="utf-8")
    commercial_fills = tmp_path / "fills_commercial.json"
    commercial_fills.write_text(json.dumps([_aapl_fill("exec-com-1", 20)]), encoding="utf-8")

    def run(*fills: Path) -> dict:
        output = tmp_path / "report.json"
        args = ["--before", str(before), "--after", str(after), "--output", str(output)]
        for f in fills:
            args += ["--fills", str(f)]
        main(args)
        return json.loads(output.read_text(encoding="utf-8"))

    merged = run(orb_fills, commercial_fills)
    assert merged["fill_count"] == 2
    assert merged["reconciled"] is True, merged

    orb_only = run(orb_fills)
    assert orb_only["reconciled"] is False, (
        "the ORB fills alone explained the delta — this fixture no longer "
        "proves the commercial merge matters; adjust the quantities."
    )
