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


def test_gap_down_candidate_never_gets_long_only_gap_and_go() -> None:
    # Regression: go_score can clear 0.30 without any gap contribution
    # (rvol 0.25 + RISK_ON 0.15 + catalyst 0.15), so before the gap>0 gate a
    # -5% gapper could receive the long-only ORH-breakout playbook.
    candidate = _strong_gap_go_candidate()
    candidate["gap_pct"] = -5.0
    result = pb.assign_playbook(
        candidate,
        regime="RISK_ON",
        sector_breadth=0.7,
        news_metrics_entry={},
        now_utc=datetime.now(UTC),
    )
    assert result.playbook != pb.PLAYBOOK_GAP_AND_GO


def test_zero_gap_candidate_never_gets_gap_fade() -> None:
    # The fade trigger branches on the gap SIGN; a zero-gap candidate fits
    # neither the short-the-gap-up nor the reclaim-from-gap-down text.
    candidate = _strong_gap_go_candidate()
    candidate["gap_pct"] = 0.0
    candidate["ext_hours_score"] = 0.1  # weak tape favors fade scoring
    candidate["volume"] = 1_000_000.0   # rvol = 1.0 (low)
    result = pb.assign_playbook(
        candidate,
        regime="RISK_OFF",
        sector_breadth=0.2,
        news_metrics_entry={},
        now_utc=datetime.now(UTC),
    )
    assert result.playbook not in (pb.PLAYBOOK_GAP_FADE, pb.PLAYBOOK_GAP_AND_GO)


def test_tier2_short_tokens_require_word_boundary() -> None:
    # "ft" must not substring-match inside other source names.
    swift = pb.classify_source_quality("Swift Media Newswire", "some headline")
    assert swift["source_tier"] != pb.SOURCE_TIER_2
    ft = pb.classify_source_quality("FT", "some headline")
    assert ft["source_tier"] == pb.SOURCE_TIER_2


# ── missing-rvol discipline in the fade score (scoring-path sibling of #3976) ─

def _fade_flip_shape(*, avg_volume: float, volume: float) -> dict:
    # A gap-DOWN whose |gap| is below the fade "overdone" line and whose tape is
    # above the fade weak-tape cutoff, so the ONLY lift to the 0.30 selection
    # line is the low-RVOL bonus. rvol is set purely by (volume, avg_volume),
    # which isolates the missing-baseline question.
    return {
        "symbol": "MISS",
        "gap_pct": -(pb._FADE_GAP_OVERDONE - 1.0),        # no overdone bonus
        "price": 50.0,
        "volume": volume,
        "avg_volume": avg_volume,
        "ext_hours_score": pb._FADE_MAX_EXT_SCORE + 0.1,  # above cutoff: no weak-tape bonus
        "premarket_spread_bps": None,                     # unknown spread -> exec CAUTION, not POOR
    }


def test_missing_volume_baseline_does_not_fabricate_a_fade_setup() -> None:
    # Store discipline in the SCORING path: the scorer emits rvol=0.0 when it has
    # no avg_volume baseline (has_rvol = rvol_ratio > 0.0). That is "no data",
    # not a genuine low RVOL — awarding the fade "low RVOL" bonus to it fabricates
    # a Gap Fade (a real trade card) on a symbol whose volume is unknown, flipping
    # NO_TRADE -> GAP_FADE. Missing baseline must not, by itself, cross the line.
    result = pb.assign_playbook(
        _fade_flip_shape(avg_volume=0.0, volume=10_000.0),  # rvol -> 0.0 (missing baseline)
        regime="RISK_ON",
        sector_breadth=0.3,
        news_metrics_entry={},
        now_utc=datetime.now(UTC),
    )
    assert result.playbook == pb.PLAYBOOK_NO_TRADE


def test_genuine_low_rvol_still_earns_the_fade_bonus() -> None:
    # Guard against over-correction: a MEASURED low RVOL (0.5x) is a real fade
    # signal and must keep the bonus — only the missing (0.0) baseline is denied.
    result = pb.assign_playbook(
        _fade_flip_shape(avg_volume=1_000_000.0, volume=500_000.0),  # rvol = 0.5 (measured low)
        regime="RISK_ON",
        sector_breadth=0.3,
        news_metrics_entry={},
        now_utc=datetime.now(UTC),
    )
    assert result.playbook == pb.PLAYBOOK_GAP_FADE


def test_sign_gated_gap_and_go_reason_names_the_gate_not_a_false_zero() -> None:
    # A gap-DOWN with a high Gap&Go score is blocked by the long-only sign-gate,
    # not because "no playbook scores above threshold". The operator line must
    # name the real block, not falsely claim nothing scored — the setup existed.
    candidate = _strong_gap_go_candidate()
    candidate["gap_pct"] = -6.0
    candidate["ext_hours_score"] = 0.9
    result = pb.assign_playbook(
        candidate,
        regime="RISK_ON",
        sector_breadth=0.7,
        news_metrics_entry={},
        now_utc=datetime.now(UTC),
    )
    assert result.playbook == pb.PLAYBOOK_NO_TRADE
    assert result.gap_go_score >= 0.30  # the setup DID score above threshold
    reason = result.playbook_reason.lower()
    assert "no playbook scores above threshold" not in reason
    assert "sign-gate" in reason
