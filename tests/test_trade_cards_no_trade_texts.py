"""TC1 regression: a NO_TRADE trade card must not carry a live entry trigger.

Before the fix, ``build_trade_cards`` excluded ``NO_TRADE`` from the playbook
override, so a NO_TRADE card kept the bias/gap default entry (e.g. a gap-up
continuation trigger) while its ``setup_type``/``note`` said "No Trade" — an
operator-facing self-contradiction. The playbook engine already supplies the
correct no-trade texts; the card must use them.
"""

import unittest

from open_prep.trade_cards import build_trade_cards


class TestTradeCardsNoTradeTexts(unittest.TestCase):
    def test_no_trade_card_uses_engine_no_trade_texts(self):
        # gap_available + gap_pct >= 1.0 would otherwise yield the gap-up
        # continuation entry; a NO_TRADE playbook must override it.
        ranked = [
            {
                "symbol": "NVDA",
                "score": 4.2,
                "gap_pct": 3.0,
                "gap_available": True,
                "playbook": {
                    "playbook": "NO_TRADE",
                    "entry_trigger": "No trade: conditions do not meet playbook criteria.",
                    "invalidation": "N/A — no trade selected.",
                },
            }
        ]
        card = build_trade_cards(ranked_candidates=ranked, bias=0.5, top_n=1)[0]

        self.assertEqual(
            card["entry_trigger"],
            "No trade: conditions do not meet playbook criteria.",
        )
        self.assertEqual(card["invalidation"], "N/A — no trade selected.")
        # The bias/gap default must NOT survive on a NO_TRADE card.
        self.assertNotIn("gap-up continuation", card["entry_trigger"])
        self.assertNotIn("opening range high", card["entry_trigger"])

    def test_actionable_playbook_still_overrides(self):
        # Guardrail: removing the NO_TRADE exclusion must not disturb the
        # override for a real playbook.
        ranked = [
            {
                "symbol": "AMD",
                "score": 3.1,
                "gap_pct": 2.0,
                "gap_available": True,
                "playbook": {
                    "playbook": "GAP_AND_GO",
                    "entry_trigger": "Enter on break + hold above ORH.",
                    "invalidation": "Close below VWAP after entry.",
                },
            }
        ]
        card = build_trade_cards(ranked_candidates=ranked, bias=0.5, top_n=1)[0]
        self.assertEqual(card["entry_trigger"], "Enter on break + hold above ORH.")
        self.assertEqual(card["invalidation"], "Close below VWAP after entry.")


if __name__ == "__main__":
    unittest.main()
