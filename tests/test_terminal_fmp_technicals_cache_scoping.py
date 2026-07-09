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


# ── Robustness: FMP indicator values that are 'N/A'/'' must not crash the
#    (unguarded) technicals fallback (review 2026-07-08). ────────────────────

def test_opt_float_drops_non_numeric_and_nan() -> None:
    assert t._opt_float(42) == 42.0
    assert t._opt_float("3.5") == 3.5
    assert t._opt_float(None) is None
    assert t._opt_float("N/A") is None
    assert t._opt_float("") is None
    assert t._opt_float(float("nan")) is None


def test_fetch_fmp_technicals_survives_na_indicator_values(monkeypatch) -> None:
    """A provider 'N/A' indicator field must skip that indicator, never raise —
    fetch_fmp_technicals runs unguarded whenever TradingView is rate-limited."""
    monkeypatch.setattr(t, "_get_api_key", lambda: "KEY")
    monkeypatch.setattr(t, "_cache_get", lambda *a, **k: None)
    monkeypatch.setattr(t, "_cache_set", lambda *a, **k: None)
    monkeypatch.setattr(t, "_fetch_price", lambda *a, **k: 10.0)
    monkeypatch.setattr(
        t, "_fetch_indicator",
        lambda sym, tf, kind, key, indicator_period=14: {kind: "N/A"},
    )
    out = t.fetch_fmp_technicals("AAA", "1D")  # must not raise
    assert out is not None
    # Every indicator was 'N/A' → dropped → no oscillator rows emitted.
    assert not any("RSI" in o.get("name", "") for o in out["osc_detail"])
    assert not any("Williams" in o.get("name", "") for o in out["osc_detail"])
