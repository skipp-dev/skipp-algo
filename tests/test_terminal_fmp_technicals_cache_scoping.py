"""Regression tests for PR-I (audit 2026-05-10).

Pin the per-API-key fingerprint scoping of ``_fmp_cache`` in
``terminal_fmp_technicals``.

Pre-PR-I the cache key was ``(symbol, interval)`` and the cache was
a single module-global dict shared across every FMP account, so a
technical-indicator snapshot fetched under one API key was silently
served to callers using a different key. Class-equivalent to the
dataset-cache (PR-C #2124) and quote-cache (PR-E #2129) leakage bugs.
"""

from __future__ import annotations

import terminal_fmp_technicals as t


class TestFMPTechnicalsCacheScoping:
    def setup_method(self) -> None:
        t._fmp_cache.clear()

    def test_cache_keys_are_three_tuples_with_fingerprint_first(self) -> None:
        t._cache_set("AAPL", "1D", "KEY-A", {"rsi": 50})
        keys = list(t._fmp_cache.keys())
        assert len(keys) == 1
        k = keys[0]
        assert len(k) == 3
        fp_a = t._client_fingerprint("KEY-A")
        assert k == (fp_a, "AAPL", "1D")

    def test_two_keys_have_independent_fingerprints(self) -> None:
        assert t._client_fingerprint("KEY-A") != t._client_fingerprint("KEY-B")

    def test_cache_does_not_leak_across_keys(self) -> None:
        """Canonical regression: a value cached under KEY-A MUST NOT
        be returned to a caller using KEY-B."""
        t._cache_set("AAPL", "1D", "KEY-A", {"rsi": 50, "src": "A"})

        # Same key, same params -> hit.
        hit_a = t._cache_get("AAPL", "1D", "KEY-A")
        assert hit_a == {"rsi": 50, "src": "A"}

        # Different key, same params -> MUST be a miss.
        miss_b = t._cache_get("AAPL", "1D", "KEY-B")
        assert miss_b is None, (
            "Cache leaked across API keys: KEY-B received KEY-A's value"
        )

    def test_set_then_get_same_key_roundtrip(self) -> None:
        t._cache_set("MSFT", "4H", "KEY-X", {"macd": 1.23})
        assert t._cache_get("MSFT", "4H", "KEY-X") == {"macd": 1.23}

    def test_expired_for_one_key_does_not_affect_other(self) -> None:
        fp_a = t._client_fingerprint("KEY-A")
        # Pre-populate both, manually age KEY-A's entry past TTL.
        t._cache_set("AAPL", "1D", "KEY-A", {"v": "stale"})
        t._cache_set("AAPL", "1D", "KEY-B", {"v": "fresh"})
        ts_a, val_a = t._fmp_cache[(fp_a, "AAPL", "1D")]
        t._fmp_cache[(fp_a, "AAPL", "1D")] = (
            ts_a - t._FMP_CACHE_TTL - 10.0,
            val_a,
        )
        assert t._cache_get("AAPL", "1D", "KEY-A") is None
        # KEY-B unaffected.
        assert t._cache_get("AAPL", "1D", "KEY-B") == {"v": "fresh"}

    def test_no_api_key_fingerprint_is_stable(self) -> None:
        """An empty/None api_key still produces a deterministic
        fingerprint (sentinel) so the cache remains usable in
        no-credentials test environments."""
        assert t._client_fingerprint("") == "no-api-key"
        # Two writes with empty api_key should hit the same partition.
        t._cache_set("AAPL", "1D", "", {"v": 1})
        assert t._cache_get("AAPL", "1D", "") == {"v": 1}
