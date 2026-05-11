"""Invariant / property tests for the terminal state-machine layer.

Targets the per-item state derivation primitives that drive the dashboard
ranking and feed lifecycle. Each ``effective_*_state`` is a total function
that must (a) never raise on partial input, (b) return a value from a fixed
set, and (c) be idempotent when its own output is injected back into the
item. Each ``effective_*_score`` / ``_confidence`` must lie in ``[0, 1]``;
each ``_actionable`` / ``_active`` / ``_featured`` must return ``bool``.

Also covers:

- ``terminal_live_story_state.live_story_key`` — determinism, explicit
  ``story_key`` pass-through, time-bucket granularity.
- ``smc_core.event_ledger`` — round-trip write→read preserves required
  fields and ``ValueError`` is raised when ``predicted_prob`` is missing.

All randomisation uses a seeded ``random.Random`` so tests stay
deterministic with no new dependency on ``hypothesis``.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import pytest

import terminal_attention_state as attention_mod
import terminal_catalyst_state as catalyst_mod
import terminal_live_story_state as live_story_mod
import terminal_posture_state as posture_mod
import terminal_reaction_state as reaction_mod
import terminal_resolution_state as resolution_mod
from smc_core.event_ledger import read_event_ledger, write_event_ledger

# ---------------------------------------------------------------------------
# Documented state sets (verified against module constants)
# ---------------------------------------------------------------------------

REACTION_STATES = {"CONFIRMED", "WATCH", "IDLE", "FADE", "CONFLICTED"}
RESOLUTION_STATES = {"FOLLOW_THROUGH", "OPEN", "STALLED", "FAILED", "REVERSAL"}
POSTURE_STATES = {"LONG", "SHORT", "WATCH_LONG", "WATCH_SHORT", "NEUTRAL", "AVOID"}
ATTENTION_STATES = {"ALERT", "FOCUS", "MONITOR", "BACKGROUND", "SUPPRESS"}
CATALYST_SENTIMENTS = {"bullish", "bearish", "neutral"}

# Priority maps are read directly from the modules so the tests assert the
# *consistency* of state→priority lookup rather than pinning specific values.
REACTION_PRIORITY = reaction_mod._REACTION_PRIORITY  # type: ignore[attr-defined]
RESOLUTION_PRIORITY = resolution_mod._RESOLUTION_PRIORITY  # type: ignore[attr-defined]
POSTURE_PRIORITY = posture_mod._POSTURE_PRIORITY  # type: ignore[attr-defined]
ATTENTION_PRIORITY = attention_mod._ATTENTION_PRIORITY  # type: ignore[attr-defined]

_RNG_SEED = 0xC0FFEE
_N_SAMPLES = 60
_FIXED_NOW = 1_715_000_000.0  # 2024-05-06; arbitrary stable epoch


# ---------------------------------------------------------------------------
# Item generators (seeded)
# ---------------------------------------------------------------------------


def _random_item(rng: random.Random) -> dict[str, Any]:
    """Build a partially-populated item with a mix of fields the modules read."""
    return {
        "ticker": rng.choice(["AAPL", "TSLA", "NVDA", "AMD", "MSFT", "META"]),
        "catalyst_score": rng.uniform(0.0, 1.0),
        "news_score": rng.uniform(0.0, 1.0),
        "catalyst_direction": rng.choice(["BULLISH", "BEARISH", "NEUTRAL", "MIXED", ""]),
        "sentiment_label": rng.choice(["bullish", "bearish", "neutral", ""]),
        "is_actionable": rng.random() < 0.3,
        "age_minutes": rng.uniform(0.0, 5_000.0),
        "published_ts": _FIXED_NOW - rng.uniform(0.0, 86_400.0),
        "headline": rng.choice(
            ["Apple beats earnings", "Tesla recall", "NVDA AI surge", "Fed hike fears", ""]
        ),
        "reaction_score": rng.uniform(0.0, 1.0),
        "resolution_score": rng.uniform(0.0, 1.0),
        "posture_score": rng.uniform(0.0, 1.0),
        "posture_confidence": rng.uniform(0.0, 1.0),
        "attention_score": rng.uniform(0.0, 1.0),
        "attention_confidence": rng.uniform(0.0, 1.0),
    }


# ---------------------------------------------------------------------------
# Reaction state invariants
# ---------------------------------------------------------------------------


class TestReactionStateInvariants:
    def test_state_total_function(self) -> None:
        rng = random.Random(_RNG_SEED)
        # Empty dict must never raise and must return a documented value.
        assert reaction_mod.effective_reaction_state({}) in REACTION_STATES
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            assert reaction_mod.effective_reaction_state(item) in REACTION_STATES

    def test_priority_in_documented_range(self) -> None:
        rng = random.Random(_RNG_SEED + 1)
        assert reaction_mod.effective_reaction_priority({}) in set(REACTION_PRIORITY.values())
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            assert reaction_mod.effective_reaction_priority(item) in set(REACTION_PRIORITY.values())

    def test_priority_consistent_with_state(self) -> None:
        rng = random.Random(_RNG_SEED + 2)
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            state = reaction_mod.effective_reaction_state(item)
            assert reaction_mod.effective_reaction_priority(item) == REACTION_PRIORITY[state]

    def test_score_bounds(self) -> None:
        rng = random.Random(_RNG_SEED + 3)
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            score = reaction_mod.effective_reaction_score(item)
            assert isinstance(score, float)
            assert 0.0 <= score <= 1.0

    def test_actionable_is_bool(self) -> None:
        rng = random.Random(_RNG_SEED + 4)
        assert isinstance(reaction_mod.effective_reaction_actionable({}), bool)
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            assert isinstance(
                reaction_mod.effective_reaction_actionable(item, now=_FIXED_NOW), bool
            )

    def test_stored_state_passes_through(self) -> None:
        for state in REACTION_STATES:
            assert reaction_mod.effective_reaction_state({"reaction_state": state}) == state

    def test_idempotent_under_reinjection(self) -> None:
        rng = random.Random(_RNG_SEED + 5)
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            s1 = reaction_mod.effective_reaction_state(item)
            item2 = {**item, "reaction_state": s1}
            s2 = reaction_mod.effective_reaction_state(item2)
            assert s1 == s2


# ---------------------------------------------------------------------------
# Resolution state invariants
# ---------------------------------------------------------------------------


class TestResolutionStateInvariants:
    def test_state_total_function(self) -> None:
        rng = random.Random(_RNG_SEED + 10)
        assert resolution_mod.effective_resolution_state({}) in RESOLUTION_STATES
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            assert resolution_mod.effective_resolution_state(item) in RESOLUTION_STATES

    def test_priority_is_int(self) -> None:
        rng = random.Random(_RNG_SEED + 11)
        # Resolution priority falls back to reaction_priority, so the
        # universe of possible values is the union.
        valid = set(RESOLUTION_PRIORITY.values()) | set(REACTION_PRIORITY.values())
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            p = resolution_mod.effective_resolution_priority(item)
            assert isinstance(p, int)
            assert p in valid

    def test_score_bounds(self) -> None:
        rng = random.Random(_RNG_SEED + 12)
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            score = resolution_mod.effective_resolution_score(item)
            assert 0.0 <= score <= 1.0

    def test_actionable_is_bool(self) -> None:
        rng = random.Random(_RNG_SEED + 13)
        assert isinstance(resolution_mod.effective_resolution_actionable({}), bool)
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            assert isinstance(
                resolution_mod.effective_resolution_actionable(item, now=_FIXED_NOW), bool
            )

    def test_follow_through_is_actionable(self) -> None:
        # Documented contract: resolution_state == FOLLOW_THROUGH → actionable True.
        assert resolution_mod.effective_resolution_actionable(
            {"resolution_state": "FOLLOW_THROUGH"}
        ) is True

    def test_failed_state_is_not_actionable(self) -> None:
        # Documented contract: STALLED/FAILED/REVERSAL → not actionable.
        for state in ("STALLED", "FAILED", "REVERSAL"):
            assert resolution_mod.effective_resolution_actionable(
                {"resolution_state": state}
            ) is False

    def test_idempotent_under_reinjection(self) -> None:
        rng = random.Random(_RNG_SEED + 14)
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            s1 = resolution_mod.effective_resolution_state(item)
            item2 = {**item, "resolution_state": s1}
            s2 = resolution_mod.effective_resolution_state(item2)
            assert s1 == s2


# ---------------------------------------------------------------------------
# Posture state invariants
# ---------------------------------------------------------------------------


class TestPostureStateInvariants:
    def test_state_total_function(self) -> None:
        rng = random.Random(_RNG_SEED + 20)
        assert posture_mod.effective_posture_state({}, now=_FIXED_NOW) in POSTURE_STATES
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            assert posture_mod.effective_posture_state(item, now=_FIXED_NOW) in POSTURE_STATES

    def test_priority_consistent_with_state(self) -> None:
        rng = random.Random(_RNG_SEED + 21)
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            state = posture_mod.effective_posture_state(item, now=_FIXED_NOW)
            assert posture_mod.effective_posture_priority(item, now=_FIXED_NOW) == POSTURE_PRIORITY[state]

    def test_priority_long_dominates_watch_dominates_neutral_dominates_avoid(self) -> None:
        # Documented contract from _POSTURE_PRIORITY in source:
        # LONG outranks WATCH_LONG outranks NEUTRAL outranks AVOID.
        long_p = posture_mod.effective_posture_priority({"posture_state": "LONG"})
        watch_p = posture_mod.effective_posture_priority({"posture_state": "WATCH_LONG"})
        neutral_p = posture_mod.effective_posture_priority({"posture_state": "NEUTRAL"})
        avoid_p = posture_mod.effective_posture_priority({"posture_state": "AVOID"})
        assert long_p > watch_p > neutral_p > avoid_p

    def test_score_bounds(self) -> None:
        rng = random.Random(_RNG_SEED + 22)
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            assert 0.0 <= posture_mod.effective_posture_score(item) <= 1.0

    def test_confidence_bounds(self) -> None:
        rng = random.Random(_RNG_SEED + 23)
        assert 0.0 <= posture_mod.effective_posture_confidence({}, now=_FIXED_NOW) <= 1.0
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            c = posture_mod.effective_posture_confidence(item, now=_FIXED_NOW)
            assert 0.0 <= c <= 1.0

    def test_actionable_is_bool(self) -> None:
        rng = random.Random(_RNG_SEED + 24)
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            assert isinstance(
                posture_mod.effective_posture_actionable(item, now=_FIXED_NOW), bool
            )

    def test_idempotent_under_reinjection(self) -> None:
        rng = random.Random(_RNG_SEED + 25)
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            s1 = posture_mod.effective_posture_state(item, now=_FIXED_NOW)
            item2 = {**item, "posture_state": s1}
            s2 = posture_mod.effective_posture_state(item2, now=_FIXED_NOW)
            assert s1 == s2


# ---------------------------------------------------------------------------
# Attention state invariants
# ---------------------------------------------------------------------------


class TestAttentionStateInvariants:
    def test_state_total_function(self) -> None:
        rng = random.Random(_RNG_SEED + 30)
        assert attention_mod.effective_attention_state({}, now=_FIXED_NOW) in ATTENTION_STATES
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            assert attention_mod.effective_attention_state(item, now=_FIXED_NOW) in ATTENTION_STATES

    def test_priority_consistent_with_state(self) -> None:
        rng = random.Random(_RNG_SEED + 31)
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            state = attention_mod.effective_attention_state(item, now=_FIXED_NOW)
            assert attention_mod.effective_attention_priority(item, now=_FIXED_NOW) == ATTENTION_PRIORITY[state]

    def test_priority_ordering(self) -> None:
        # ALERT(4) > FOCUS(3) > MONITOR(2) > BACKGROUND(1) > SUPPRESS(0).
        priorities = [
            attention_mod.effective_attention_priority({"attention_state": s})
            for s in ("ALERT", "FOCUS", "MONITOR", "BACKGROUND", "SUPPRESS")
        ]
        assert priorities == sorted(priorities, reverse=True)
        assert priorities == [4, 3, 2, 1, 0]

    def test_score_bounds(self) -> None:
        rng = random.Random(_RNG_SEED + 32)
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            s = attention_mod.effective_attention_score(item, now=_FIXED_NOW)
            assert 0.0 <= s <= 1.0

    def test_confidence_bounds(self) -> None:
        rng = random.Random(_RNG_SEED + 33)
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            c = attention_mod.effective_attention_confidence(item, now=_FIXED_NOW)
            assert 0.0 <= c <= 1.0

    def test_active_passes_through_explicit_field(self) -> None:
        # `attention_active` is an independent stored field; explicit value passes through.
        assert attention_mod.effective_attention_active({"attention_active": True}) is True
        assert attention_mod.effective_attention_active({"attention_active": False}) is False

    def test_featured_passes_through_explicit_field(self) -> None:
        # `attention_featured` is an independent stored field; explicit value passes through.
        assert attention_mod.effective_attention_featured({"attention_featured": True}) is True
        assert attention_mod.effective_attention_featured({"attention_featured": False}) is False

    def test_active_and_featured_always_bool(self) -> None:
        rng = random.Random(_RNG_SEED + 35)
        assert isinstance(attention_mod.effective_attention_active({}, now=_FIXED_NOW), bool)
        assert isinstance(attention_mod.effective_attention_featured({}, now=_FIXED_NOW), bool)
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            assert isinstance(
                attention_mod.effective_attention_active(item, now=_FIXED_NOW), bool
            )
            assert isinstance(
                attention_mod.effective_attention_featured(item, now=_FIXED_NOW), bool
            )

    def test_featured_implies_active(self) -> None:
        # Documented dashboard contract: featured items are always active too.
        rng = random.Random(_RNG_SEED + 36)
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            featured = attention_mod.effective_attention_featured(item, now=_FIXED_NOW)
            active = attention_mod.effective_attention_active(item, now=_FIXED_NOW)
            if featured:
                assert active, "featured implies active"

    def test_idempotent_under_reinjection(self) -> None:
        rng = random.Random(_RNG_SEED + 34)
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            s1 = attention_mod.effective_attention_state(item, now=_FIXED_NOW)
            item2 = {**item, "attention_state": s1}
            s2 = attention_mod.effective_attention_state(item2, now=_FIXED_NOW)
            assert s1 == s2


# ---------------------------------------------------------------------------
# Catalyst state invariants
# ---------------------------------------------------------------------------


class TestCatalystStateInvariants:
    def test_score_bounds(self) -> None:
        rng = random.Random(_RNG_SEED + 40)
        assert 0.0 <= catalyst_mod.effective_catalyst_score({}) <= 1.0
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            assert 0.0 <= catalyst_mod.effective_catalyst_score(item) <= 1.0

    def test_sentiment_total_function(self) -> None:
        rng = random.Random(_RNG_SEED + 41)
        # Empty input must default cleanly.
        assert catalyst_mod.effective_catalyst_sentiment({}) in CATALYST_SENTIMENTS
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            assert catalyst_mod.effective_catalyst_sentiment(item) in CATALYST_SENTIMENTS

    def test_sentiment_direction_mapping(self) -> None:
        assert catalyst_mod.effective_catalyst_sentiment({"catalyst_direction": "BULLISH"}) == "bullish"
        assert catalyst_mod.effective_catalyst_sentiment({"catalyst_direction": "BEARISH"}) == "bearish"
        assert catalyst_mod.effective_catalyst_sentiment({"catalyst_direction": "NEUTRAL"}) == "neutral"
        assert catalyst_mod.effective_catalyst_sentiment({"catalyst_direction": "MIXED"}) == "neutral"

    def test_actionable_is_bool(self) -> None:
        rng = random.Random(_RNG_SEED + 42)
        assert isinstance(catalyst_mod.effective_catalyst_actionable({}), bool)
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            assert isinstance(
                catalyst_mod.effective_catalyst_actionable(item, now=_FIXED_NOW), bool
            )

    def test_high_score_is_actionable(self) -> None:
        # Documented contract: score >= 0.65 → actionable True.
        assert catalyst_mod.effective_catalyst_actionable({"catalyst_score": 0.95}) is True
        assert catalyst_mod.effective_catalyst_actionable({"catalyst_score": 0.65}) is True

    def test_age_minutes_returns_float_or_none(self) -> None:
        rng = random.Random(_RNG_SEED + 43)
        # No timestamp at all → None.
        assert catalyst_mod.effective_catalyst_age_minutes({}) is None
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            age = catalyst_mod.effective_catalyst_age_minutes(item, now=_FIXED_NOW)
            assert age is None or isinstance(age, float)
            if age is not None:
                # With now == _FIXED_NOW and published_ts within 24h, age is bounded.
                assert age >= 0.0


# ---------------------------------------------------------------------------
# live_story_key invariants
# ---------------------------------------------------------------------------


class TestLiveStoryKeyInvariants:
    def test_returns_string(self) -> None:
        rng = random.Random(_RNG_SEED + 50)
        # Empty item must never raise and must return a string.
        assert isinstance(live_story_mod.live_story_key({}), str)
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            assert isinstance(live_story_mod.live_story_key(item), str)

    def test_deterministic(self) -> None:
        rng = random.Random(_RNG_SEED + 51)
        for _ in range(_N_SAMPLES):
            item = _random_item(rng)
            assert live_story_mod.live_story_key(item) == live_story_mod.live_story_key(item)

    def test_explicit_story_key_passes_through(self) -> None:
        item = {"story_key": "AAPL:earnings:1715000000"}
        assert live_story_mod.live_story_key(item) == "AAPL:earnings:1715000000"

    def test_default_bucket_seconds_constant(self) -> None:
        # Module-level constant pinned at 900s (15 min).
        assert live_story_mod.LIVE_STORY_BUCKET_SECONDS == 900


# ---------------------------------------------------------------------------
# event_ledger round-trip invariants
# ---------------------------------------------------------------------------


def _make_event(event_id: str, prob: float, outcome: bool) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "family": "BOS",
        "predicted_prob": prob,
        "outcome": outcome,
        "timestamp": _FIXED_NOW,
        "context": {"session": "RTH"},
    }


class TestEventLedgerRoundTrip:
    def test_write_then_read_count_preserved(self, tmp_path: Path) -> None:
        events = [_make_event(f"e{i}", 0.5, True) for i in range(10)]
        out = tmp_path / "ledger.jsonl"
        n_written = write_event_ledger(events, output_path=out, symbol="AAPL", timeframe="5m")
        assert n_written == 10
        records = list(read_event_ledger(out))
        assert len(records) == 10

    def test_required_fields_present_after_round_trip(self, tmp_path: Path) -> None:
        events = [_make_event("e1", 0.42, False)]
        out = tmp_path / "ledger.jsonl"
        write_event_ledger(events, output_path=out, symbol="TSLA", timeframe="15m")
        records = list(read_event_ledger(out))
        assert len(records) == 1
        rec = records[0]
        for field_name in (
            "schema_version",
            "event_id",
            "symbol",
            "timeframe",
            "family",
            "timestamp",
            "predicted_prob",
            "outcome",
        ):
            assert field_name in rec, f"missing field: {field_name}"
        assert rec["symbol"] == "TSLA"
        assert rec["timeframe"] == "15m"
        assert rec["event_id"] == "e1"
        assert rec["predicted_prob"] == pytest.approx(0.42)
        assert rec["outcome"] is False

    def test_missing_predicted_prob_raises(self, tmp_path: Path) -> None:
        bad = [{
            "event_id": "x",
            "family": "BOS",
            "outcome": True,
            "timestamp": _FIXED_NOW,
        }]
        out = tmp_path / "ledger.jsonl"
        with pytest.raises(ValueError):
            write_event_ledger(bad, output_path=out, symbol="AAPL", timeframe="5m")

    def test_empty_input_produces_empty_file(self, tmp_path: Path) -> None:
        out = tmp_path / "empty.jsonl"
        n_written = write_event_ledger([], output_path=out, symbol="AAPL", timeframe="5m")
        assert n_written == 0
        assert out.exists()
        assert list(read_event_ledger(out)) == []

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        out = tmp_path / "deep" / "nested" / "dir" / "ledger.jsonl"
        events = [_make_event("e1", 0.7, True)]
        n_written = write_event_ledger(events, output_path=out, symbol="AAPL", timeframe="5m")
        assert n_written == 1
        assert out.exists()
