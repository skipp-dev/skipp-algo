"""Regression tests for PR-G (audit 2026-05-10).

Pin the negative-cache sentinel pattern in ``terminal_fmp_insights``
(the Producer-side OpenAI failure path).

Pre-PR-G, ``_get_cached`` returned ``T | None`` collapsing the
"unknown" and "known-miss" states into ``None``. A failed fetch was
NEVER cached, so every call after a transient error re-issued the
upstream request, producing thundering-herd behaviour.

PR-G changes the API to ``(hit: bool, value)`` and adds
``_set_cached_miss`` which writes a sentinel with a short TTL so the
back-off self-recovers.

Audit 2026-08-29 widened the accessor to ``_get_cached_entry`` ->
``(hit, value, blocked_by_policy)`` so a replayed AI Defense block keeps
block semantics instead of being reported as a provider outage. The
invariants pinned here are unchanged; only the third element is new.
"""

from __future__ import annotations

# ===========================================================================
# terminal_fmp_insights
# ===========================================================================


class TestFMPInsightsMissCache:
    def setup_method(self) -> None:
        import terminal_fmp_insights as fi
        fi._cache.clear()

    def test_get_cached_returns_tuple_for_unknown_key(self) -> None:
        import terminal_fmp_insights as fi
        hit, val, blocked = fi._get_cached_entry("never-seen")
        assert hit is False
        assert val == ""
        assert blocked is False

    def test_set_cached_miss_then_get_returns_hit_with_empty(self) -> None:
        import terminal_fmp_insights as fi
        fi._set_cached_miss("Q1")
        hit, val, blocked = fi._get_cached_entry("Q1")
        assert hit is True
        assert val == ""
        assert blocked is False

    def test_policy_block_is_cached_as_a_block_not_as_a_failure(self) -> None:
        import terminal_fmp_insights as fi
        fi._set_cached_miss("Q1", blocked=True)
        hit, val, blocked = fi._get_cached_entry("Q1")
        assert hit is True
        assert val == ""
        assert blocked is True

    def test_miss_expires_after_miss_ttl(self) -> None:
        import terminal_fmp_insights as fi
        fi._set_cached_miss("Q1")
        ts, sentinel = fi._cache["Q1"]
        fi._cache["Q1"] = (ts - fi._MISS_TTL_S - 1.0, sentinel)
        hit, val, blocked = fi._get_cached_entry("Q1")
        assert hit is False
        assert val == ""
        assert blocked is False
        assert "Q1" not in fi._cache

    def test_set_cached_then_get_returns_hit_with_text(self) -> None:
        import terminal_fmp_insights as fi
        fi._set_cached("Q1", "the answer")
        hit, val, blocked = fi._get_cached_entry("Q1")
        assert hit is True
        assert val == "the answer"
        assert blocked is False

    def test_query_surfaces_explicit_error_during_miss_backoff(self) -> None:
        import hashlib

        import terminal_fmp_insights as fi
        context = "{}"
        digest = hashlib.sha256(context.encode()).hexdigest()[:16]
        ck = fi._cache_key("Q", digest, fi._DEFAULT_MODEL, "sk-test")
        fi._set_cached_miss(ck)
        resp = fi.query_fmp_llm("Q", context, "sk-test")
        assert resp.answer == ""
        assert resp.cached is True
        assert "try again" in resp.error.lower()

    def test_query_replays_a_cached_block_with_the_block_answer(self) -> None:
        import hashlib

        import terminal_fmp_insights as fi
        context = "{}"
        digest = hashlib.sha256(context.encode()).hexdigest()[:16]
        ck = fi._cache_key("Q", digest, fi._DEFAULT_MODEL, "sk-test")
        fi._set_cached_miss(ck, blocked=True)
        resp = fi.query_fmp_llm("Q", context, "sk-test", blocked_answer="Blocked by policy.")
        assert resp.answer == "Blocked by policy."
        assert resp.error == ""


# ===========================================================================
# Cross-module invariant: miss-TTL must be SHORTER than success-TTL,
# otherwise a transient failure would back-off longer than a real
# success would live in the cache.
# ===========================================================================


def test_miss_ttl_shorter_than_success_ttl() -> None:
    import terminal_fmp_insights as fi
    assert fi._MISS_TTL_S < fi._CACHE_TTL_S
