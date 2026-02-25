"""Tests for the A0/A1 realtime signal auto-promotion logic.

The ``promote_a0a1_signals`` function bridges the gap between the pipeline
scorer (point-in-time snapshot) and the realtime engine (continuous breakout
detection).  These tests verify that:

1. Below-cutoff symbols with A0/A1 signals are promoted into ranked_v2.
2. Hard-filtered symbols are NOT promoted (even if they have A0/A1 signals).
3. Symbols already in ranked_v2 are not duplicated.
4. Promoted symbols are removed from filtered_out_v2.
5. The function is a no-op when no RT signals exist.
"""
from __future__ import annotations

import copy
import unittest

from open_prep.streamlit_monitor import promote_a0a1_signals


def _make_ranked(symbols: list[str], base_score: float = 5.0) -> list[dict]:
    """Build a minimal ranked_v2 list for testing."""
    return [
        {"symbol": s, "score": base_score - i * 0.1, "gap_pct": 2.0,
         "confidence_tier": "HIGH_CONVICTION"}
        for i, s in enumerate(symbols)
    ]


def _make_filtered_out(entries: list[tuple[str, list[str], float]]) -> list[dict]:
    """Build a minimal filtered_out_v2 list.

    Each entry is ``(symbol, filter_reasons, score)``.
    """
    return [
        {"symbol": s, "filter_reasons": r, "score": sc, "gap_pct": 1.0,
         "price": 100.0, "confidence_tier": "STANDARD"}
        for s, r, sc in entries
    ]


def _make_rt_signals(entries: list[tuple[str, str, str, str]]) -> list[dict]:
    """Build minimal RT signal dicts.

    Each entry is ``(symbol, level, direction, pattern)``.
    """
    return [
        {"symbol": s, "level": lv, "direction": d, "pattern": p,
         "price": 150.0, "change_pct": 5.0, "volume_ratio": 2.5}
        for s, lv, d, p in entries
    ]


