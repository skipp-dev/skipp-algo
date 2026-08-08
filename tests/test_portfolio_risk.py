from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from governance.portfolio_contract import (
    PortfolioIntent,
    PortfolioRiskContextV1,
    PortfolioSnapshotV1,
    Side,
)
from governance.portfolio_risk import (
    PortfolioRiskLimitsV1,
    PortfolioRiskMode,
    PortfolioRiskVerdict,
    evaluate_portfolio_risk,
)

NOW = datetime(2026, 8, 8, 14, 0, tzinfo=UTC)


def _snapshot(*, captured_at: datetime = NOW, complete: bool = True) -> PortfolioSnapshotV1:
    return PortfolioSnapshotV1.build(
        captured_at=captured_at,
        account="DU1",
        base_currency="USD",
        equity=10_000,
        available_funds=10_000,
        source="test",
        complete=complete,
        missing_fields=(() if complete else ("equity",)),
    )


def _intent(*, quantity: float = 10) -> PortfolioIntent:
    return PortfolioIntent("intent", "AAPL", "DU1", Side.BUY, quantity, 100, 95)


def test_shadow_reports_reject_but_permits_submission() -> None:
    limits = PortfolioRiskLimitsV1(
        mode=PortfolioRiskMode.SHADOW,
        max_single_position_pct=5,
    )
    decision = evaluate_portfolio_risk(_snapshot(), (_intent(quantity=10),), limits, now=NOW)
    assert decision.verdict is PortfolioRiskVerdict.RESIZE
    assert decision.would_block is True
    assert decision.permits_submission is True
    assert decision.recommended_scale == pytest.approx(0.5)


def test_enforce_blocks_same_projected_breach() -> None:
    limits = PortfolioRiskLimitsV1(
        mode=PortfolioRiskMode.ENFORCE,
        max_single_position_pct=5,
    )
    decision = evaluate_portfolio_risk(_snapshot(), (_intent(quantity=10),), limits, now=NOW)
    assert decision.verdict is PortfolioRiskVerdict.RESIZE
    assert decision.permits_submission is False


@pytest.mark.parametrize(
    ("snapshot", "reason"),
    [
        (_snapshot(captured_at=NOW - timedelta(seconds=121)), "snapshot_stale"),
        (_snapshot(captured_at=NOW + timedelta(seconds=1)), "snapshot_from_future"),
        (_snapshot(complete=False), "snapshot_incomplete"),
    ],
)
def test_snapshot_quality_failures_cannot_be_resized(
    snapshot: PortfolioSnapshotV1,
    reason: str,
) -> None:
    decision = evaluate_portfolio_risk(snapshot, (_intent(),), PortfolioRiskLimitsV1(), now=NOW)
    assert reason in decision.reasons
    assert decision.verdict is PortfolioRiskVerdict.REJECT
    assert decision.recommended_scale is None


def test_config_loader_rejects_unknown_keys(tmp_path) -> None:
    payload = PortfolioRiskLimitsV1().to_dict()
    payload["max_gros_exposure_pct"] = 1
    path = tmp_path / "limits.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown"):
        PortfolioRiskLimitsV1.from_json(path)


def test_checked_in_limits_remain_shadow_and_correlation_caps_inactive() -> None:
    limits = PortfolioRiskLimitsV1.from_json("configs/portfolio_risk_limits.json")
    assert limits.mode is PortfolioRiskMode.SHADOW
    assert limits.max_sector_exposure_pct is None
    assert limits.max_correlated_cluster_exposure_pct is None


def test_sector_cap_requires_explicit_context() -> None:
    limits = replace(PortfolioRiskLimitsV1(), max_sector_exposure_pct=20.0)
    decision = evaluate_portfolio_risk(_snapshot(), (_intent(),), limits, now=NOW)
    assert "sector_context_incomplete" in decision.reasons
    assert decision.verdict is PortfolioRiskVerdict.REJECT


def test_enabled_context_cap_rejects_stale_context() -> None:
    limits = replace(PortfolioRiskLimitsV1(), max_sector_exposure_pct=100.0)
    context = PortfolioRiskContextV1(
        as_of=NOW - timedelta(days=5),
        sector_by_symbol={"AAPL": "Technology"},
        complete=True,
    )
    decision = evaluate_portfolio_risk(
        _snapshot(),
        (_intent(),),
        limits,
        now=NOW,
        context=context,
    )
    assert "context_stale" in decision.reasons


def test_short_or_offsetting_batch_never_gets_unsafe_linear_resize_advice() -> None:
    limits = replace(PortfolioRiskLimitsV1(), max_single_position_pct=5.0)
    sell = PortfolioIntent("sell", "AAPL", "DU1", Side.SELL, 10, 100, 105)
    decision = evaluate_portfolio_risk(_snapshot(), (sell,), limits, now=NOW)
    assert decision.verdict is PortfolioRiskVerdict.REJECT
    assert decision.recommended_scale is None
