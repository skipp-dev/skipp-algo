"""Tests for the Finnhub social-sentiment pass-through (observe-only, no weight).

``social_sentiment`` (Finnhub social-buzz) reached the scorer feature dict and the
display snapshot but — until 2026-07-11 — was NOT in FEATURE_KEYS /
PASS_THROUGH_FEATURE_KEYS, so ``FeatureImportanceCollector.record`` (which only
copies FEATURE_KEYS) silently dropped it and it accrued zero FI-graduation
evidence, despite the candidate_weights "recorded for FI visibility" claim. These
tests pin the now-wired pass-through so a future refactor can't drop it again.

Mirrors tests/test_recent_eps_surprise_passthrough.py.
"""
from __future__ import annotations

from datetime import date

_TODAY = date(2026, 7, 11)


class TestOutcomeSnapshotPassThrough:
    def test_snapshot_includes_social_sentiment(self) -> None:
        from open_prep.outcomes import prepare_outcome_snapshot

        ranked = [{
            "symbol": "AAPL", "gap_pct": 2.0, "volume": 1_000_000, "avg_volume": 500_000,
            "score": 3.0, "social_sentiment": 0.42,
        }]
        rec = prepare_outcome_snapshot(ranked, _TODAY)[0]
        assert rec["social_sentiment"] == 0.42

    def test_snapshot_none_when_absent(self) -> None:
        # No Finnhub key / no social data -> None ("not measured"), NOT a real 0.
        from open_prep.outcomes import prepare_outcome_snapshot

        rec = prepare_outcome_snapshot(
            [{"symbol": "MSFT", "gap_pct": 1.0, "volume": 1, "avg_volume": 1, "score": 0.5}],
            _TODAY,
        )[0]
        assert rec["social_sentiment"] is None


class TestFeatureKeyConsistency:
    def test_social_sentiment_is_pass_through_not_weighted(self) -> None:
        from open_prep.outcomes import (
            FEATURE_KEYS,
            FEATURE_TO_WEIGHT_KEY,
            PASS_THROUGH_FEATURE_KEYS,
        )

        assert "social_sentiment" in FEATURE_KEYS  # -> reaches the FI samples
        assert "social_sentiment" in PASS_THROUGH_FEATURE_KEYS  # observe-only
        assert "social_sentiment" not in FEATURE_TO_WEIGHT_KEY  # zero scorer weight

    def test_recorder_persists_social_sentiment_to_fi_sample(self) -> None:
        # End-to-end: a score_breakdown carrying social_sentiment must land in the
        # recorded FI sample (the exact link that was broken before 2026-07-11).
        from open_prep.outcomes import FeatureImportanceCollector

        collector = FeatureImportanceCollector()
        collector.record("AAPL", {"social_sentiment": 0.7}, total_score=3.0, profitable_30m=True)
        sample = collector._buffer[-1]
        assert sample["social_sentiment"] == 0.7
