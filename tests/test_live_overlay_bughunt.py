"""
Bug-hunt regression tests for live_overlay_daemon.
Confirmed via code execution:
  B15 – compute_flow_fields: last_vol silently one bar stale when last bar has no volume
  B18 – cache.patch_overlay: None values overwrite previously-valid values

Run:
  python -m pytest tests/test_live_overlay_bughunt.py -v
"""
import importlib
import threading

# ---------------------------------------------------------------------------
# Module loaders – always reload to pick up on-disk state
# ---------------------------------------------------------------------------

def _cache():
    import services.live_overlay_daemon.cache as m
    importlib.reload(m)
    return m


def _compute():
    import services.live_overlay_daemon.compute as m
    importlib.reload(m)
    return m


# ============================================================
# B15 – compute_flow_fields volume/bar misalignment
# ============================================================

class TestFlowFieldsVolumeMisalignment:
    """
    FIXED BUG B15: volumes list was filtered independently of bars.
    If the last bar has no volume, volumes[-1] returned bars[-2].volume,
    producing a one-bar-stale rel_vol ratio alongside bars[-1]'s price delta.
    Fix: anchor last_vol to bars[-1].get("volume"); return None if absent.
    """

    def test_flow_rel_vol_is_none_when_last_bar_has_no_volume(self):
        compute = _compute()
        bars = [
            {"open": 100.0, "close": 101.0, "high": 102.0, "low": 99.0,  "volume": 1000},
            {"open": 101.0, "close": 102.0, "high": 103.0, "low": 100.0, "volume": 1500},
            {"open": 102.0, "close": 103.0, "high": 104.0, "low": 101.0, "volume": 2000},
            {"open": 103.0, "close": 104.0, "high": 105.0, "low": 102.0, "volume": 2500},
            {"open": 104.0, "close": 105.0, "high": 106.0, "low": 103.0, "volume": 3000},
            # last bar: NO volume — must yield flow_rel_vol=None, not 3000/avg(1000..2500)
            {"open": 105.0, "close": 106.0, "high": 107.0, "low": 104.0},
        ]
        result = compute.compute_flow_fields(bars)
        assert result["flow_rel_vol"] is None, (
            f"B15 regression: flow_rel_vol={result['flow_rel_vol']} was computed "
            "even though the last bar has no volume; ratio is one bar stale"
        )

    def test_flow_rel_vol_is_computed_when_last_bar_has_volume(self):
        """Happy path: last bar has a volume — ratio must be returned."""
        compute = _compute()
        bars = [
            {"open": 100.0, "close": 101.0, "high": 102.0, "low": 99.0,  "volume": 1000},
            {"open": 101.0, "close": 102.0, "high": 103.0, "low": 100.0, "volume": 1000},
            {"open": 102.0, "close": 103.0, "high": 104.0, "low": 101.0, "volume": 1000},
            {"open": 103.0, "close": 104.0, "high": 105.0, "low": 102.0, "volume": 1000},
            # last bar has 2× the average volume
            {"open": 104.0, "close": 105.0, "high": 106.0, "low": 103.0, "volume": 2000},
        ]
        result = compute.compute_flow_fields(bars)
        assert result["flow_rel_vol"] is not None
        assert abs(result["flow_rel_vol"] - 2.0) < 0.01, (
            f"Expected rel_vol≈2.0, got {result['flow_rel_vol']}"
        )

    def test_flow_rel_vol_is_none_with_all_volumes_missing_except_one(self):
        """Only last bar has volume → no prior volumes → avg_vol=None → rel_vol=None."""
        compute = _compute()
        bars = [
            {"open": 100.0, "close": 101.0, "high": 102.0, "low": 99.0},
            {"open": 101.0, "close": 102.0, "high": 103.0, "low": 100.0},
            {"open": 102.0, "close": 103.0, "high": 104.0, "low": 101.0},
            {"open": 103.0, "close": 104.0, "high": 105.0, "low": 102.0, "volume": 5000},
        ]
        result = compute.compute_flow_fields(bars)
        assert result["flow_rel_vol"] is None, (
            "Need ≥1 prior bar with volume to compute rel_vol; got "
            f"flow_rel_vol={result['flow_rel_vol']}"
        )

    def test_empty_bars_returns_none_fields(self):
        compute = _compute()
        result = compute.compute_flow_fields([])
        assert result == {"flow_rel_vol": None, "flow_delta_proxy_pct": None}

    def test_flow_delta_still_computed_when_last_bar_has_no_volume(self):
        """flow_delta_proxy_pct is independent of volume; must still be computed."""
        compute = _compute()
        bars = [
            {"open": 100.0, "close": 101.0, "high": 102.0, "low": 99.0, "volume": 1000},
            {"open": 100.0, "close": 110.0, "high": 111.0, "low": 99.0},  # +10%, no volume
        ]
        result = compute.compute_flow_fields(bars)
        assert result["flow_rel_vol"] is None
        assert result["flow_delta_proxy_pct"] is not None
        assert abs(result["flow_delta_proxy_pct"] - 10.0) < 0.01, (
            f"Expected flow_delta≈10.0%, got {result['flow_delta_proxy_pct']}"
        )


# ============================================================
# B18 – cache.patch_overlay None-overwrite
# ============================================================

