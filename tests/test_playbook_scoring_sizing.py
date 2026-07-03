"""Meaningful coverage for open_prep.playbook scoring + position sizing.

Audit PHASE-1 HIGH: the only prior direct test asserted membership in the set
of all four playbooks (tests/test_open_prep.py) and could never fail. These
tests pin the concrete playbook choice per candidate matrix plus the exact
``size_adjustment`` / ``max_loss_pct`` per execution quality.

Inputs are built relative to the live threshold constants so the tests survive
a deliberate threshold recalibration (they assert behaviour, not magic numbers).
"""

from __future__ import annotations

from datetime import UTC, datetime

from open_prep import playbook as pb

# ── _max_loss_for_playbook: exact risk table ────────────────────────────────

def test_max_loss_base_values_per_playbook_good_execution() -> None:
    assert pb._max_loss_for_playbook(pb.PLAYBOOK_GAP_AND_GO, "GOOD") == 0.50
    assert pb._max_loss_for_playbook(pb.PLAYBOOK_GAP_FADE, "GOOD") == 0.25
    assert pb._max_loss_for_playbook(pb.PLAYBOOK_POST_NEWS_DRIFT, "GOOD") == 0.75
    assert pb._max_loss_for_playbook(pb.PLAYBOOK_NO_TRADE, "GOOD") == 0.0


def test_max_loss_caution_halves_base() -> None:
    assert pb._max_loss_for_playbook(pb.PLAYBOOK_GAP_AND_GO, "CAUTION") == 0.25
    assert pb._max_loss_for_playbook(pb.PLAYBOOK_POST_NEWS_DRIFT, "CAUTION") == 0.38


def test_max_loss_poor_is_always_zero() -> None:
    for book in (
        pb.PLAYBOOK_GAP_AND_GO,
        pb.PLAYBOOK_GAP_FADE,
        pb.PLAYBOOK_POST_NEWS_DRIFT,
        pb.PLAYBOOK_NO_TRADE,
    ):
        assert pb._max_loss_for_playbook(book, "POOR") == 0.0


# ── _execution_quality: quality label + size_adjustment ─────────────────────

def test_execution_quality_good_full_size() -> None:
    # Tight spread, deep liquidity → no issues → GOOD, full size.
    quality, size = pb._execution_quality(
        spread_bps=pb._CAUTION_SPREAD_BPS - 1.0,
        avg_volume=pb._MIN_AVERAGE_VOLUME_CAUTION * 20,
        price=100.0,
    )
    assert quality == "GOOD"
    assert size == 1.0


def test_execution_quality_single_caution_issue_half_size() -> None:
    # One issue: spread between caution and hard-max, otherwise deep liquidity.
    quality, size = pb._execution_quality(
        spread_bps=(pb._CAUTION_SPREAD_BPS + pb._MAX_SPREAD_BPS_FOR_TRADE) / 2.0,
        avg_volume=pb._MIN_AVERAGE_VOLUME_CAUTION * 20,
        price=100.0,
    )
    assert quality == "CAUTION"
    assert size == 0.5


def test_execution_quality_poor_skips_trade() -> None:
    # Wide spread (2) + tiny avg volume (2) → issues >= 3 → POOR, size 0.
    quality, size = pb._execution_quality(
        spread_bps=pb._MAX_SPREAD_BPS_FOR_TRADE + 50.0,
        avg_volume=pb._MIN_AVERAGE_VOLUME_POOR - 1.0,
        price=1.0,
    )
    assert quality == "POOR"
    assert size == 0.0


# ── _no_trade_zone branches ─────────────────────────────────────────────────

def test_no_trade_zone_breaking_news_no_reclaim() -> None:
    is_ntz, reason = pb._no_trade_zone(
        regime="NEUTRAL",
        gap_pct=5.0,
        recency_bucket=pb.RECENCY_ULTRA_FRESH,
        event_class=pb.EVENT_UNSCHEDULED,
        spread_bps=20.0,
        is_halt_risk=False,
        premarket_stale=False,
        ext_hours_score=0.1,
    )
    assert is_ntz is True
    assert "breaking_news_no_reclaim" in reason


def test_no_trade_zone_illiquid_stale_premarket() -> None:
    is_ntz, reason = pb._no_trade_zone(
        regime="NEUTRAL",
        gap_pct=1.0,
        recency_bucket=pb.RECENCY_WARM,
        event_class=pb.EVENT_SCHEDULED,
        spread_bps=250.0,
        is_halt_risk=False,
        premarket_stale=True,
        ext_hours_score=1.0,
    )
    assert is_ntz is True
    assert "illiquid_stale_premarket" in reason


def test_no_trade_zone_extreme_gap_halt_risk() -> None:
    is_ntz, reason = pb._no_trade_zone(
        regime="NEUTRAL",
        gap_pct=20.0,
        recency_bucket=pb.RECENCY_WARM,
        event_class=pb.EVENT_SCHEDULED,
        spread_bps=20.0,
        is_halt_risk=True,
        premarket_stale=False,
        ext_hours_score=1.0,
    )
    assert is_ntz is True
    assert "extreme_gap_halt_risk" in reason


def test_no_trade_zone_clean_candidate_is_tradeable() -> None:
    is_ntz, reason = pb._no_trade_zone(
        regime="RISK_ON",
        gap_pct=3.0,
        recency_bucket=pb.RECENCY_WARM,
        event_class=pb.EVENT_SCHEDULED,
        spread_bps=20.0,
        is_halt_risk=False,
        premarket_stale=False,
        ext_hours_score=2.0,
    )
    assert is_ntz is False
    assert reason == ""


# ── assign_playbook end-to-end: concrete choice, not membership ─────────────

def _strong_gap_go_candidate() -> dict:
    return {
        "symbol": "AAPL",
        "gap_pct": 4.0,
        "price": 180.0,
        "volume": 3_000_000.0,
        "avg_volume": 1_000_000.0,  # rvol = 3.0
        "ext_hours_score": 2.0,
        "premarket_spread_bps": 5.0,
        "premarket_stale": False,
    }


def test_assign_playbook_strong_gap_go_is_deterministic() -> None:
    result = pb.assign_playbook(
        _strong_gap_go_candidate(),
        regime="RISK_ON",
        sector_breadth=0.7,
        news_metrics_entry={},
        now_utc=datetime.now(UTC),
    )
    assert result.playbook == pb.PLAYBOOK_GAP_AND_GO
    assert result.execution_quality == "GOOD"
    assert result.size_adjustment == 1.0
    assert result.max_loss_pct == 0.50
    assert result.gap_go_score >= result.fade_score
    assert result.gap_go_score >= result.drift_score


def test_assign_playbook_poor_liquidity_forces_no_trade() -> None:
    candidate = _strong_gap_go_candidate()
    candidate["avg_volume"] = pb._MIN_AVERAGE_VOLUME_POOR - 1.0
    candidate["volume"] = candidate["avg_volume"] * 3.0
    candidate["price"] = 1.0
    candidate["premarket_spread_bps"] = pb._MAX_SPREAD_BPS_FOR_TRADE + 50.0
    result = pb.assign_playbook(
        candidate,
        regime="RISK_ON",
        sector_breadth=0.7,
        news_metrics_entry={},
        now_utc=datetime.now(UTC),
    )
    assert result.playbook == pb.PLAYBOOK_NO_TRADE
    assert result.execution_quality == "POOR"
    assert result.size_adjustment == 0.0
    assert result.max_loss_pct == 0.0
