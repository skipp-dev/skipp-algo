"""§13-A regression: a gap-up GAP_FADE card is a SHORT and must not carry a
long-side (below-entry) trailing stop or long-side S/R targets.

The playbook engine emits GAP_FADE on a gap-UP as a short ("short the failed
break / VWAP rejection"). ``build_trade_cards`` previously computed the ATR
trailing stop unconditionally below the reference and hardcoded ``direction=
"long"`` for S/R targets, so a short card showed a stop below entry (no upside
protection) and upside targets — contradicting its own "Short …" entry trigger.
"""

import unittest

from open_prep.trade_cards import _card_direction, build_trade_cards


class TestCardDirection(unittest.TestCase):
    def test_gap_up_fade_is_short(self):
        self.assertEqual(_card_direction({"playbook": "GAP_FADE"}, 4.0), "short")

    def test_gap_down_fade_is_long_reclaim(self):
        self.assertEqual(_card_direction({"playbook": "GAP_FADE"}, -4.0), "long")

    def test_gap_and_go_is_long(self):
        self.assertEqual(_card_direction({"playbook": "GAP_AND_GO"}, 4.0), "long")

    def test_no_playbook_defaults_long(self):
        self.assertEqual(_card_direction(None, 4.0), "long")


class TestTradeCardsShortDirection(unittest.TestCase):
    def _gap_up_fade_row(self):
        return {
            "symbol": "XYZ",
            "price": 100.0,
            "entry_price": 100.0,
            "atr": 2.0,
            "gap_pct": 4.0,
            "gap_available": True,
            "playbook": {
                "playbook": "GAP_FADE",
                "entry_trigger": "Short on failed break / VWAP rejection.",
                "invalidation": "New HOD above entry / ORH breakout.",
            },
        }

    def test_short_card_trailing_stop_is_above_reference(self):
        card = build_trade_cards([self._gap_up_fade_row()], bias=0.2, top_n=1)[0]
        self.assertEqual(card["direction"], "short")
        trail = card["trail_stop_atr"]
        self.assertEqual(trail["direction"], "short")
        ref = trail["stop_reference_price"]
        # Every profile's stop must sit ABOVE the reference for a short.
        for profile in ("tight", "mid", "wide", "balanced"):
            self.assertGreater(
                trail["stop_prices"][profile], ref,
                f"{profile} stop must be above entry for a short",
            )
        # atr=2.0 → tight (×1.0) stop at reference + 2.0
        self.assertEqual(trail["stop_prices"]["tight"], 102.0)

    def test_long_card_trailing_stop_unchanged(self):
        # A gap-up GAP_AND_GO stays long: stop below reference (regression guard).
        row = self._gap_up_fade_row()
        row["playbook"] = {"playbook": "GAP_AND_GO", "entry_trigger": "Break ORH."}
        card = build_trade_cards([row], bias=0.2, top_n=1)[0]
        self.assertEqual(card["direction"], "long")
        trail = card["trail_stop_atr"]
        self.assertEqual(trail["direction"], "long")
        self.assertEqual(trail["stop_prices"]["tight"], 98.0)

    def test_short_card_sr_targets_are_downside(self):
        # 60 declining daily bars → S/R computed short-side: targets below price.
        bars = [
            {
                "high": 160.0 - i,
                "low": 158.0 - i,
                "close": 159.0 - i,
                "open": 159.0 - i,
                "volume": 1_000_000,
            }
            for i in range(60)
        ]
        row = self._gap_up_fade_row()
        row["symbol"] = "AAA"
        row["price"] = 100.0
        card = build_trade_cards(
            [row], bias=0.2, top_n=1, daily_bars={"AAA": bars}
        )[0]
        sr = card["key_levels"]["sr_targets"]
        self.assertIsNotNone(sr)
        # Short targets sit below entry; the short stop sits above entry.
        self.assertLess(sr["target_1"], 100.0)
        self.assertGreater(sr["stop_loss"], 100.0)


if __name__ == "__main__":
    unittest.main()
