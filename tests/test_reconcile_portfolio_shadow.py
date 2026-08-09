from __future__ import annotations

from scripts.reconcile_portfolio_shadow import monitoring_report


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
