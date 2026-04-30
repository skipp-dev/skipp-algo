"""Tests for stale-batch protection (ENG-WS5-02)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from smc_integration.stale_batch_guard import (
    DEFAULT_AGING_HOURS,
    DEFAULT_STALE_HOURS,
    StaleStatus,
    classify_batch,
    evaluate,
)

NOW = datetime(2026, 4, 20, 12, 0, tzinfo=UTC)


def _ts(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


class TestClassifyBatch:
    def test_fresh_below_aging(self) -> None:
        b = classify_batch("daily", _ts(2), now=NOW)
        assert b.status is StaleStatus.FRESH

    def test_aging_in_warn_band(self) -> None:
        b = classify_batch("daily", _ts(20), now=NOW)
        assert b.status is StaleStatus.AGING
        assert "aging threshold" in b.reason

    def test_stale_above_threshold(self) -> None:
        b = classify_batch("daily", _ts(40), now=NOW)
        assert b.status is StaleStatus.STALE

    def test_unknown_when_timestamp_missing(self) -> None:
        b = classify_batch("daily", None, now=NOW)
        assert b.status is StaleStatus.UNKNOWN
        assert "missing or unparsable timestamp" in b.reason

    def test_unknown_when_timestamp_unparsable(self) -> None:
        b = classify_batch("daily", "not-a-date", now=NOW)
        assert b.status is StaleStatus.UNKNOWN

    def test_thresholds_are_configurable(self) -> None:
        b = classify_batch("daily", _ts(5), now=NOW,
                           aging_hours=2, stale_hours=4)
        assert b.status is StaleStatus.STALE


class TestEvaluate:
    def test_all_fresh_unblocked(self) -> None:
        v = evaluate([
            {"name": "A", "timestamp": _ts(1)},
            {"name": "B", "timestamp": _ts(2)},
        ], now=NOW)
        assert v.overall_status is StaleStatus.FRESH
        assert v.blocked is False

    def test_aging_does_not_block(self) -> None:
        v = evaluate([
            {"name": "A", "timestamp": _ts(1)},
            {"name": "B", "timestamp": _ts(20)},  # aging
        ], now=NOW)
        assert v.overall_status is StaleStatus.AGING
        assert v.blocked is False
        assert "aging" in v.reason

    def test_stale_blocks_and_names_batches(self) -> None:
        v = evaluate([
            {"name": "fresh-one", "timestamp": _ts(1)},
            {"name": "stale-one", "timestamp": _ts(48)},
        ], now=NOW)
        assert v.overall_status is StaleStatus.STALE
        assert v.blocked is True
        assert "stale-one" in v.reason

    def test_unknown_blocks(self) -> None:
        v = evaluate([
            {"name": "A", "timestamp": _ts(1)},
            {"name": "no-ts", "timestamp": None},
        ], now=NOW)
        assert v.overall_status is StaleStatus.UNKNOWN
        assert v.blocked is True

    def test_stale_takes_priority_over_unknown(self) -> None:
        v = evaluate([
            {"name": "stale", "timestamp": _ts(72)},
            {"name": "no-ts", "timestamp": None},
        ], now=NOW)
        assert v.overall_status is StaleStatus.STALE

    def test_no_batches_blocks(self) -> None:
        v = evaluate([], now=NOW)
        assert v.blocked is True
        assert v.overall_status is StaleStatus.UNKNOWN

    def test_as_dict_includes_per_batch_age(self) -> None:
        v = evaluate([{"name": "A", "timestamp": _ts(1)}], now=NOW)
        d = v.as_dict()
        assert d["overall_status"] == "fresh"
        assert d["batches"][0]["name"] == "A"
        assert d["batches"][0]["age_hours"] >= 0


class TestPolicy:
    def test_default_thresholds_published(self) -> None:
        # Publish the policy so workflows can cite the same numbers.
        assert DEFAULT_AGING_HOURS < DEFAULT_STALE_HOURS
        assert DEFAULT_STALE_HOURS >= 24
