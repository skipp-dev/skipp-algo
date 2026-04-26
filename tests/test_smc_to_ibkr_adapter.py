"""Tests for ``scripts.smc_to_ibkr_adapter`` (C8/T1)."""

from __future__ import annotations

from datetime import date

import pytest

from scripts.smc_to_ibkr_adapter import (
    LIVE_TRADING_PORT,
    PAPER_TRADING_PORT,
    PHASE_B_RECOMMENDED_SIZE_SCALE,
    IBKRExecutionConfig,
    build_ibkr_intents_from_smc_setups,
)


def _setup(**overrides) -> dict:
    base = {
        "symbol": "BTC",
        "entry": 102.34,
        "stop_loss": 100.50,
        "take_profit": 105.20,
        "quantity": 100,
        "trade_date": "2026-04-26",
    }
    base.update(overrides)
    return base


def test_paper_mode_resolves_to_port_7497() -> None:
    cfg = IBKRExecutionConfig(paper_mode=True)
    assert cfg.port == PAPER_TRADING_PORT == 7497


def test_live_mode_resolves_to_port_7496() -> None:
    cfg = IBKRExecutionConfig(paper_mode=False)
    assert cfg.port == LIVE_TRADING_PORT == 7496


def test_builds_one_intent_per_setup_record_in_order() -> None:
    cfg = IBKRExecutionConfig()
    intents = build_ibkr_intents_from_smc_setups(
        [_setup(symbol="BTC"), _setup(symbol="ETH"), _setup(symbol="SOL")],
        cfg,
    )
    assert [i.symbol for i in intents] == ["BTC", "ETH", "SOL"]


def test_intent_carries_smc_levels_through_unchanged() -> None:
    cfg = IBKRExecutionConfig()
    [intent] = build_ibkr_intents_from_smc_setups([_setup()], cfg)
    assert intent.entry_limit == pytest.approx(102.34)
    assert intent.stop_loss == pytest.approx(100.50)
    assert intent.take_profit == pytest.approx(105.20)
    assert intent.trade_date == date(2026, 4, 26)


def test_size_scale_zero_point_one_reduces_quantity_to_ten_percent() -> None:
    cfg = IBKRExecutionConfig()
    [intent] = build_ibkr_intents_from_smc_setups(
        [_setup(quantity=100)],
        cfg,
        size_scale=PHASE_B_RECOMMENDED_SIZE_SCALE,
    )
    assert intent.quantity == 10


def test_size_scale_floors_at_one_share() -> None:
    cfg = IBKRExecutionConfig()
    # 5 shares × 0.10 = 0.5 → must round up to 1, never 0.
    [intent] = build_ibkr_intents_from_smc_setups(
        [_setup(quantity=5)], cfg, size_scale=0.10
    )
    assert intent.quantity == 1


def test_size_scale_outside_unit_interval_is_rejected() -> None:
    cfg = IBKRExecutionConfig()
    with pytest.raises(ValueError, match="size_scale"):
        build_ibkr_intents_from_smc_setups([_setup()], cfg, size_scale=1.5)
    with pytest.raises(ValueError, match="size_scale"):
        build_ibkr_intents_from_smc_setups([_setup()], cfg, size_scale=0.0)


def test_zero_risk_order_is_rejected() -> None:
    cfg = IBKRExecutionConfig()
    with pytest.raises(ValueError, match="stop_loss must differ from entry"):
        build_ibkr_intents_from_smc_setups(
            [_setup(stop_loss=102.34)], cfg
        )


def test_order_ref_records_resolved_port() -> None:
    paper_cfg = IBKRExecutionConfig(paper_mode=True)
    [paper] = build_ibkr_intents_from_smc_setups([_setup()], paper_cfg)
    assert "port7497" in paper.order_ref

    live_cfg = IBKRExecutionConfig(paper_mode=False)
    [live] = build_ibkr_intents_from_smc_setups([_setup()], live_cfg)
    assert "port7496" in live.order_ref


def test_explicit_order_ref_is_preserved() -> None:
    cfg = IBKRExecutionConfig()
    [intent] = build_ibkr_intents_from_smc_setups(
        [_setup(order_ref="custom-tag-42")], cfg
    )
    assert intent.order_ref == "custom-tag-42"


def test_empty_input_returns_empty_list() -> None:
    cfg = IBKRExecutionConfig()
    assert build_ibkr_intents_from_smc_setups([], cfg) == []


def test_missing_required_field_raises() -> None:
    cfg = IBKRExecutionConfig()
    with pytest.raises(ValueError, match="missing required field 'symbol'"):
        build_ibkr_intents_from_smc_setups([_setup(symbol=None)], cfg)
    with pytest.raises(ValueError, match="missing required field 'entry'"):
        build_ibkr_intents_from_smc_setups([_setup(entry=None)], cfg)


def test_trade_date_accepts_iso_string_and_date() -> None:
    cfg = IBKRExecutionConfig()
    [a] = build_ibkr_intents_from_smc_setups(
        [_setup(trade_date="2026-04-26")], cfg
    )
    [b] = build_ibkr_intents_from_smc_setups(
        [_setup(trade_date=date(2026, 4, 26))], cfg
    )
    assert a.trade_date == b.trade_date == date(2026, 4, 26)
