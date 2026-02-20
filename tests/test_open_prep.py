import unittest
from unittest.mock import patch

from open_prep.ai import build_trade_cards
from open_prep.run_open_prep import _extract_time_str, _filter_events_by_cutoff_utc, _sort_macro_events
from open_prep.macro import (
    FMPClient,
    filter_us_events,
    filter_us_high_impact_events,
    filter_us_mid_impact_events,
    macro_bias_score,
)
from open_prep.screen import rank_candidates


class TestOpenPrep(unittest.TestCase):
    def test_filter_events_by_cutoff_utc_keeps_only_earlier_times(self):
        events = [
            {"date": "2026-02-20 13:30:00", "event": "GDP"},
            {"date": "2026-02-20 16:00:00", "event": "Consumer Confidence"},
            {"date": "2026-02-20 20:30:00", "event": "CFTC"},
        ]
        filtered = _filter_events_by_cutoff_utc(events, "16:00:00")
        self.assertEqual([e["event"] for e in filtered], ["GDP", "Consumer Confidence"])

    def test_filter_events_by_cutoff_utc_with_strict_cutoff(self):
        events = [
            {"date": "2026-02-20 13:29:59", "event": "Before"},
            {"date": "2026-02-20 13:30:00", "event": "AtCutoff"},
            {"date": "2026-02-20 13:30:01", "event": "After"},
        ]
        filtered = _filter_events_by_cutoff_utc(events, "13:30:00")
        self.assertEqual([e["event"] for e in filtered], ["Before", "AtCutoff"])

    def test_extract_time_str_supports_hhmm_and_single_digit_hour(self):
        self.assertEqual(_extract_time_str("2026-02-20 14:30"), "14:30:00")
        self.assertEqual(_extract_time_str("2026-02-20T9:30:00Z"), "09:30:00")

    def test_extract_time_str_rejects_invalid_time_values(self):
        self.assertEqual(_extract_time_str("2026-02-20 24:00:00"), "99:99:99")
        self.assertEqual(_extract_time_str("2026-02-20 12:61:00"), "99:99:99")

    def test_sort_macro_events_prioritizes_high_and_open_window(self):
        events = [
            {
                "date": "2026-02-20 20:30:00",
                "event": "CPI YoY",
                "impact": "High",
            },
            {
                "date": "2026-02-20 13:30:00",
                "event": "Retail Sales MoM",
                "impact": "High",
            },
            {
                "date": "2026-02-20 13:30:00",
                "event": "Housing Starts",
                "impact": "Medium",
            },
        ]
        ordered = _sort_macro_events(events)
        self.assertEqual(ordered[0]["event"], "Retail Sales MoM")

    def test_sort_macro_events_uses_relevance_with_same_impact_and_time(self):
        events = [
            {
                "date": "2026-02-20 15:00:00",
                "event": "Consumer Sentiment",
                "impact": "Medium",
            },
            {
                "date": "2026-02-20 15:00:00",
                "event": "Housing Starts",
                "impact": "Medium",
            },
        ]
        ordered = _sort_macro_events(events)
        self.assertEqual(ordered[0]["event"], "Consumer Sentiment")

    def test_filter_us_events_keeps_only_us(self):
        events = [
            {"country": "US", "currency": "USD", "event": "PPI"},
            {"country": "DE", "currency": "EUR", "event": "CPI"},
        ]
        filtered = filter_us_events(events)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["country"], "US")

    def test_filter_us_high_impact_events_combines_both_filters(self):
        events = [
            {"country": "US", "currency": "USD", "event": "PPI"},
            {"country": "US", "currency": "USD", "event": "Housing Starts"},
            {"country": "DE", "currency": "EUR", "event": "PPI"},
        ]
        filtered = filter_us_high_impact_events(events)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["event"], "PPI")

    def test_filter_us_high_impact_events_matches_name_variants(self):
        events = [
            {
                "country": "US",
                "currency": "USD",
                "event": "US Initial Jobless Claims",
            },
            {
                "country": "US",
                "currency": "USD",
                "event": "Philadelphia Fed Business Outlook Survey",
            },
            {
                "country": "US",
                "currency": "USD",
                "event": "Building Permits",
            },
        ]
        filtered = filter_us_high_impact_events(events)
        names = {item["event"] for item in filtered}
        self.assertIn("US Initial Jobless Claims", names)
        self.assertIn("Philadelphia Fed Business Outlook Survey", names)
        self.assertNotIn("Building Permits", names)

    def test_filter_us_mid_impact_events_uses_impact_field(self):
        events = [
            {"country": "US", "currency": "USD", "event": "CFTC Nasdaq 100 speculative net positions", "impact": "Medium"},
            {"country": "US", "currency": "USD", "event": "Michigan Consumer Sentiment", "impact": "Medium"},
            {"country": "US", "currency": "USD", "event": "CFTC Silver speculative net positions", "impact": "Low"},
            {"country": "DE", "currency": "EUR", "event": "ZEW Survey", "impact": "Medium"},
        ]
        filtered = filter_us_mid_impact_events(events)
        self.assertEqual(len(filtered), 1)
        self.assertIn("Michigan", filtered[0]["event"])

    def test_filter_us_high_impact_events_prefers_provider_high_tag(self):
        events = [
            {"country": "US", "currency": "USD", "event": "GDP Growth Rate QoQ", "impact": "High"},
            {"country": "US", "currency": "USD", "event": "GDP Sales QoQ", "impact": "Low"},
        ]
        filtered = filter_us_high_impact_events(events)
        self.assertEqual(len(filtered), 1)
        self.assertIn("GDP Growth", filtered[0]["event"])

    def test_macro_bias_uses_mid_impact_fallback(self):
        events = [
            {
                "country": "US",
                "currency": "USD",
                "event": "ISM Services PMI",
                "impact": "Medium",
                "actual": 53.0,
                "consensus": 51.0,
            }
        ]
        self.assertGreater(macro_bias_score(events), 0.0)

    def test_macro_bias_inflation_hot_is_risk_off(self):
        events = [
            {"country": "US", "currency": "USD", "event": "PPI", "actual": 0.4, "consensus": 0.2},
            {"country": "US", "currency": "USD", "event": "Core CPI", "actual": 3.6, "consensus": 3.4},
        ]
        self.assertLess(macro_bias_score(events), 0.0)

    def test_macro_bias_growth_strong_is_risk_on(self):
        events = [
            {
                "country": "US",
                "currency": "USD",
                "event": "ISM Manufacturing PMI",
                "actual": 53.0,
                "consensus": 51.2,
            },
            {
                "country": "US",
                "currency": "USD",
                "event": "Philadelphia Fed Manufacturing Index",
                "actual": 8.0,
                "consensus": 4.0,
            },
        ]
        self.assertGreater(macro_bias_score(events), 0.0)

    def test_rank_candidates_applies_risk_off_penalty(self):
        quotes = [
            {
                "symbol": "AAA",
                "price": 100,
                "changesPercentage": 3.0,
                "volume": 1_000_000,
                "avgVolume": 500_000,
            }
        ]
        risk_on = rank_candidates(quotes, bias=0.7, top_n=1)[0]["score"]
        risk_off = rank_candidates(quotes, bias=-0.7, top_n=1)[0]["score"]
        self.assertGreater(risk_on, risk_off)

    def test_trade_cards_follow_bias_setup(self):
        ranked = [
            {
                "symbol": "NVDA",
                "score": 4.2,
                "gap_pct": 2.5,
                "rel_volume": 1.8,
            }
        ]
        cards = build_trade_cards(ranked_candidates=ranked, bias=-0.5, top_n=1)
        self.assertEqual(cards[0]["setup_type"], "VWAP-Reclaim only")

    def test_filter_events_by_cutoff_utc_includes_untimed_events(self):
        events = [
            {"date": "2026-02-20 13:30:00", "event": "GDP"},
            {"date": "2026-02-20", "event": "Whole Day"},          # no time component
            {"date": "2026-02-20T13:30:00", "event": "ISO-T GDP"},  # T-separator
            {"date": "2026-02-20 20:30:00", "event": "AfterCutoff"},
        ]
        filtered = _filter_events_by_cutoff_utc(events, "16:00:00")
        names = [e["event"] for e in filtered]
        self.assertIn("GDP", names)
        self.assertIn("Whole Day", names)   # untimed always included
        self.assertIn("ISO-T GDP", names)   # T-separator correctly parsed
        self.assertNotIn("AfterCutoff", names)

    def test_cutoff_excludes_untimed_when_flag_false(self):
        events = [
            {"date": "2026-02-20", "event": "Whole Day"},
            {"date": "2026-02-20 13:30:00", "event": "WithTime"},
        ]
        filtered = _filter_events_by_cutoff_utc(events, "16:00:00", include_untimed=False)
        self.assertEqual([e["event"] for e in filtered], ["WithTime"])

    def test_macro_bias_on_consensus_print_is_neutral(self):
        """An on-consensus release (surprise == 0) must not move the bias."""
        events = [
            {"country": "US", "currency": "USD", "event": "CPI YoY",
             "actual": 3.0, "consensus": 3.0},
            {"country": "US", "currency": "USD", "event": "Nonfarm Payrolls",
             "actual": 200, "consensus": 200},
        ]
        self.assertEqual(macro_bias_score(events), 0.0)

    def test_gdpnow_not_treated_as_high_impact_release(self):
        from open_prep.macro import _is_high_impact_event_name, DEFAULT_HIGH_IMPACT_EVENTS
        self.assertFalse(_is_high_impact_event_name(
            "Atlanta Fed GDPNow", DEFAULT_HIGH_IMPACT_EVENTS
        ))

    def test_get_batch_quotes_uses_stable_batch_quote_endpoint(self):
        client = FMPClient(api_key="test")
        with patch.object(FMPClient, "_get", return_value=[{"symbol": "NVDA"}]) as mock_get:
            quotes = client.get_batch_quotes(["NVDA", "PLTR"])

        mock_get.assert_called_once_with("/stable/batch-quote", {"symbols": "NVDA,PLTR"})
        self.assertEqual(quotes, [{"symbol": "NVDA"}])


if __name__ == "__main__":
    unittest.main()
