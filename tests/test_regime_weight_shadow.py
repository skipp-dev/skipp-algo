"""Exact §15 shadow runs the complete scorer and never changes live rows."""
from __future__ import annotations

import pytest

from open_prep.regime_shadow import attach_exact_regime_shadow, build_exact_shadow_quotes
from open_prep.scorer import DEFAULT_WEIGHTS, filter_candidate, score_candidate
from open_prep.technical_analysis import detect_symbol_regime


def _quote(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "symbol": "TEST",
        "price": 20.0,
        "previousClose": 19.0,
        "gap_pct": 5.0,
        "gap_available": True,
        "volume": 5_000_000,
        "avgVolume": 1_000_000,
        "atr": 1.0,
        "momentum_z_score": 1.5,
        "ext_hours_score": 0.8,
    }
    row.update(overrides)
    return row


def test_scorer_regime_fallback_defaults_resolve_to_neutral() -> None:
    assert detect_symbol_regime(adx=15.0, bb_width_pct=3.0) == "NEUTRAL"


def test_shadow_quote_exposes_only_adx_bb_and_keeps_ewma_neutral() -> None:
    quote = _quote(
        _shadow_adx=30.0,
        _shadow_bb_width_pct=5.0,
        ewma_score_shadow=0.9,
        daily_bars=[{"close": 1.0}] * 50,
    )
    shadow_quotes, technical = build_exact_shadow_quotes([quote])
    assert shadow_quotes[0]["adx"] == 30.0
    assert shadow_quotes[0]["bb_width_pct"] == 5.0
    assert "daily_bars" not in shadow_quotes[0]
    assert technical["TEST"]["ewma_score_shadow"] == 0.9


def test_exact_shadow_delta_matches_a_complete_second_scorer_pass() -> None:
    base_quote = _quote()
    shadow_quote = _quote(adx=30.0, bb_width_pct=5.0)
    baseline = score_candidate(filter_candidate(base_quote, 0.2), 0.2, dict(DEFAULT_WEIGHTS))
    shadow = score_candidate(filter_candidate(shadow_quote, 0.2), 0.2, dict(DEFAULT_WEIGHTS))
    expected_delta = round(shadow["score"] - baseline["score"], 6)

    summary = attach_exact_regime_shadow(
        [baseline],
        [shadow],
        {
            "TEST": {
                "adx": 30.0,
                "bb_width_pct": 5.0,
                "ewma_score_shadow": 0.6,
                "technical_source": "atr_eod_candles",
                "technical_complete": True,
            },
        },
    )

    evidence = baseline["regime_weight_shadow"]
    assert evidence["exact_second_scorer_pass"] is True
    assert evidence["measured_regime"] == "TRENDING"
    assert evidence["score_delta"] == pytest.approx(expected_delta)
    assert evidence["score_delta"] == pytest.approx(0.0717)
    assert baseline["ewma_score_shadow"] == 0.6
    assert summary["exact_rows"] == 1
    assert summary["live_ranking_changed"] is False
    assert summary["comparisons"] == [evidence]


def test_exact_shadow_records_rank_movement_from_full_universe() -> None:
    baseline = [
        {"symbol": "A", "score": 10.0, "symbol_regime": "NEUTRAL"},
        {"symbol": "B", "score": 9.0, "symbol_regime": "NEUTRAL"},
    ]
    shadow = [
        {"symbol": "B", "score": 11.0, "symbol_regime": "TRENDING"},
        {"symbol": "A", "score": 10.0, "symbol_regime": "NEUTRAL"},
    ]
    technical = {
        symbol: {
            "adx": 30.0,
            "bb_width_pct": 5.0,
            "technical_source": "atr_eod_candles",
            "technical_complete": True,
        }
        for symbol in ("A", "B")
    }
    summary = attach_exact_regime_shadow(baseline, shadow, technical)
    assert baseline[0]["regime_weight_shadow"]["rank_delta"] == -1
    assert baseline[1]["regime_weight_shadow"]["rank_delta"] == 1
    assert summary["rank_changed_rows"] == 2


def test_missing_measured_pair_is_unresolved_not_neutral_evidence() -> None:
    baseline = [{"symbol": "A", "score": 10.0, "symbol_regime": "NEUTRAL"}]
    shadow = [{"symbol": "A", "score": 10.0, "symbol_regime": "NEUTRAL"}]
    summary = attach_exact_regime_shadow(
        baseline,
        shadow,
        {
            "A": {
                "adx": None,
                "bb_width_pct": None,
                "technical_source": "atr_eod_candles",
                "technical_complete": False,
            },
        },
    )
    evidence = baseline[0]["regime_weight_shadow"]
    assert evidence["exact_second_scorer_pass"] is False
    assert evidence["score_delta"] is None
    assert summary["unresolved_rows"] == 1
