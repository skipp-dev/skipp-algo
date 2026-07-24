"""TC1: a NO_TRADE candidate that also has a gap produced a self-contradictory
trade card — setup_type/note said "No Trade" while entry_trigger/invalidation
kept the gap-based default ("Break and hold above ORH" / "VWAP reclaim ...").

build_trade_cards excluded NO_TRADE from the playbook override, so the stale
gap default survived. The playbook engine already emits the correct no-trade
text; the card must use it.
"""
from __future__ import annotations

from open_prep.playbook import assign_playbook
from open_prep.trade_cards import build_trade_cards


def test_no_trade_card_uses_playbook_text_not_gap_default() -> None:
    # A sign-gated gap-down -> NO_TRADE, but gap_available + gap_pct<=-1 would
    # otherwise print the "VWAP reclaim and hold" default entry trigger.
    cand = {
        "symbol": "ZZZ", "gap_pct": -6.0, "price": 50.0,
        "volume": 3_000_000.0, "avg_volume": 1_000_000.0,
        "ext_hours_score": 0.9, "atr": 1.0,
    }
    pb = assign_playbook(cand, regime="RISK_ON", sector_breadth=0.7)
    assert pb.playbook == "NO_TRADE"

    row = {**cand, "gap_available": True, "score": 5.0, "playbook": pb.to_dict()}
    card = build_trade_cards([row], bias=0.2, top_n=5)[0]

    assert card["setup_type"] == "No Trade — Playbook"
    assert card["entry_trigger"] == pb.entry_trigger      # 'No trade: conditions do not meet ...'
    assert card["invalidation"] == pb.invalidation        # 'N/A — no trade selected.'
    # and definitely NOT the contradictory gap-based default
    assert "reclaim" not in card["entry_trigger"].lower()
    assert "opening range high" not in card["entry_trigger"].lower()


def test_non_no_trade_card_still_uses_its_playbook_trigger() -> None:
    # Unchanged behaviour: a real playbook's own entry_trigger still wins.
    row = {
        "symbol": "AAA", "score": 5.0, "gap_pct": 3.0, "gap_available": True,
        "price": 50.0, "avg_volume": 1_000_000, "volume": 3_000_000, "atr": 1.0,
        "playbook": {
            "playbook": "GAP_AND_GO", "playbook_reason": "x",
            "entry_trigger": "CUSTOM GAP GO TRIGGER", "invalidation": "CUSTOM INV",
        },
    }
    card = build_trade_cards([row], bias=0.2, top_n=5)[0]
    assert card["entry_trigger"] == "CUSTOM GAP GO TRIGGER"
    assert card["invalidation"] == "CUSTOM INV"


def test_card_without_playbook_keeps_gap_default() -> None:
    # No playbook attached -> the gap-based default is still used (unchanged).
    row = {
        "symbol": "BBB", "score": 5.0, "gap_pct": 3.0, "gap_available": True,
        "price": 50.0, "avg_volume": 1_000_000, "volume": 3_000_000, "atr": 1.0,
    }
    card = build_trade_cards([row], bias=0.2, top_n=5)[0]
    assert "opening range high" in card["entry_trigger"].lower()
