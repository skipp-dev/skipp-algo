from datetime import UTC, datetime
import unittest
from unittest.mock import patch

from open_prep.trade_cards import build_trade_cards
from open_prep.run_open_prep import (
    _calculate_atr14_from_eod,
    _extract_time_str,
    _filter_events_by_cutoff_utc,
    _inputs_hash,
    _sort_macro_events,
)
from open_prep.news import build_news_scores, _parse_article_datetime
from open_prep.macro import (
    FMPClient,
    filter_us_events,
    filter_us_high_impact_events,
    filter_us_mid_impact_events,
    macro_bias_with_components,
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

    def test_rank_candidates_applies_news_catalyst_score(self):
        quotes = [
            {
                "symbol": "NVDA",
                "price": 100,
                "changesPercentage": 1.0,
                "volume": 1_000_000,
                "avgVolume": 500_000,
            }
        ]
        base = rank_candidates(quotes, bias=0.0, top_n=1)[0]
        with_news = rank_candidates(quotes, bias=0.0, top_n=1, news_scores={"NVDA": 1.5})[0]
        self.assertAlmostEqual(with_news["score"] - base["score"], 1.5, places=4)
        self.assertEqual(with_news["news_catalyst_score"], 1.5)
        self.assertIn("score_breakdown", with_news)
        self.assertIn("news_component", with_news["score_breakdown"])

    def test_rank_candidates_normalizes_symbol_case_for_news_lookup(self):
        quotes = [
            {
                "symbol": "nvda",
                "price": 100,
                "changesPercentage": 1.0,
                "volume": 1_000_000,
                "avgVolume": 500_000,
            }
        ]
        row = rank_candidates(quotes, bias=0.0, top_n=1, news_scores={"NVDA": 1.25})[0]
        self.assertEqual(row["symbol"], "NVDA")
        self.assertEqual(row["news_catalyst_score"], 1.25)

    def test_rank_candidates_handles_non_numeric_news_score(self):
        quotes = [
            {
                "symbol": "NVDA",
                "price": 100,
                "changesPercentage": 1.0,
                "volume": 1_000_000,
                "avgVolume": 500_000,
            }
        ]
        row = rank_candidates(quotes, bias=0.0, top_n=1, news_scores={"NVDA": "N/A"})[0]
        self.assertEqual(row["news_catalyst_score"], 0.0)

    def test_rank_candidates_emits_long_guardrails(self):
        quotes = [
            {
                "symbol": "PENNY",
                "price": 3.0,
                "changesPercentage": -9.0,
                "volume": 1_000_000,
                "avgVolume": 500_000,
            }
        ]
        row = rank_candidates(quotes, bias=-0.9, top_n=1)[0]
        self.assertFalse(row["long_allowed"])
        self.assertIn("price_below_5", row["no_trade_reason"])
        self.assertIn("macro_risk_off_extreme", row["no_trade_reason"])
        self.assertIn("severe_gap_down", row["no_trade_reason"])

    def test_rank_candidates_risk_off_blocks_missing_rvol(self):
        quotes = [
            {
                "symbol": "THIN",
                "price": 20.0,
                "changesPercentage": 1.0,
                "volume": 0,
                "avgVolume": 0,
            }
        ]
        row = rank_candidates(quotes, bias=-0.9, top_n=1)[0]
        self.assertFalse(row["long_allowed"])
        self.assertIn("macro_risk_off_extreme", row["no_trade_reason"])
        self.assertIn("missing_rvol", row["no_trade_reason"])
        self.assertTrue(row["data_sufficiency"]["low"])
        self.assertTrue(row["data_sufficiency"]["avg_volume_missing"])
        self.assertTrue(row["data_sufficiency"]["rel_volume_missing"])

    def test_rank_candidates_carries_atr_from_quote(self):
        quotes = [
            {
                "symbol": "NVDA",
                "price": 100,
                "changesPercentage": 1.0,
                "volume": 1_000_000,
                "avgVolume": 500_000,
                "atr": 3.25,
            }
        ]
        row = rank_candidates(quotes, bias=0.0, top_n=1)[0]
        self.assertEqual(row["atr"], 3.25)

    def test_build_news_scores_uses_tickers_and_recency_windows(self):
        symbols = ["NVDA", "PLTR"]
        now = datetime(2026, 2, 20, 15, 0, 0, tzinfo=UTC)
        articles = [
            {
                "tickers": "NASDAQ:NVDA",
                "title": "NVIDIA sees strong demand",
                "content": "",
                "date": "2026-02-20 14:30:00",
            },
            {
                "tickers": "NYSE:PLTR",
                "title": "Palantir update",
                "content": "",
                "date": "2026-02-19 20:00:00",
            },
        ]
        scores, metrics = build_news_scores(symbols=symbols, articles=articles, now_utc=now)
        self.assertGreater(scores["NVDA"], scores["PLTR"])
        self.assertEqual(metrics["NVDA"]["mentions_2h"], 1)
        self.assertEqual(metrics["PLTR"]["mentions_24h"], 1)

    def test_news_score_does_not_double_count_2h_articles(self):
        """A single article from < 2h ago must score exactly 0.5, not 0.65."""
        symbols = ["AAPL"]
        now = datetime(2026, 2, 20, 15, 0, 0, tzinfo=UTC)
        articles = [
            {
                "tickers": "NASDAQ:AAPL",
                "title": "Apple news",
                "content": "",
                "date": "2026-02-20 14:00:00",  # 1h ago → in both 2h and 24h
            },
        ]
        scores, metrics = build_news_scores(symbols=symbols, articles=articles, now_utc=now)
        # 2h article: 0.5 only; should NOT include extra 0.15 from 24h overlap
        self.assertAlmostEqual(scores["AAPL"], 0.5, places=4)
        self.assertEqual(metrics["AAPL"]["mentions_2h"], 1)
        self.assertEqual(metrics["AAPL"]["mentions_24h"], 1)

    def test_parse_article_datetime_supports_iso_z_and_offset(self):
        dt_z = _parse_article_datetime("2026-02-20T14:30:00.123Z")
        self.assertIsNotNone(dt_z)
        assert dt_z is not None
        self.assertEqual(dt_z.tzinfo, UTC)
        self.assertEqual((dt_z.hour, dt_z.minute), (14, 30))

        dt_offset = _parse_article_datetime("2026-02-20T15:30:00+01:00")
        self.assertIsNotNone(dt_offset)
        assert dt_offset is not None
        self.assertEqual(dt_offset.tzinfo, UTC)
        self.assertEqual((dt_offset.hour, dt_offset.minute), (14, 30))

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
        self.assertIn("long_allowed", cards[0]["context"])
        self.assertIn("no_trade_reason", cards[0]["context"])

    def test_trade_cards_include_atr_trail_stop_profiles(self):
        ranked = [
            {
                "symbol": "NVDA",
                "score": 4.2,
                "gap_pct": 2.5,
                "rel_volume": 1.8,
                "atr": 3.2,
                "entry_price": 200.0,
            }
        ]
        card = build_trade_cards(ranked_candidates=ranked, bias=0.1, top_n=1)[0]
        trail = card["trail_stop_atr"]
        self.assertEqual(trail["atr"], 3.2)
        self.assertEqual(trail["distances"]["tight"], 3.2)
        self.assertEqual(trail["distances"]["balanced"], 4.8)
        self.assertEqual(trail["distances"]["wide"], 6.4)
        self.assertEqual(trail["stop_reference_source"], "entry_price")
        self.assertEqual(trail["stop_reference_price"], 200.0)
        self.assertEqual(trail["stop_prices"]["tight"], 196.8)
        self.assertEqual(trail["stop_prices"]["balanced"], 195.2)
        self.assertEqual(trail["stop_prices"]["wide"], 193.6)

    def test_trade_cards_atr_trail_stop_fallback_when_missing(self):
        ranked = [
            {
                "symbol": "PLTR",
                "score": 2.1,
                "gap_pct": 1.2,
                "rel_volume": 1.1,
            }
        ]
        card = build_trade_cards(ranked_candidates=ranked, bias=0.0, top_n=1)[0]
        trail = card["trail_stop_atr"]
        self.assertEqual(trail["atr"], 0.0)
        self.assertEqual(trail["distances"]["tight"], 0.0)
        self.assertIsNone(trail["stop_reference_price"])
        self.assertIsNone(trail["stop_prices"]["tight"])
        self.assertIn("unavailable", trail["note"].lower())
        # Regression: stop_reference_source must be None (not the string "none")
        # so that JSON consumers get null and truthiness checks work as expected.
        self.assertIsNone(trail["stop_reference_source"])

    def test_trade_cards_use_vwap_as_stop_reference_when_entry_missing(self):
        ranked = [
            {
                "symbol": "AMD",
                "score": 1.5,
                "gap_pct": 1.1,
                "rel_volume": 1.4,
                "atr": 2.0,
                "vwap": 150.0,
            }
        ]
        card = build_trade_cards(ranked_candidates=ranked, bias=0.0, top_n=1)[0]
        trail = card["trail_stop_atr"]
        self.assertEqual(trail["stop_reference_source"], "vwap")
        self.assertEqual(trail["stop_prices"]["tight"], 148.0)

    def test_trade_cards_handles_non_numeric_gap_pct(self):
        ranked = [
            {
                "symbol": "AMD",
                "score": 1.5,
                "gap_pct": "N/A",
                "rel_volume": 1.4,
            }
        ]
        card = build_trade_cards(ranked_candidates=ranked, bias=0.0, top_n=1)[0]
        self.assertIn("Break and hold above opening range high OR", card["entry_trigger"])

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

    def test_filter_events_by_cutoff_utc_rejects_invalid_cutoff(self):
        with self.assertRaises(ValueError):
            _filter_events_by_cutoff_utc([], "invalid")

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

    def test_calculate_atr14_from_eod_returns_non_zero_for_valid_candles(self):
        candles = [
            {"date": "2026-02-01", "high": 10.0, "low": 9.0, "close": 9.5},
            {"date": "2026-02-02", "high": 10.5, "low": 9.2, "close": 10.2},
            {"date": "2026-02-03", "high": 11.0, "low": 9.8, "close": 10.7},
            {"date": "2026-02-04", "high": 11.3, "low": 10.1, "close": 11.1},
            {"date": "2026-02-05", "high": 11.6, "low": 10.4, "close": 11.0},
        ]
        self.assertGreater(_calculate_atr14_from_eod(candles), 0.0)

    def test_inputs_hash_is_deterministic(self):
        payload = {"symbols": ["NVDA", "PLTR"], "top": 10}
        self.assertEqual(_inputs_hash(payload), _inputs_hash(payload))

    def test_macro_score_components_schema_contract(self):
        events = [
            {
                "country": "US",
                "date": "2026-02-20",
                "event": "Gross Domestic Product QoQ (Q4)",
                "actual": 1.4,
                "consensus": 2.8,
                "impact": "High",
            },
            {
                "country": "US",
                "date": "2026-02-20",
                "event": "GDP Growth Rate QoQ (Q4)",
                "actual": 1.4,
                "consensus": 3.5,
                "impact": "High",
            },
            {
                "country": "US",
                "date": "2026-02-20",
                "event": "Core PCE Price Index MoM (Dec)",
                "actual": 0.4,
                "estimate": 0.2,
                "impact": "High",
            },
        ]
        analysis = macro_bias_with_components(events)
        components = analysis.get("score_components", [])
        self.assertGreater(len(components), 0)

        required = {
            "canonical_event",
            "consensus_value",
            "consensus_field",
            "surprise",
            "weight",
            "contribution",
            "data_quality_flags",
        }
        for component in components:
            self.assertTrue(required.issubset(component.keys()))

        gdp_component = next(c for c in components if c.get("canonical_event") == "gdp_qoq")
        self.assertIn("dedup", gdp_component)
        self.assertTrue(gdp_component["dedup"]["was_deduped"])

    def test_ranked_candidates_schema_contract(self):
        quotes = [
            {
                "symbol": "THIN",
                "price": 20.0,
                "changesPercentage": 1.0,
                "volume": 0,
                "avgVolume": 0,
            }
        ]
        row = rank_candidates(quotes, bias=-0.9, top_n=1)[0]

        required = {
            "allowed_setups",
            "max_trades",
            "data_sufficiency",
            "no_trade_reason",
            "score_breakdown",
        }
        self.assertTrue(required.issubset(row.keys()))

        self.assertTrue({"low", "avg_volume_missing", "rel_volume_missing"}.issubset(row["data_sufficiency"].keys()))
        self.assertTrue(
            {
                "gap_component",
                "rvol_component",
                "macro_component",
                "news_component",
                "liquidity_penalty",
                "risk_off_penalty",
            }.issubset(row["score_breakdown"].keys())
        )


if __name__ == "__main__":
    unittest.main()
