"""Manual fuzzing / property tests without Hypothesis.

Goal: find broken invariants using many random and extreme inputs.
"""
from __future__ import annotations

import math
import random

import pytest


class TestComputeFlowFieldsFuzz:
    """Invariants for compute_flow_fields."""

    def test_flow_delta_proxy_pct_within_bounds(self) -> None:
        import services.live_overlay_daemon.compute as compute

        random.seed(42)
        for _ in range(1000):
            open_ = random.uniform(0.01, 1000.0)
            close_ = random.uniform(0.01, 1000.0)
            bars = [
                {"open": open_, "high": max(open_, close_), "low": min(open_, close_), "close": close_, "volume": random.randint(1, 1_000_000)}
            ]
            result = compute.compute_flow_fields(bars)
            delta = result["flow_delta_proxy_pct"]
            if delta is not None:
                assert math.isfinite(delta), f"delta must be finite, got {delta}"

    def test_flow_rel_vol_non_negative(self) -> None:
        import services.live_overlay_daemon.compute as compute

        random.seed(42)
        for _ in range(1000):
            volumes = [random.uniform(0, 1e9) for _ in range(random.randint(1, 50))]
            bars = [
                {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": v}
                for v in volumes
            ]
            result = compute.compute_flow_fields(bars)
            rel = result["flow_rel_vol"]
            if rel is not None:
                assert rel >= 0.0, f"flow_rel_vol negative: {rel}"


class TestComputeSqueezeOnFuzz:
    """Invariants for compute_squeeze_on."""

    def test_squeeze_on_returns_bool_or_none(self) -> None:
        import services.live_overlay_daemon.compute as compute

        random.seed(42)
        for _ in range(500):
            n = random.randint(1, 40)
            bars = [
                {
                    "open": random.uniform(1.0, 100.0),
                    "high": random.uniform(1.0, 100.0),
                    "low": random.uniform(1.0, 100.0),
                    "close": random.uniform(1.0, 100.0),
                    "volume": random.randint(1, 1000000),
                }
                for _ in range(n)
            ]
            result = compute.compute_squeeze_on(bars)
            assert result is None or isinstance(result, bool), f"unexpected type: {type(result)}"


class TestGetNewsFieldsFuzz:
    """Invariants for _get_news_fields."""

    def test_news_strength_between_zero_and_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.live_overlay_daemon.compute as compute

        random.seed(42)
        for _ in range(500):
            n_stories = random.randint(0, 50)
            stories = [
                {
                    "tickers": ["AAPL"],
                    "sentiment_score": random.uniform(-10.0, 10.0),
                }
                for _ in range(n_stories)
            ]
            snap = {"stories": stories}

            # Use monkeypatch to avoid direct module-level mutation and file I/O.
            monkeypatch.setattr(compute, "_load_news_snapshot", lambda s=snap: s)

            fields = compute._get_news_fields("AAPL")
            strength = fields["news_strength"]
            if strength is not None:
                assert 0.0 <= strength <= 1.0, f"news_strength out of bounds: {strength}"


class TestGlobalNewsFieldsFuzz:
    """Invariants for _get_global_news_fields."""

    def test_global_heat_between_minus_one_and_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.live_overlay_daemon.compute as compute

        random.seed(42)
        for _ in range(500):
            n = random.randint(1, 100)
            stories = [
                {"sentiment_score": random.uniform(-100.0, 100.0)}
                for _ in range(n)
            ]
            snap = {"stories": stories}

            # Use monkeypatch to avoid direct module-level mutation and file I/O.
            monkeypatch.setattr(compute, "_load_news_snapshot", lambda s=snap: s)

            fields = compute._get_global_news_fields()
            heat = fields["global_heat"]
            assert heat is None or -1.0 <= heat <= 1.0, f"global_heat out of bounds: {heat}"
            assert fields["tone"] in ("BULLISH", "BEARISH", "NEUTRAL")


class TestBuildPayloadFuzz:
    """Invariants for build_payload."""

    def test_build_payload_never_crashes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.live_overlay_daemon.compute as compute

        monkeypatch.setattr(compute, "_load_news_snapshot", lambda: {})
        random.seed(42)
        for _ in range(500):
            n = random.randint(0, 100)
            bars = [
                {
                    "open": random.uniform(-1000.0, 1000.0),
                    "high": random.uniform(-1000.0, 1000.0),
                    "low": random.uniform(-1000.0, 1000.0),
                    "close": random.uniform(-1000.0, 1000.0),
                    "volume": random.randint(-1000, 1000000),
                }
                for _ in range(n)
            ]
            try:
                payload = compute.build_payload("AAPL", bars, {"tone": "NEUTRAL", "global_heat": 0.0}, 3600)
            except Exception as exc:
                pytest.fail(f"build_payload crashed on random bars: {exc}")

            assert payload["symbol"] == "AAPL"
            assert isinstance(payload["stale"], bool)