class TestPromoteA0A1Signals(unittest.TestCase):
    """Unit tests for promote_a0a1_signals."""

    def test_promotes_below_cutoff_with_a1_signal(self):
        ranked = _make_ranked(["AAPL", "GOOG"])
        filtered = _make_filtered_out([
            ("NVDA", ["below_top_n_cutoff"], 3.0),
        ])
        rt = _make_rt_signals([("NVDA", "A1", "LONG", "momentum_breakout")])

        ranked_out, filt_out, promoted, a0a1 = promote_a0a1_signals(
            ranked, filtered, rt,
        )

        self.assertIn("NVDA", promoted)
        self.assertEqual(len(ranked_out), 3)
        nvda_row = next(r for r in ranked_out if r["symbol"] == "NVDA")
        self.assertTrue(nvda_row["rt_promoted"])
        self.assertEqual(nvda_row["rt_level"], "A1")
        self.assertEqual(nvda_row["rt_direction"], "LONG")
        self.assertEqual(nvda_row["score"], 3.0)
        # NVDA should be removed from filtered_out_v2
        self.assertEqual(len(filt_out), 0)

    def test_promotes_a0_signal_same_as_a1(self):
        ranked = _make_ranked(["AAPL"])
        filtered = _make_filtered_out([
            ("TSLA", ["below_top_n_cutoff"], 2.5),
        ])
        rt = _make_rt_signals([("TSLA", "A0", "LONG", "gap_breakout")])

        _, _, promoted, _ = promote_a0a1_signals(ranked, filtered, rt)
        self.assertIn("TSLA", promoted)

    def test_does_not_promote_hard_filtered_symbols(self):
        ranked = _make_ranked(["AAPL"])
        filtered = _make_filtered_out([
            ("BAD", ["low_rvol", "spread_too_wide"], 1.0),
        ])
        rt = _make_rt_signals([("BAD", "A0", "LONG", "fake_breakout")])

        ranked_out, filt_out, promoted, _ = promote_a0a1_signals(
            ranked, filtered, rt,
        )

        self.assertNotIn("BAD", promoted)
        self.assertEqual(len(ranked_out), 1)  # unchanged
        # BAD stays in filtered_out
        self.assertEqual(len(filt_out), 1)

    def test_does_not_duplicate_already_ranked_symbol(self):
        ranked = _make_ranked(["AAPL", "NVDA"])
        filtered = _make_filtered_out([])
        rt = _make_rt_signals([("NVDA", "A1", "LONG", "momentum")])

        ranked_out, _, promoted, _ = promote_a0a1_signals(ranked, filtered, rt)

        self.assertNotIn("NVDA", promoted)
        self.assertEqual(len(ranked_out), 2)  # no duplicate

    def test_noop_when_no_rt_signals(self):
        ranked = _make_ranked(["AAPL", "GOOG"])
        filtered = _make_filtered_out([
            ("NVDA", ["below_top_n_cutoff"], 3.0),
        ])

        ranked_out, filt_out, promoted, a0a1 = promote_a0a1_signals(
            ranked, filtered, [],
        )

        self.assertEqual(len(promoted), 0)
        self.assertEqual(len(ranked_out), 2)
        self.assertEqual(len(filt_out), 1)
        self.assertEqual(len(a0a1), 0)

    def test_noop_when_only_a2_signals(self):
        ranked = _make_ranked(["AAPL"])
        filtered = _make_filtered_out([
            ("NVDA", ["below_top_n_cutoff"], 3.0),
        ])
        rt = [{"symbol": "NVDA", "level": "A2", "direction": "LONG",
               "pattern": "minor", "price": 100, "change_pct": 1,
               "volume_ratio": 1}]

        _, _, promoted, a0a1 = promote_a0a1_signals(ranked, filtered, rt)
        self.assertEqual(len(promoted), 0)
        self.assertEqual(len(a0a1), 0)

    def test_case_insensitive_symbol_matching(self):
        ranked = _make_ranked(["aapl"])
        filtered = _make_filtered_out([
            ("nvda", ["below_top_n_cutoff"], 3.0),
        ])
        rt = _make_rt_signals([("Nvda", "A1", "LONG", "breakout")])

        _, _, promoted, _ = promote_a0a1_signals(ranked, filtered, rt)
        self.assertIn("NVDA", promoted)

    def test_promoted_row_uses_cutoff_price_over_rt(self):
        ranked = _make_ranked(["AAPL"])
        filtered = [
            {"symbol": "NVDA", "filter_reasons": ["below_top_n_cutoff"],
             "score": 3.0, "gap_pct": 1.5, "price": 120.0,
             "confidence_tier": "STANDARD"},
        ]
        rt = [{"symbol": "NVDA", "level": "A1", "direction": "LONG",
               "pattern": "breakout", "price": 130.0, "change_pct": 5.0,
               "volume_ratio": 2.0}]

        ranked_out, _, _, _ = promote_a0a1_signals(ranked, filtered, rt)
        nvda = next(r for r in ranked_out if r["symbol"] == "NVDA")
        # Should use cutoff entry price (120), not RT price (130)
        self.assertEqual(nvda["price"], 120.0)

    def test_promoted_row_uses_rt_price_when_cutoff_has_none(self):
        ranked = _make_ranked(["AAPL"])
        filtered = [
            {"symbol": "NVDA", "filter_reasons": ["below_top_n_cutoff"],
             "score": 3.0, "gap_pct": 1.5,
             "confidence_tier": "STANDARD"},
        ]
        rt = [{"symbol": "NVDA", "level": "A1", "direction": "LONG",
               "pattern": "breakout", "price": 130.0, "change_pct": 5.0,
               "volume_ratio": 2.0}]

        ranked_out, _, _, _ = promote_a0a1_signals(ranked, filtered, rt)
        nvda = next(r for r in ranked_out if r["symbol"] == "NVDA")
        # No price in cutoff entry → falls back to RT price
        self.assertEqual(nvda["price"], 130.0)

    def test_multiple_promotions(self):
        ranked = _make_ranked(["AAPL"])
        filtered = _make_filtered_out([
            ("NVDA", ["below_top_n_cutoff"], 3.0),
            ("TSLA", ["below_top_n_cutoff"], 2.8),
            ("META", ["low_rvol"], 1.0),  # hard-filtered
        ])
        rt = _make_rt_signals([
            ("NVDA", "A1", "LONG", "momentum"),
            ("TSLA", "A0", "SHORT", "reversal"),
            ("META", "A1", "LONG", "breakout"),  # won't promote: hard-filtered
        ])

        ranked_out, filt_out, promoted, _ = promote_a0a1_signals(
            ranked, filtered, rt,
        )

        self.assertEqual(promoted, {"NVDA", "TSLA"})
        self.assertEqual(len(ranked_out), 3)  # AAPL + NVDA + TSLA
        # META still in filtered_out (hard-filtered)
        self.assertEqual(len(filt_out), 1)
        self.assertEqual(filt_out[0]["symbol"], "META")

    def test_not_in_universe_not_promoted(self):
        """Symbol with A0/A1 not in filtered_out at all (not in universe)."""
        ranked = _make_ranked(["AAPL"])
        filtered = _make_filtered_out([])
        rt = _make_rt_signals([("XYZ", "A0", "LONG", "breakout")])

        ranked_out, _, promoted, _ = promote_a0a1_signals(ranked, filtered, rt)
        self.assertNotIn("XYZ", promoted)
        self.assertEqual(len(ranked_out), 1)

    def test_returns_a0a1_map_for_crossref(self):
        ranked = _make_ranked(["AAPL"])
        filtered = _make_filtered_out([])
        rt = _make_rt_signals([
            ("NVDA", "A1", "LONG", "breakout"),
            ("GOOG", "A2", "LONG", "minor"),
        ])

        _, _, _, a0a1_map = promote_a0a1_signals(ranked, filtered, rt)
        self.assertIn("NVDA", a0a1_map)
        self.assertNotIn("GOOG", a0a1_map)  # A2 excluded

    def test_original_lists_not_mutated(self):
        """Ensure the function doesn't mutate the caller's original lists."""
        ranked_orig = _make_ranked(["AAPL"])
        filtered_orig = _make_filtered_out([
            ("NVDA", ["below_top_n_cutoff"], 3.0),
        ])
        rt = _make_rt_signals([("NVDA", "A1", "LONG", "breakout")])

        ranked_copy = copy.deepcopy(ranked_orig)
        filtered_copy = copy.deepcopy(filtered_orig)

        promote_a0a1_signals(ranked_orig, filtered_orig, rt)

        # ranked_v2 is mutated in-place (appended to), which is documented
        # behaviour.  But the original filtered_out list should NOT lose items
        # since the function reassigns the local variable.
        self.assertEqual(len(filtered_orig), len(filtered_copy))


if __name__ == "__main__":
    unittest.main()