class TestPatchOverlayNoneGuard:
    """
    FIXED BUG B18: patch_overlay did payload.update(updates) unconditionally.
    A flow-refresh cycle that cannot compute flow_rel_vol (e.g. last bar has
    no volume after the B15 fix) passes {'flow_rel_vol': None} and erased a
    previously-valid value.
    Fix: skip keys whose value is None in the update dict.
    """

    def test_none_value_does_not_overwrite_existing_valid_value(self):
        cache = _cache()
        initial = {
            "symbol": "AAPL",
            "flow_rel_vol": 1.5,
            "flow_delta_proxy_pct": -0.3,
            "vix_level": 18.0,
            "stale": False,
        }
        cache.set_overlay({"AAPL": initial})
        cache.patch_overlay("AAPL", {"flow_rel_vol": None, "flow_delta_proxy_pct": None})
        result = cache.get_overlay("AAPL")
        assert result is not None
        assert result["flow_rel_vol"] == 1.5, (
            f"B18 regression: flow_rel_vol was overwritten with None; got {result['flow_rel_vol']}"
        )
        assert result["flow_delta_proxy_pct"] == -0.3, (
            f"B18 regression: flow_delta_proxy_pct was overwritten with None; "
            f"got {result['flow_delta_proxy_pct']}"
        )

    def test_non_none_value_is_patched_normally(self):
        cache = _cache()
        cache.set_overlay({"TSLA": {"symbol": "TSLA", "flow_rel_vol": 1.0, "vix_level": 20.0}})
        cache.patch_overlay("TSLA", {"flow_rel_vol": 2.5})
        result = cache.get_overlay("TSLA")
        assert result["flow_rel_vol"] == 2.5

    def test_vix_level_none_does_not_overwrite(self):
        cache = _cache()
        cache.set_overlay({"NVDA": {"symbol": "NVDA", "vix_level": 22.5}})
        # vix refresh fails → passes None
        cache.patch_overlay("NVDA", {"vix_level": None})
        result = cache.get_overlay("NVDA")
        assert result["vix_level"] == 22.5, (
            f"vix_level was overwritten with None; got {result['vix_level']}"
        )

    def test_patch_on_unknown_symbol_is_a_noop(self):
        cache = _cache()
        # Should not raise, not create a new entry
        cache.patch_overlay("UNKNOWN", {"flow_rel_vol": 1.5})
        assert cache.get_overlay("UNKNOWN") is None

    def test_mixed_patch_updates_non_none_skips_none(self):
        cache = _cache()
        cache.set_overlay({"AMD": {
            "symbol": "AMD",
            "flow_rel_vol": 1.0,
            "flow_delta_proxy_pct": 0.5,
            "vix_level": 19.0,
        }})
        cache.patch_overlay("AMD", {
            "flow_rel_vol": 2.0,       # should be applied
            "flow_delta_proxy_pct": None,  # should be skipped
            "vix_level": 21.0,         # should be applied
        })
        result = cache.get_overlay("AMD")
        assert result["flow_rel_vol"] == 2.0
        assert result["flow_delta_proxy_pct"] == 0.5  # preserved
        assert result["vix_level"] == 21.0


# ============================================================
# Concurrency: set_overlay / get_overlay never serve partial state
# ============================================================

class TestCacheConcurrentConsistency:
    def test_concurrent_set_and_get_never_returns_partial_payload(self):
        """Writer calls set_overlay 500×; reader calls get_overlay 500×.
        Reader must never observe a state that is neither A nor B."""
        cache = _cache()
        errors: list[str] = []
        ROUNDS = 500
        SYMBOLS = ["AAPL", "TSLA", "NVDA"]

        payload_a = {s: {"symbol": s, "close": 100.0, "flag": "A"} for s in SYMBOLS}
        payload_b = {s: {"symbol": s, "close": 200.0, "flag": "B"} for s in SYMBOLS}

        def writer():
            for i in range(ROUNDS):
                cache.set_overlay(payload_a if i % 2 == 0 else payload_b)

        def reader():
            for _ in range(ROUNDS):
                for sym in SYMBOLS:
                    p = cache.get_overlay(sym)
                    if p is not None and p.get("flag") not in ("A", "B"):
                        errors.append(f"partial state for {sym}: {p}")

        w = threading.Thread(target=writer)
        r = threading.Thread(target=reader)
        w.start()
        r.start()
        w.join()
        r.join()
        assert not errors, f"Concurrent consistency violations: {errors[:3]}"


# ============================================================
# _safe_std / _safe_mean edge cases
# ============================================================

class TestSafeStatEdgeCases:
    def test_safe_std_single_element(self):
        compute = _compute()
        result = compute._safe_std([42.0])
        assert result == 0.0 or result is None

    def test_safe_std_all_equal(self):
        compute = _compute()
        assert compute._safe_std([5.0, 5.0, 5.0, 5.0]) == 0.0

    def test_safe_std_does_not_return_nan_or_inf(self):
        import math
        import random
        compute = _compute()
        for _ in range(200):
            vals = [random.uniform(-1e14, 1e14) for _ in range(random.randint(2, 30))]
            r = compute._safe_std(vals)
            assert r is None or math.isfinite(r), (
                f"_safe_std returned non-finite {r} for {vals[:3]}…"
            )

    def test_safe_mean_empty_returns_none(self):
        compute = _compute()
        assert compute._safe_mean([]) is None

    def test_safe_mean_zero_list(self):
        compute = _compute()
        assert compute._safe_mean([0.0, 0.0, 0.0]) == 0.0
