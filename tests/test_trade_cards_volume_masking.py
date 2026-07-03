from __future__ import annotations

from open_prep.trade_cards import build_trade_cards


def test_trade_cards_context_uses_precomputed_volume_ratio_when_present() -> None:
    ranked = [
        {
            "symbol": "AAPL",
            "score": 1.0,
            "price": 100.0,
            "gap_pct": 2.0,
            "gap_available": True,
            "volume_ratio": 2.37,
            "is_hvb": True,
            "avg_volume": 0.0,
            "volume": 0.0,
        }
    ]

    card = build_trade_cards(ranked_candidates=ranked, bias=0.1, top_n=1)[0]
    ctx = card["context"]

    assert ctx["volume_ratio"] == 2.37
    assert ctx["volume_ratio_masked"] is False
    assert ctx["is_hvb"] is True


def test_trade_cards_context_masks_volume_fields_without_valid_baseline() -> None:
    ranked = [
        {
            "symbol": "MSFT",
            "score": 1.0,
            "price": 100.0,
            "gap_pct": 1.5,
            "gap_available": True,
            "avg_volume": 0.0,
            "volume": 1_500_000.0,
        }
    ]

    card = build_trade_cards(ranked_candidates=ranked, bias=0.2, top_n=1)[0]
    ctx = card["context"]

    assert ctx["volume_ratio"] is None
    assert ctx["volume_ratio_masked"] is True
    assert ctx["is_hvb"] is False
