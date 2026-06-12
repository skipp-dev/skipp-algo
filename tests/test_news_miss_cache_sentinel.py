"""Regression tests for PR-G (audit 2026-05-10).

Pin the negative-cache sentinel pattern in three modules:

* ``terminal_tradingview_news``  -> ``fetch_tv`` failure path
* ``terminal_ai_insights``       -> OpenAI failure path
* ``terminal_fmp_insights``      -> OpenAI failure path

Pre-PR-G, ``_get_cached`` returned ``T | None`` collapsing the
"unknown" and "known-miss" states into ``None``. A failed fetch was
NEVER cached, so every call after a transient error re-issued the
upstream request, producing thundering-herd behaviour and (for TV)
double-counting in the ``_health`` failure counter.

PR-G changes the API to ``(hit: bool, value)`` and adds
``_set_cached_miss`` which writes a sentinel with a short TTL so the
back-off self-recovers.
"""

from __future__ import annotations

from unittest.mock import patch

# ===========================================================================
# terminal_tradingview_news
# ===========================================================================


class TestTradingViewMissCache:
    def setup_method(self) -> None:
        import terminal_tradingview_news as tv
        tv._cache.clear()

    def test_get_cached_returns_tuple_for_unknown_key(self) -> None:
        import terminal_tradingview_news as tv
        hit, val = tv._get_cached("never-seen")
        assert hit is False
        assert val == []

    def test_set_cached_miss_then_get_returns_hit_with_empty(self) -> None:
        import terminal_tradingview_news as tv
        tv._set_cached_miss("AAPL")
        hit, val = tv._get_cached("AAPL")
        assert hit is True
        assert val == []

    def test_miss_expires_after_miss_ttl(self) -> None:
        import terminal_tradingview_news as tv
        tv._set_cached_miss("AAPL")
        # Manually age the entry past _MISS_TTL_S.
        ts, sentinel = tv._cache["AAPL"]
        tv._cache["AAPL"] = (ts - tv._MISS_TTL_S - 1.0, sentinel)
        hit, val = tv._get_cached("AAPL")
        assert hit is False
        assert val == []
        assert "AAPL" not in tv._cache  # expired entry purged

    def test_fetch_tv_failure_caches_miss_and_short_circuits_next_call(
        self,
    ) -> None:
        """Canonical regression: a failed fetch_tv MUST cache the miss
        so a follow-up call within _MISS_TTL_S does NOT re-issue
        _fetch_raw nor double-record a health failure."""
        import terminal_tradingview_news as tv

        call_count = {"raw": 0, "fail": 0}

        def boom(_ticker: str) -> dict:
            call_count["raw"] += 1
            raise RuntimeError("upstream 503")

        def record_failure(_msg: str) -> None:
            call_count["fail"] += 1

        with patch.object(tv, "_fetch_raw", side_effect=boom), \
             patch.object(tv._health, "record_failure", side_effect=record_failure):
            r1 = tv.fetch_tv_headlines("AAPL")
            r2 = tv.fetch_tv_headlines("AAPL")
            r3 = tv.fetch_tv_headlines("AAPL")

        assert r1 == [] and r2 == [] and r3 == []
        # Only the FIRST call should have hit upstream / counted a
        # health failure. Subsequent calls must be served from the
        # negative cache.
        assert call_count["raw"] == 1, (
            "Negative cache must short-circuit subsequent fetch_raw calls "
            f"but raw was called {call_count['raw']} times"
        )
        assert call_count["fail"] == 1, (
            "Health-failure must be recorded ONCE per logical fetch failure "
            f"but was recorded {call_count['fail']} times"
        )


# ===========================================================================
# terminal_ai_insights
# ===========================================================================


class TestAIInsightsMissCache:
    def setup_method(self) -> None:
        import terminal_ai_insights as ai
        ai._cache.clear()

    def test_get_cached_returns_tuple_for_unknown_key(self) -> None:
        import terminal_ai_insights as ai
        hit, val = ai._get_cached("never-seen")
        assert hit is False
        assert val == ""

    def test_set_cached_miss_then_get_returns_hit_with_empty(self) -> None:
        import terminal_ai_insights as ai
        ai._set_cached_miss("Q1")
        hit, val = ai._get_cached("Q1")
        assert hit is True
        assert val == ""

    def test_miss_expires_after_miss_ttl(self) -> None:
        import terminal_ai_insights as ai
        ai._set_cached_miss("Q1")
        ts, sentinel = ai._cache["Q1"]
        ai._cache["Q1"] = (ts - ai._MISS_TTL_S - 1.0, sentinel)
        hit, val = ai._get_cached("Q1")
        assert hit is False
        assert val == ""
        assert "Q1" not in ai._cache

    def test_set_cached_then_get_returns_hit_with_text(self) -> None:
        import terminal_ai_insights as ai
        ai._set_cached("Q1", "the answer")
        hit, val = ai._get_cached("Q1")
        assert hit is True
        assert val == "the answer"


# ===========================================================================
# terminal_fmp_insights
# ===========================================================================


class TestFMPInsightsMissCache:
    def setup_method(self) -> None:
        import terminal_fmp_insights as fi
        fi._cache.clear()

    def test_get_cached_returns_tuple_for_unknown_key(self) -> None:
        import terminal_fmp_insights as fi
        hit, val = fi._get_cached("never-seen")
        assert hit is False
        assert val == ""

    def test_set_cached_miss_then_get_returns_hit_with_empty(self) -> None:
        import terminal_fmp_insights as fi
        fi._set_cached_miss("Q1")
        hit, val = fi._get_cached("Q1")
        assert hit is True
        assert val == ""

    def test_miss_expires_after_miss_ttl(self) -> None:
        import terminal_fmp_insights as fi
        fi._set_cached_miss("Q1")
        ts, sentinel = fi._cache["Q1"]
        fi._cache["Q1"] = (ts - fi._MISS_TTL_S - 1.0, sentinel)
        hit, val = fi._get_cached("Q1")
        assert hit is False
        assert val == ""
        assert "Q1" not in fi._cache

    def test_set_cached_then_get_returns_hit_with_text(self) -> None:
        import terminal_fmp_insights as fi
        fi._set_cached("Q1", "the answer")
        hit, val = fi._get_cached("Q1")
        assert hit is True
        assert val == "the answer"


# ===========================================================================
# Cross-module invariant: miss-TTL must be SHORTER than success-TTL,
# otherwise a transient failure would back-off longer than a real
# success would live in the cache.
# ===========================================================================


def test_miss_ttl_shorter_than_success_ttl() -> None:
    import terminal_ai_insights as ai
    import terminal_fmp_insights as fi
    import terminal_tradingview_news as tv
    assert tv._MISS_TTL_S < tv._CACHE_TTL
    assert ai._MISS_TTL_S < ai._CACHE_TTL_S
    assert fi._MISS_TTL_S < fi._CACHE_TTL_S
