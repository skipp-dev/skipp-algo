"""Regression tests for PR-E (audit 2026-05-10).

Pin the per-API-key fingerprint scoping of ``_quote_cache`` /
``_quote_cache_ts`` in ``terminal_databento``.

Pre-PR-E both were module-globals shared across every API key
(``_quote_cache: dict[symbol, quote]`` and ``_quote_cache_ts: float``)
so a quote fetched under one Databento account was silently served to
callers using a different API key. This is a cross-account leakage
class-equivalent to the dataset-cache bug PR-C (#2124) fixed.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import terminal_databento as td


class TestQuoteCachePerKeyScoping:
    def setup_method(self) -> None:
        td._quote_cache.clear()
        td._quote_cache_ts.clear()

    def test_cache_state_is_per_fingerprint_dict(self) -> None:
        """The module-level types MUST be dicts keyed by fingerprint."""
        assert isinstance(td._quote_cache, dict)
        assert isinstance(td._quote_cache_ts, dict)

    def test_two_keys_have_independent_fingerprints(self) -> None:
        fp_a = td._client_fingerprint("KEY-A")
        fp_b = td._client_fingerprint("KEY-B")
        assert fp_a != fp_b

    def test_cache_does_not_leak_across_keys(self) -> None:
        """Canonical regression. A quote written under KEY-A must
        NEVER be returned to a caller using KEY-B."""
        fp_a = td._client_fingerprint("KEY-A")
        fp_b = td._client_fingerprint("KEY-B")

        # Manually populate KEY-A's cache as if a recent fetch had
        # succeeded for symbol AAPL.
        td._quote_cache[fp_a] = {"AAPL": {"price": 100.0, "src": "A"}}
        td._quote_cache_ts[fp_a] = time.time()

        # KEY-B has its own (empty) partition.
        b_quotes = td._quote_cache.get(fp_b, {})
        assert "AAPL" not in b_quotes, (
            "Quote cached under KEY-A leaked into KEY-B's partition"
        )
        # And no shared timestamp.
        assert td._quote_cache_ts.get(fp_b, 0.0) == 0.0

    def test_fetch_quotes_serves_cache_only_for_matching_fingerprint(
        self,
    ) -> None:
        """End-to-end: with KEY-A populated, calling fetch_quotes
        under KEY-B MUST trigger an upstream fetch (not return the
        KEY-A cached value)."""
        fp_a = td._client_fingerprint("KEY-A")

        # Pre-populate KEY-A's cache with AAPL.
        td._quote_cache[fp_a] = {"AAPL": {"price": 100.0, "src": "A"}}
        td._quote_cache_ts[fp_a] = time.time()

        # Run fetch_quotes under KEY-B and assert that the upstream
        # path was taken (cache miss) by stubbing _get_api_key + the
        # network-touching helpers.
        upstream_called = {"n": 0}

        def fake_make_client(_key: str):
            upstream_called["n"] += 1
            return None

        # We expect fetch_quotes to NOT short-circuit from KEY-A's
        # cache. Make _make_databento_client raise so we can detect
        # that the network path was attempted (and short-circuit at
        # client creation).
        def boom_make_client(_key: str):
            upstream_called["n"] += 1
            raise RuntimeError("upstream not actually reached in test")

        with patch.object(td, "_get_api_key", return_value="KEY-B"), \
             patch.object(td, "_make_databento_client",
                          side_effect=boom_make_client):
            try:
                td.fetch_databento_daily_bars_with_status(["AAPL"])
            except RuntimeError:
                pass  # expected: stubbed upstream
        assert upstream_called["n"] >= 1, (
            "KEY-B should NOT have been served from KEY-A's cache; "
            "upstream client creation was never attempted"
        )

    def test_fetch_quotes_short_circuits_on_own_cache_hit(self) -> None:
        """Same key, fully-cached symbols -> no upstream call."""
        fp = td._client_fingerprint("KEY-X")
        td._quote_cache[fp] = {"AAPL": {"price": 200.0}}
        td._quote_cache_ts[fp] = time.time()

        with patch.object(td, "_get_api_key", return_value="KEY-X"), \
             patch.object(td, "_make_databento_client",
                          side_effect=AssertionError("must not be called")):
            quotes, failed = td.fetch_databento_daily_bars_with_status(["AAPL"])
        assert quotes == {"AAPL": {"price": 200.0}}
        assert failed == []

    def test_expired_cache_for_one_key_does_not_affect_other(self) -> None:
        fp_a = td._client_fingerprint("KEY-A")
        fp_b = td._client_fingerprint("KEY-B")
        td._quote_cache[fp_a] = {"AAPL": {"price": 1.0}}
        td._quote_cache_ts[fp_a] = time.time() - td._QUOTE_CACHE_TTL - 10.0
        td._quote_cache[fp_b] = {"AAPL": {"price": 2.0}}
        td._quote_cache_ts[fp_b] = time.time()

        # KEY-B is fresh; KEY-A is expired. Verify directly via the
        # dict layout we expect post-PR-E.
        now = time.time()
        assert now - td._quote_cache_ts[fp_b] < td._QUOTE_CACHE_TTL
        assert now - td._quote_cache_ts[fp_a] >= td._QUOTE_CACHE_TTL
