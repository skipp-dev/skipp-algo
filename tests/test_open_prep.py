from datetime import UTC, datetime, date, timedelta
from pathlib import Path
import io
import json
import os
import tempfile
import unittest
import urllib.error
from unittest.mock import MagicMock, patch
import argparse

from open_prep.trade_cards import build_trade_cards
import open_prep.run_open_prep as run_open_prep
from open_prep.run_open_prep import (
    GAP_MODE_OFF,
    GAP_MODE_PREMARKET_INDICATIVE,
    GAP_MODE_RTH_OPEN,
    GAP_SCOPE_DAILY,
    GAP_SCOPE_STRETCH_ONLY,
    _build_runtime_status,
    _calculate_atr14_from_eod,
    _fetch_symbol_atr,
    _load_atr_cache,
    _save_atr_cache,
    _extract_time_str,
    _filter_events_by_cutoff_utc,
    _inputs_hash,
    _is_gap_day,
    _parse_bar_dt_utc,
    _sort_macro_events,
    _to_iso_utc_from_epoch,
    apply_gap_mode_to_quotes,
    build_gap_scanner,
)
from open_prep.news import build_news_scores, _parse_article_datetime
from open_prep.screen import classify_long_gap, compute_gap_warn_flags, rank_candidates
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
    def test_build_runtime_status_no_warnings(self):
        status = _build_runtime_status(news_fetch_error=None, atr_fetch_errors={}, fatal_stage=None)
        self.assertFalse(status["degraded_mode"])
        self.assertIsNone(status["fatal_stage"])
        self.assertEqual(status["warnings"], [])

    def test_build_runtime_status_with_news_failure(self):
        status = _build_runtime_status(
            news_fetch_error="news endpoint timeout",
            atr_fetch_errors={},
            fatal_stage=None,
        )
        self.assertTrue(status["degraded_mode"])
        self.assertEqual(status["fatal_stage"], None)
        self.assertEqual(len(status["warnings"]), 1)
        self.assertEqual(status["warnings"][0]["stage"], "news_fetch")
        self.assertEqual(status["warnings"][0]["code"], "DATA_SOURCE_DEGRADED")

    def test_build_runtime_status_with_atr_partial_data(self):
        status = _build_runtime_status(
            news_fetch_error=None,
            atr_fetch_errors={"nvda": "timeout", "amd": "503"},
            fatal_stage=None,
        )
        self.assertTrue(status["degraded_mode"])
        self.assertEqual(status["fatal_stage"], None)
        self.assertEqual(len(status["warnings"]), 1)
        self.assertEqual(status["warnings"][0]["stage"], "atr_fetch")
        self.assertEqual(status["warnings"][0]["code"], "PARTIAL_DATA")
        self.assertEqual(status["warnings"][0]["symbols"], ["AMD", "NVDA"])

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
        self.assertAlmostEqual(with_news["score"] - base["score"], 1.2, places=4)
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

    def test_rank_candidates_risk_off_blocks_even_with_valid_rvol(self):
        """Regression: extreme risk-off should block longs regardless of data sufficiency."""
        quotes = [
            {
                "symbol": "NVDA",
                "price": 100.0,
                "changesPercentage": 3.0,
                "volume": 1_200_000,
                "avgVolume": 600_000,
            }
        ]
        row = rank_candidates(quotes, bias=-0.875, top_n=1)[0]
        self.assertFalse(row["long_allowed"])
        self.assertIn("macro_risk_off_extreme", row["no_trade_reason"])
        self.assertFalse(row["data_sufficiency"]["low"])

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

    def test_latest_article_utc_prefers_later_datetime_regardless_of_microseconds(self):
        """BUG-FIX regression: ISO string comparison breaks when one datetime has
        microseconds. '.' (ASCII 46) > '+' (ASCII 43), so '14:30:00.123456+00:00'
        would compare as *later* than '15:30:00+00:00' under naive string ordering.
        Post-fix: datetime objects are compared, giving the correct result."""
        symbols = ["NVDA"]
        now = datetime(2026, 2, 20, 16, 0, 0, tzinfo=UTC)
        articles = [
            # Earlier article — has microseconds in timestamp
            {
                "tickers": "NASDAQ:NVDA",
                "title": "NVIDIA morning note",
                "content": "",
                "date": "2026-02-20T14:30:00.654321Z",  # 14:30, with microseconds
            },
            # Later article — no microseconds
            {
                "tickers": "NASDAQ:NVDA",
                "title": "NVIDIA afternoon update",
                "content": "",
                "date": "2026-02-20T15:30:00Z",          # 15:30, no microseconds
            },
        ]
        _, metrics = build_news_scores(symbols=symbols, articles=articles, now_utc=now)
        latest = metrics["NVDA"]["latest_article_utc"]
        self.assertIsNotNone(latest)
        # The 15:30 article must be recognised as the latest, not 14:30 with µs.
        assert latest is not None
        self.assertIn("15:30", latest)

    def test_future_dated_articles_excluded_from_recency_windows(self):
        """BUG-FIX regression: articles dated in the future (e.g. due to
        timezone confusion in the FMP API) must not inflate 24h / 2h mention
        counts. They should still appear in mentions_total."""
        symbols = ["PLTR"]
        now = datetime(2026, 2, 20, 15, 0, 0, tzinfo=UTC)
        articles = [
            {
                "tickers": "NYSE:PLTR",
                "title": "Palantir future event",
                "content": "",
                "date": "2026-02-20T16:00:00Z",  # 1h in the future
            },
        ]
        _, metrics = build_news_scores(symbols=symbols, articles=articles, now_utc=now)
        self.assertEqual(metrics["PLTR"]["mentions_total"], 1)    # counted as mention
        self.assertEqual(metrics["PLTR"]["mentions_24h"], 0)       # but NOT in 24h window
        self.assertEqual(metrics["PLTR"]["mentions_2h"], 0)        # and NOT in 2h window

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

    def test_get_batch_aftermarket_trade_uses_stable_endpoint(self):
        client = FMPClient(api_key="test")
        with patch.object(FMPClient, "_get", return_value=[{"symbol": "NVDA", "price": 100.0}]) as mock_get:
            rows = client.get_batch_aftermarket_trade(["NVDA", "PLTR"])

        mock_get.assert_called_once_with("/stable/batch-aftermarket-trade", {"symbols": "NVDA,PLTR"})
        self.assertEqual(rows, [{"symbol": "NVDA", "price": 100.0}])

    def test_get_biggest_gainers_and_losers_use_stable_endpoints(self):
        client = FMPClient(api_key="test")
        with patch.object(FMPClient, "_get", side_effect=[[{"symbol": "AAA"}], [{"symbol": "BBB"}]]) as mock_get:
            gainers = client.get_biggest_gainers()
            losers = client.get_biggest_losers()

        self.assertEqual(gainers, [{"symbol": "AAA"}])
        self.assertEqual(losers, [{"symbol": "BBB"}])
        self.assertEqual(mock_get.call_args_list[0].args, ("/stable/biggest-gainers", {}))
        self.assertEqual(mock_get.call_args_list[1].args, ("/stable/biggest-losers", {}))

    def test_get_eod_bulk_uses_stable_endpoint(self):
        client = FMPClient(api_key="test")
        with patch.object(FMPClient, "_get", return_value=[{"symbol": "NVDA", "date": "2026-02-20"}]) as mock_get:
            rows = client.get_eod_bulk(datetime(2026, 2, 20, tzinfo=UTC).date())

        mock_get.assert_called_once_with("/stable/eod-bulk", {"date": "2026-02-20"})
        self.assertEqual(rows, [{"symbol": "NVDA", "date": "2026-02-20"}])

    def test_fmp_client_get_retries_transient_http_error(self):
        client = FMPClient(api_key="test", retry_attempts=3, retry_backoff_seconds=0.01)

        transient = urllib.error.HTTPError(
            url="https://example.invalid",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=io.BytesIO(b'{"message":"temporary"}'),
        )
        response = MagicMock()
        response.read.return_value = b"[]"
        context_manager = MagicMock()
        context_manager.__enter__.return_value = response
        context_manager.__exit__.return_value = False

        with (
            patch("open_prep.macro.urlopen", side_effect=[transient, context_manager]) as mock_urlopen,
            patch("open_prep.macro.time.sleep") as mock_sleep,
        ):
            data = client._get("/stable/economic-calendar", {"from": "2026-02-20", "to": "2026-02-21"})

        self.assertEqual(data, [])
        self.assertEqual(mock_urlopen.call_count, 2)
        mock_sleep.assert_called_once()

    def test_fmp_client_get_does_not_retry_non_transient_http_error(self):
        client = FMPClient(api_key="test", retry_attempts=3, retry_backoff_seconds=0.01)

        non_transient = urllib.error.HTTPError(
            url="https://example.invalid",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io.BytesIO(b'{"message":"bad request"}'),
        )

        with (
            patch("open_prep.macro.urlopen", side_effect=non_transient) as mock_urlopen,
            patch("open_prep.macro.time.sleep") as mock_sleep,
        ):
            with self.assertRaises(RuntimeError):
                client._get("/stable/economic-calendar", {"from": "2026-02-20", "to": "2026-02-21"})

        self.assertEqual(mock_urlopen.call_count, 1)
        mock_sleep.assert_not_called()

    def test_calculate_atr14_from_eod_returns_non_zero_for_valid_candles(self):
        # We need at least 15 candles (14 for initial SMA + 1 prior close) to calculate RMA ATR
        candles = [
            {"date": f"2026-02-{i:02d}", "high": 10.0 + i*0.1, "low": 9.0 + i*0.1, "close": 9.5 + i*0.1}
            for i in range(1, 25)
        ]
        atr = _calculate_atr14_from_eod(candles)
        self.assertGreater(atr, 0.0)
        self.assertIsInstance(atr, float)

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

    def test_gap_mode_premarket_indicative_enriches_gap_fields(self):
        quotes = [
            {
                "symbol": "NVDA",
                "price": 104.0,
                "preMarketPrice": 105.0,
                "previousClose": 100.0,
                "timestamp": 1771842600,  # 2026-02-23T10:30:00Z
            }
        ]
        run_dt = datetime(2026, 2, 23, 10, 30, tzinfo=UTC)  # Monday, 05:30 ET
        enriched = apply_gap_mode_to_quotes(
            quotes,
            run_dt_utc=run_dt,
            gap_mode=GAP_MODE_PREMARKET_INDICATIVE,
        )
        row = enriched[0]
        self.assertAlmostEqual(row["gap_pct"], 5.0, places=6)
        self.assertEqual(row["gap_type"], GAP_MODE_PREMARKET_INDICATIVE)
        self.assertTrue(row["gap_available"])
        self.assertEqual(row["gap_mode_selected"], GAP_MODE_PREMARKET_INDICATIVE)
        self.assertEqual(row["gap_price_source"], "premarket")
        self.assertIsNotNone(row["gap_from_ts"])
        self.assertEqual(row["gap_to_ts"], "2026-02-23T10:30:00+00:00")

    def test_to_iso_utc_from_epoch_accepts_milliseconds(self):
        # 2026-02-23T10:30:00Z in milliseconds
        ms_epoch = 1771842600000
        iso = _to_iso_utc_from_epoch(ms_epoch)
        self.assertEqual(iso, "2026-02-23T10:30:00+00:00")

    def test_parse_bar_dt_utc_naive_treated_as_utc_when_env_set(self):
        bar = {"date": "2026-02-23 09:00:00"}
        with patch.dict("os.environ", {"OPEN_PREP_INTRADAY_NAIVE_TZ": "UTC"}, clear=False):
            parsed = _parse_bar_dt_utc(bar)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.isoformat(), "2026-02-23T09:00:00+00:00")

    def test_gap_mode_premarket_spot_without_timestamp_is_stale(self):
        quotes = [
            {
                "symbol": "NVDA",
                "price": 105.0,
                "previousClose": 100.0,
            }
        ]
        run_dt = datetime(2026, 2, 23, 10, 30, tzinfo=UTC)  # Monday premarket
        enriched = apply_gap_mode_to_quotes(
            quotes,
            run_dt_utc=run_dt,
            gap_mode=GAP_MODE_PREMARKET_INDICATIVE,
        )
        row = enriched[0]
        self.assertEqual(row["gap_type"], GAP_MODE_OFF)
        self.assertFalse(row["gap_available"])
        self.assertEqual(row["gap_price_source"], "spot")
        self.assertEqual(row["gap_reason"], "stale_quote_unknown_timestamp")

    def test_gap_mode_premarket_without_quote_timestamp_is_unavailable(self):
        quotes = [
            {
                "symbol": "NVDA",
                "preMarketPrice": 105.0,
                "previousClose": 100.0,
            }
        ]
        run_dt = datetime(2026, 2, 23, 10, 30, tzinfo=UTC)  # Monday premarket
        enriched = apply_gap_mode_to_quotes(
            quotes,
            run_dt_utc=run_dt,
            gap_mode=GAP_MODE_PREMARKET_INDICATIVE,
        )
        row = enriched[0]
        self.assertEqual(row["gap_type"], GAP_MODE_OFF)
        self.assertFalse(row["gap_available"])
        self.assertEqual(row["gap_price_source"], "premarket")
        self.assertEqual(row["gap_reason"], "missing_quote_timestamp")
        self.assertIsNone(row["gap_to_ts"])

    def test_gap_mode_rth_open_requires_monday_open_time(self):
        quotes = [{"symbol": "NVDA", "open": 103.0, "previousClose": 100.0}]
        run_dt = datetime(2026, 2, 23, 13, 0, tzinfo=UTC)  # Monday, 08:00 ET (pre-open)
        enriched = apply_gap_mode_to_quotes(quotes, run_dt_utc=run_dt, gap_mode=GAP_MODE_RTH_OPEN)
        row = enriched[0]
        self.assertEqual(row["gap_type"], GAP_MODE_OFF)
        self.assertFalse(row["gap_available"])
        self.assertEqual(row["gap_reason"], "rth_open_unavailable")

    def test_gap_mode_off_forces_zero_gap(self):
        quotes = [{"symbol": "NVDA", "preMarketPrice": 105.0, "previousClose": 100.0}]
        run_dt = datetime(2026, 2, 23, 11, 0, tzinfo=UTC)
        enriched = apply_gap_mode_to_quotes(quotes, run_dt_utc=run_dt, gap_mode=GAP_MODE_OFF)
        row = enriched[0]
        self.assertEqual(row["gap_pct"], 0.0)
        self.assertEqual(row["gap_type"], GAP_MODE_OFF)
        self.assertFalse(row["gap_available"])

    def test_rank_candidates_ignores_gap_when_unavailable(self):
        quotes = [
            {
                "symbol": "AAA",
                "price": 100.0,
                "gap_pct": 7.5,
                "gap_available": False,
                "volume": 1_000_000,
                "avgVolume": 500_000,
            }
        ]
        row = rank_candidates(quotes, bias=0.0, top_n=1)[0]
        self.assertEqual(row["score_breakdown"]["gap_component"], 0.0)
        self.assertFalse(row["gap_available"])

    def test_trade_cards_uses_neutral_trigger_when_gap_not_available(self):
        """When gap_available is False the entry trigger must fall back to the
        neutral wording regardless of how large the raw gap_pct value is.
        Previously, a positive gap_pct (e.g. from changesPercentage used as a
        fallback when previousClose is missing) could incorrectly produce the
        'gap-up continuation' trigger even though the gap was unvalidated."""
        ranked = [
            {
                "symbol": "NVDA",
                "score": 3.0,
                "gap_pct": 3.5,       # positive gap, but flagged as unavailable
                "gap_available": False,
                "rel_volume": 1.5,
            }
        ]
        card = build_trade_cards(ranked_candidates=ranked, bias=0.3, top_n=1)[0]
        # Must NOT show gap-up continuation because gap_available is False
        self.assertNotIn("gap-up continuation", card["entry_trigger"])
        # Must fall back to the neutral trigger that contains "OR"
        self.assertIn("OR", card["entry_trigger"])

    def test_trade_cards_gap_down_trigger_requires_gap_available(self):
        """Similarly, a negative raw gap_pct must not produce the gap-down
        (VWAP reclaim) trigger when gap_available is False."""
        ranked = [
            {
                "symbol": "AMD",
                "score": 1.5,
                "gap_pct": -2.5,      # negative gap, but unavailable
                "gap_available": False,
                "rel_volume": 1.2,
            }
        ]
        card = build_trade_cards(ranked_candidates=ranked, bias=0.0, top_n=1)[0]
        self.assertNotIn("VWAP reclaim and hold", card["entry_trigger"])
        self.assertIn("OR", card["entry_trigger"])

    def test_data_sufficiency_low_set_on_neutral_day_with_missing_volume(self):
        """Regression: data_sufficiency.low must be True whenever avg_volume or
        rel_volume is missing, even on a neutral-bias day (not only when bias <= -0.75).
        Previously the flag was only set inside the risk-off block, leading to an
        inconsistency where data_sufficiency.rel_volume_missing was True but low was False."""
        quotes = [
            {
                "symbol": "THIN",
                "price": 20.0,
                "changesPercentage": 1.0,
                "volume": 0,
                "avgVolume": 0,
            }
        ]
        row = rank_candidates(quotes, bias=0.0, top_n=1)[0]
        self.assertTrue(row["data_sufficiency"]["low"])
        self.assertTrue(row["data_sufficiency"]["avg_volume_missing"])
        self.assertTrue(row["data_sufficiency"]["rel_volume_missing"])
        # On a neutral day, longs are still allowed (rvol gate only activates at risk-off extreme)
        self.assertTrue(row["long_allowed"])
        self.assertNotIn("missing_rvol", row["no_trade_reason"])

    def test_gap_mode_not_monday_returns_not_first_session_after_break(self):
        """Non-gap sessions (STRETCH_ONLY scope) must return gap_reason='scope_stretch_only'
        and gap_available=False on normal weekdays."""
        for weekday_offset, label in ((1, "Tuesday"), (2, "Wednesday")):
            with self.subTest(day=label):
                run_dt = datetime(2026, 2, 23, 11, 0, tzinfo=UTC) + timedelta(days=weekday_offset)
                quotes = [{
                    "symbol": "NVDA",
                    "preMarketPrice": 105.0,
                    "previousClose": 100.0,
                    "timestamp": int(run_dt.timestamp()),
                }]
                enriched = apply_gap_mode_to_quotes(
                    quotes, run_dt_utc=run_dt, gap_mode=GAP_MODE_PREMARKET_INDICATIVE,
                    gap_scope=GAP_SCOPE_STRETCH_ONLY,
                )
                row = enriched[0]
                self.assertFalse(row["gap_available"])
                self.assertEqual(row["gap_reason"], "scope_stretch_only")
                self.assertEqual(row["gap_scope"], GAP_SCOPE_STRETCH_ONLY)
                self.assertIn("overnight_gap_pct", row)
                self.assertIn("overnight_gap_source", row)

    def test_gap_mode_premarket_handles_tuesday_after_monday_holiday(self):
        """Presidents Day 2026 is Monday (2026-02-16), so Tuesday 2026-02-17
        must be treated as the first tradable session after a non-trading stretch."""
        quotes = [
            {
                "symbol": "NVDA",
                "preMarketPrice": 105.0,
                "previousClose": 100.0,
                "timestamp": 1771324200,  # 2026-02-17T10:30:00Z (05:30 ET)
            }
        ]
        run_dt = datetime(2026, 2, 17, 10, 30, tzinfo=UTC)  # Tuesday after Presidents Day
        enriched = apply_gap_mode_to_quotes(
            quotes,
            run_dt_utc=run_dt,
            gap_mode=GAP_MODE_PREMARKET_INDICATIVE,
        )
        row = enriched[0]
        self.assertTrue(row["gap_available"])
        self.assertEqual(row["gap_type"], GAP_MODE_PREMARKET_INDICATIVE)
        self.assertAlmostEqual(row["gap_pct"], 5.0, places=6)
        self.assertEqual(row["gap_reason"], "ok")
        self.assertIn("2026-02-13", row["gap_from_ts"])  # prior trading day Friday close

    def test_gap_mode_rth_open_handles_tuesday_after_monday_holiday(self):
        quotes = [
            {
                "symbol": "NVDA",
                "open": 104.0,
                "previousClose": 100.0,
            }
        ]
        run_dt = datetime(2026, 2, 17, 14, 40, tzinfo=UTC)  # 09:40 ET, post-open
        enriched = apply_gap_mode_to_quotes(
            quotes,
            run_dt_utc=run_dt,
            gap_mode=GAP_MODE_RTH_OPEN,
        )
        row = enriched[0]
        self.assertTrue(row["gap_available"])
        self.assertEqual(row["gap_type"], GAP_MODE_RTH_OPEN)
        self.assertAlmostEqual(row["gap_pct"], 4.0, places=6)
        self.assertEqual(row["gap_reason"], "ok")


class TestIsGapDay(unittest.TestCase):
    """Tests for the _is_gap_day helper."""

    def test_daily_scope_every_weekday(self):
        from datetime import date
        # Mon 2026-02-23 through Fri 2026-02-27
        for day_offset in range(5):
            d = date(2026, 2, 23) + timedelta(days=day_offset)
            self.assertTrue(_is_gap_day(d, GAP_SCOPE_DAILY), f"{d} should be gap day in DAILY scope")

    def test_daily_scope_weekend_excluded(self):
        from datetime import date
        sat = date(2026, 2, 28)
        sun = date(2026, 3, 1)
        self.assertFalse(_is_gap_day(sat, GAP_SCOPE_DAILY))
        self.assertFalse(_is_gap_day(sun, GAP_SCOPE_DAILY))

    def test_stretch_only_monday_is_gap(self):
        from datetime import date
        mon = date(2026, 2, 23)
        self.assertTrue(_is_gap_day(mon, GAP_SCOPE_STRETCH_ONLY))

    def test_stretch_only_tuesday_is_not_gap(self):
        from datetime import date
        tue = date(2026, 2, 24)
        self.assertFalse(_is_gap_day(tue, GAP_SCOPE_STRETCH_ONLY))

    def test_stretch_only_after_holiday(self):
        from datetime import date
        # Presidents Day 2026 = Mon Feb 16; Tuesday Feb 17 is first session after stretch
        tue_after_holiday = date(2026, 2, 17)
        self.assertTrue(_is_gap_day(tue_after_holiday, GAP_SCOPE_STRETCH_ONLY))


class TestDailyGapOnTuesday(unittest.TestCase):
    """With GAP_SCOPE_DAILY, Tuesday should produce real gap values."""

    def test_tuesday_daily_scope_produces_gap(self):
        quotes = [{
            "symbol": "NVDA",
            "preMarketPrice": 105.0,
            "previousClose": 100.0,
            "timestamp": int(datetime(2026, 2, 24, 10, 0, tzinfo=UTC).timestamp()),
        }]
        run_dt = datetime(2026, 2, 24, 10, 0, tzinfo=UTC)  # Tuesday
        enriched = apply_gap_mode_to_quotes(
            quotes, run_dt_utc=run_dt,
            gap_mode=GAP_MODE_PREMARKET_INDICATIVE,
            gap_scope=GAP_SCOPE_DAILY,
        )
        row = enriched[0]
        self.assertTrue(row["gap_available"])
        self.assertAlmostEqual(row["gap_pct"], 5.0, places=4)
        self.assertEqual(row["gap_reason"], "ok")
        self.assertEqual(row["gap_scope"], GAP_SCOPE_DAILY)
        self.assertFalse(row["is_stretch_session"])

    def test_tuesday_stretch_only_no_gap(self):
        quotes = [{
            "symbol": "NVDA",
            "preMarketPrice": 105.0,
            "previousClose": 100.0,
            "timestamp": int(datetime(2026, 2, 24, 10, 0, tzinfo=UTC).timestamp()),
        }]
        run_dt = datetime(2026, 2, 24, 10, 0, tzinfo=UTC)
        enriched = apply_gap_mode_to_quotes(
            quotes, run_dt_utc=run_dt,
            gap_mode=GAP_MODE_PREMARKET_INDICATIVE,
            gap_scope=GAP_SCOPE_STRETCH_ONLY,
        )
        row = enriched[0]
        self.assertFalse(row["gap_available"])
        self.assertEqual(row["gap_pct"], 0.0)
        self.assertEqual(row["gap_reason"], "scope_stretch_only")
        # overnight_gap_pct is still computed for reference
        self.assertAlmostEqual(row["overnight_gap_pct"], 5.0, places=4)


class TestBuildGapScanner(unittest.TestCase):
    """Tests for the build_gap_scanner function."""

    def _make_quote(self, symbol: str, gap_pct: float, **kw) -> dict:
        base = {
            "symbol": symbol,
            "gap_pct": gap_pct,
            "gap_available": True,
            "gap_type": GAP_MODE_PREMARKET_INDICATIVE,
            "gap_scope": GAP_SCOPE_DAILY,
            "is_stretch_session": False,
            "ext_hours_score": 1.0,
            "ext_volume_ratio": 0.15,
            "premarket_spread_bps": 10.0,
            "premarket_stale": False,
            "price": 100.0,
            "atr": 3.0,
        }
        base.update(kw)
        return base

    def test_filters_below_threshold(self):
        quotes = [self._make_quote("NVDA", 0.5)]
        result = build_gap_scanner(quotes, min_gap_pct=1.5)
        self.assertEqual(len(result), 0)

    def test_passes_above_threshold(self):
        quotes = [self._make_quote("NVDA", 3.0)]
        result = build_gap_scanner(quotes, min_gap_pct=1.5)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["symbol"], "NVDA")
        self.assertIn("gap>=1.5%", result[0]["reason_tags"])

    def test_filters_stale_when_required(self):
        quotes = [self._make_quote("NVDA", 3.0, premarket_stale=True)]
        result = build_gap_scanner(quotes, min_gap_pct=1.5, require_fresh=True)
        self.assertEqual(len(result), 0)

    def test_sorted_by_abs_gap_desc(self):
        quotes = [
            self._make_quote("A", 2.0),
            self._make_quote("B", -4.0),
            self._make_quote("C", 3.0),
        ]
        result = build_gap_scanner(quotes, min_gap_pct=1.5)
        symbols = [r["symbol"] for r in result]
        self.assertEqual(symbols, ["B", "C", "A"])

    def test_earnings_risk_tag(self):
        quotes = [self._make_quote("NVDA", 3.0, earnings_today=True)]
        result = build_gap_scanner(quotes, min_gap_pct=1.5)
        self.assertIn("earnings_risk", result[0]["reason_tags"])

    def test_uses_overnight_gap_when_gap_unavailable(self):
        quotes = [self._make_quote("NVDA", 0.0, gap_available=False, overnight_gap_pct=3.5)]
        result = build_gap_scanner(quotes, min_gap_pct=1.5)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["gap_pct"], 3.5, places=4)


class TestClassifyLongGap(unittest.TestCase):
    """Test classify_long_gap bucket/reason/warn_flags/grade logic."""

    def _make_row(self, **overrides: object) -> dict:
        base: dict = {
            "symbol": "NVDA",
            "gap_available": True,
            "gap_pct": 2.5,
            "gap_reason": "ok",
            "ext_hours_score": 1.5,
            "ext_volume_ratio": 0.10,
            "premarket_stale": False,
            "premarket_spread_bps": 15.0,
            "earnings_risk_window": False,
            "corporate_action_penalty": 0.0,
        }
        base.update(overrides)
        return base

    # --- GO bucket ---

    def test_go_with_strong_metrics(self):
        result = classify_long_gap(self._make_row(), bias=0.2)
        self.assertEqual(result["bucket"], "GO")
        self.assertEqual(result["no_trade_reason"], "")
        self.assertEqual(result["warn_flags"], "")
        self.assertGreater(result["gap_grade"], 0.0)

    def test_go_even_with_earnings_warning(self):
        result = classify_long_gap(
            self._make_row(earnings_risk_window=True), bias=0.2
        )
        self.assertEqual(result["bucket"], "GO")
        self.assertEqual(result["no_trade_reason"], "")
        self.assertIn("earnings_risk_window", result["warn_flags"])

    def test_go_even_with_corporate_action_warning(self):
        result = classify_long_gap(
            self._make_row(corporate_action_penalty=1.5), bias=0.2
        )
        self.assertEqual(result["bucket"], "GO")
        self.assertIn("corporate_action_risk", result["warn_flags"])

    def test_go_even_with_macro_short_bias_warning(self):
        result = classify_long_gap(self._make_row(), bias=-0.5)
        self.assertEqual(result["bucket"], "GO")
        self.assertIn("macro_short_bias", result["warn_flags"])
        self.assertEqual(result["no_trade_reason"], "")

    # --- WATCH bucket ---

    def test_watch_gap_too_small_for_go(self):
        result = classify_long_gap(self._make_row(gap_pct=0.7), bias=0.2)
        self.assertEqual(result["bucket"], "WATCH")
        self.assertIn("gap_too_small", result["no_trade_reason"])

    def test_watch_ext_score_too_low(self):
        result = classify_long_gap(
            self._make_row(ext_hours_score=0.3), bias=0.2
        )
        self.assertEqual(result["bucket"], "WATCH")
        self.assertIn("ext_score_too_low", result["no_trade_reason"])

    def test_watch_ext_vol_too_low(self):
        result = classify_long_gap(
            self._make_row(ext_volume_ratio=0.02), bias=0.2
        )
        self.assertEqual(result["bucket"], "WATCH")
        self.assertIn("ext_vol_too_low", result["no_trade_reason"])

    # --- SKIP bucket ---

    def test_skip_gap_not_available(self):
        result = classify_long_gap(
            self._make_row(gap_available=False, gap_pct=0.0), bias=0.2
        )
        self.assertEqual(result["bucket"], "SKIP")
        self.assertIn("gap_not_available", result["warn_flags"])

    def test_skip_premarket_stale(self):
        result = classify_long_gap(
            self._make_row(premarket_stale=True), bias=0.2
        )
        self.assertEqual(result["bucket"], "GO")
        self.assertIn("premarket_stale", result["warn_flags"])

    def test_skip_spread_too_wide(self):
        result = classify_long_gap(
            self._make_row(premarket_spread_bps=120.0), bias=0.2
        )
        self.assertEqual(result["bucket"], "GO")
        self.assertIn("spread_too_wide", result["warn_flags"])

    def test_skip_premarket_unavailable_gap_reason(self):
        result = classify_long_gap(
            self._make_row(gap_reason="premarket_unavailable", gap_available=False),
            bias=0.2,
        )
        self.assertEqual(result["bucket"], "GO")
        self.assertIn("premarket_unavailable", result["warn_flags"])

    def test_skip_missing_previous_close(self):
        result = classify_long_gap(
            self._make_row(gap_reason="missing_previous_close", gap_available=False),
            bias=0.2,
        )
        self.assertEqual(result["bucket"], "GO")
        self.assertIn("data_missing_prev_close", result["warn_flags"])

    def test_skip_tiny_gap_below_watch_threshold(self):
        result = classify_long_gap(
            self._make_row(gap_pct=0.2), bias=0.2
        )
        self.assertEqual(result["bucket"], "SKIP")

    # --- gap_grade ---

    def test_gap_grade_range(self):
        result = classify_long_gap(self._make_row(), bias=0.2)
        self.assertGreaterEqual(result["gap_grade"], 0.0)
        self.assertLessEqual(result["gap_grade"], 5.0)

    def test_gap_grade_zero_for_no_gap(self):
        result = classify_long_gap(
            self._make_row(gap_pct=0.0, ext_hours_score=0.0, ext_volume_ratio=0.0),
            bias=0.0,
        )
        self.assertEqual(result["gap_grade"], 0.0)

    # --- spread_bps None is not a block ---

    def test_spread_bps_none_does_not_block(self):
        result = classify_long_gap(
            self._make_row(premarket_spread_bps=None), bias=0.2
        )
        self.assertEqual(result["bucket"], "GO")


class TestGapBucketLists(unittest.TestCase):
    """Integration: classify quotes → build GO/WATCH/SKIP universes."""

    def test_three_bucket_split(self):
        from open_prep.screen import classify_long_gap

        go_row = {
            "symbol": "NVDA", "gap_available": True, "gap_pct": 3.0,
            "gap_reason": "ok", "ext_hours_score": 1.5, "ext_volume_ratio": 0.12,
            "premarket_stale": False, "premarket_spread_bps": 10.0,
            "earnings_risk_window": False, "corporate_action_penalty": 0.0,
        }
        watch_row = {
            "symbol": "AAPL", "gap_available": True, "gap_pct": 0.6,
            "gap_reason": "ok", "ext_hours_score": 0.5, "ext_volume_ratio": 0.03,
            "premarket_stale": False, "premarket_spread_bps": 15.0,
            "earnings_risk_window": False, "corporate_action_penalty": 0.0,
        }
        skip_row = {
            "symbol": "BAD", "gap_available": False, "gap_pct": 0.0,
            "gap_reason": "premarket_unavailable", "ext_hours_score": 0.0,
            "ext_volume_ratio": 0.0, "premarket_stale": True,
            "premarket_spread_bps": 200.0, "earnings_risk_window": False,
            "corporate_action_penalty": 0.0,
        }
        quotes = [go_row, watch_row, skip_row]
        for q in quotes:
            meta = classify_long_gap(q, bias=0.1)
            q["gap_bucket"] = meta["bucket"]
            q["no_trade_reason"] = meta["no_trade_reason"]
            q["warn_flags"] = meta["warn_flags"]
            q["gap_grade"] = meta["gap_grade"]

        go_list = [q for q in quotes if q["gap_bucket"] == "GO"]
        watch_list = [q for q in quotes if q["gap_bucket"] == "WATCH"]
        skip_list = [q for q in quotes if q["gap_bucket"] == "SKIP"]

        self.assertEqual(len(go_list), 1)
        self.assertEqual(go_list[0]["symbol"], "NVDA")
        self.assertEqual(len(watch_list), 1)
        self.assertEqual(watch_list[0]["symbol"], "AAPL")
        self.assertEqual(len(skip_list), 1)
        self.assertEqual(skip_list[0]["symbol"], "BAD")

    def test_go_earnings_subset(self):
        from open_prep.screen import classify_long_gap

        go_clean = {
            "symbol": "NVDA", "gap_available": True, "gap_pct": 2.0,
            "gap_reason": "ok", "ext_hours_score": 1.2, "ext_volume_ratio": 0.08,
            "premarket_stale": False, "premarket_spread_bps": 10.0,
            "earnings_risk_window": False, "corporate_action_penalty": 0.0,
        }
        go_earn = {
            "symbol": "TSLA", "gap_available": True, "gap_pct": 4.0,
            "gap_reason": "ok", "ext_hours_score": 2.0, "ext_volume_ratio": 0.15,
            "premarket_stale": False, "premarket_spread_bps": 8.0,
            "earnings_risk_window": True, "corporate_action_penalty": 0.0,
        }
        for q in [go_clean, go_earn]:
            meta = classify_long_gap(q, bias=0.1)
            q["gap_bucket"] = meta["bucket"]
            q["warn_flags"] = meta["warn_flags"]

        self.assertEqual(go_clean["gap_bucket"], "GO")
        self.assertEqual(go_earn["gap_bucket"], "GO")

        go_list = [go_clean, go_earn]
        go_earnings = [
            r for r in go_list
            if "earnings_risk_window" in str(r.get("warn_flags", ""))
        ]
        self.assertEqual(len(go_earnings), 1)
        self.assertEqual(go_earnings[0]["symbol"], "TSLA")


class TestComputeGapWarnFlags(unittest.TestCase):
    """Test compute_gap_warn_flags informational flag logic."""

    def _make_row(self, **overrides: object) -> dict:
        base: dict = {
            "symbol": "NVDA",
            "gap_pct": 2.5,
            "price": 150.0,
            "previousClose": 140.0,
            "atr": 5.0,
            "vwap": 142.0,
            "pdl": 135.0,
            "pdh": 148.0,
            "premarket_high": 152.0,
            "premarket_low": 146.0,
            "momentum_z_score": 0.5,
            "ext_hours_score": 1.0,
            "premarket_spread_bps": 10.0,
            "premarket_stale": False,
        }
        base.update(overrides)
        return base

    # --- gap_up_hold_ok ---

    def test_gap_up_hold_ok_above_vwap_and_pmh(self):
        flags = compute_gap_warn_flags(self._make_row(price=155.0, vwap=142.0, premarket_high=152.0))
        self.assertIn("gap_up_hold_ok", flags)
        self.assertNotIn("gap_up_fade_risk", flags)

    def test_gap_up_hold_ok_above_vwap_no_pmh_uses_pdh(self):
        flags = compute_gap_warn_flags(self._make_row(price=155.0, vwap=142.0, premarket_high=None, pdh=148.0))
        self.assertIn("gap_up_hold_ok", flags)
        self.assertIn("warn_no_pmh", flags)

    def test_gap_up_hold_ok_above_vwap_no_pmh_no_pdh(self):
        flags = compute_gap_warn_flags(self._make_row(price=155.0, vwap=142.0, premarket_high=None, pdh=None))
        self.assertIn("gap_up_hold_ok", flags)

    # --- gap_up_fade_risk ---

    def test_gap_up_fade_risk_below_vwap(self):
        flags = compute_gap_warn_flags(self._make_row(price=140.0, vwap=142.0))
        self.assertIn("gap_up_fade_risk", flags)
        self.assertNotIn("gap_up_hold_ok", flags)

    def test_gap_up_fade_risk_below_pmh(self):
        flags = compute_gap_warn_flags(self._make_row(price=145.0, vwap=142.0, premarket_high=152.0))
        self.assertIn("gap_up_fade_risk", flags)

    # --- gap_down_reversal_ok ---

    def test_gap_down_reversal_ok_reclaim_vwap(self):
        flags = compute_gap_warn_flags(self._make_row(
            gap_pct=-1.5, price=143.0, vwap=142.0, pdl=135.0, ext_hours_score=0.5,
        ))
        self.assertIn("gap_down_reversal_ok", flags)
        self.assertNotIn("gap_down_falling_knife", flags)

    def test_gap_down_reversal_ok_reclaim_pdl(self):
        flags = compute_gap_warn_flags(self._make_row(
            gap_pct=-1.5, price=136.0, vwap=145.0, pdl=135.0, ext_hours_score=0.5,
        ))
        self.assertIn("gap_down_reversal_ok", flags)

    def test_gap_down_no_reversal_extreme_ext_score(self):
        flags = compute_gap_warn_flags(self._make_row(
            gap_pct=-1.5, price=143.0, vwap=142.0, ext_hours_score=-1.0,
        ))
        self.assertNotIn("gap_down_reversal_ok", flags)

    # --- gap_down_falling_knife ---

    def test_gap_down_falling_knife(self):
        flags = compute_gap_warn_flags(self._make_row(
            gap_pct=-3.0, price=130.0, pdl=135.0,
            momentum_z_score=-0.5, ext_hours_score=-0.5,
        ))
        self.assertIn("gap_down_falling_knife", flags)

    def test_gap_down_falling_knife_needs_negative_momentum(self):
        flags = compute_gap_warn_flags(self._make_row(
            gap_pct=-3.0, price=130.0, pdl=135.0,
            momentum_z_score=0.5, ext_hours_score=-0.5,
        ))
        self.assertNotIn("gap_down_falling_knife", flags)

    # --- gap_large_atr ---

    def test_gap_large_atr(self):
        # atr_pct = (5/140)*100 = 3.57%, 0.80*3.57 = 2.86%, gap_pct 3.5 > 2.86
        flags = compute_gap_warn_flags(self._make_row(gap_pct=3.5, atr=5.0, previousClose=140.0))
        self.assertIn("gap_large_atr", flags)

    def test_gap_not_large_atr(self):
        # atr_pct = (5/140)*100 = 3.57%, 0.80*3.57 = 2.86%, gap_pct 1.0 < 2.86
        flags = compute_gap_warn_flags(self._make_row(gap_pct=1.0, atr=5.0, previousClose=140.0))
        self.assertNotIn("gap_large_atr", flags)

    def test_gap_large_atr_no_prev_close(self):
        flags = compute_gap_warn_flags(self._make_row(gap_pct=3.5, atr=5.0, previousClose=None))
        self.assertNotIn("gap_large_atr", flags)

    # --- warn_spread_wide ---

    def test_warn_spread_wide(self):
        flags = compute_gap_warn_flags(self._make_row(premarket_spread_bps=55.0))
        self.assertIn("warn_spread_wide", flags)

    def test_spread_ok(self):
        flags = compute_gap_warn_flags(self._make_row(premarket_spread_bps=20.0))
        self.assertNotIn("warn_spread_wide", flags)

    def test_spread_none_no_flag(self):
        flags = compute_gap_warn_flags(self._make_row(premarket_spread_bps=None))
        self.assertNotIn("warn_spread_wide", flags)

    # --- warn_premarket_stale ---

    def test_warn_premarket_stale(self):
        flags = compute_gap_warn_flags(self._make_row(premarket_stale=True))
        self.assertIn("warn_premarket_stale", flags)

    def test_premarket_not_stale(self):
        flags = compute_gap_warn_flags(self._make_row(premarket_stale=False))
        self.assertNotIn("warn_premarket_stale", flags)

    # --- warn_no_pmh ---

    def test_warn_no_pmh_gap_up(self):
        flags = compute_gap_warn_flags(self._make_row(gap_pct=2.0, premarket_high=None))
        self.assertIn("warn_no_pmh", flags)

    def test_no_warn_no_pmh_gap_down(self):
        flags = compute_gap_warn_flags(self._make_row(gap_pct=-2.0, premarket_high=None))
        self.assertNotIn("warn_no_pmh", flags)

    # --- no flags for micro gap ---

    def test_micro_gap_no_directional_flags(self):
        flags = compute_gap_warn_flags(self._make_row(gap_pct=0.10))
        self.assertNotIn("gap_up_hold_ok", flags)
        self.assertNotIn("gap_up_fade_risk", flags)
        self.assertNotIn("gap_down_reversal_ok", flags)
        self.assertNotIn("gap_down_falling_knife", flags)


class TestPremarketHighLow(unittest.TestCase):
    """Test compute_premarket_high_low aggregation."""

    def test_premarket_window_aggregation(self):
        from open_prep.run_open_prep import compute_premarket_high_low

        bars = [
            {"date": "2026-02-23 06:00:00", "high": 155.0, "low": 150.0},
            {"date": "2026-02-23 07:30:00", "high": 158.0, "low": 151.0},
            {"date": "2026-02-23 09:00:00", "high": 156.0, "low": 149.0},
            # After RTH open — should be excluded
            {"date": "2026-02-23 09:35:00", "high": 160.0, "low": 148.0},
        ]
        pm_high, pm_low = compute_premarket_high_low(bars, session_day_ny=date(2026, 2, 23))
        self.assertEqual(pm_high, 158.0)
        self.assertEqual(pm_low, 149.0)

    def test_premarket_before_window_excluded(self):
        from open_prep.run_open_prep import compute_premarket_high_low

        bars = [
            # 03:00 NY — before premarket window
            {"date": "2026-02-23 03:00:00", "high": 200.0, "low": 100.0},
            {"date": "2026-02-23 05:00:00", "high": 155.0, "low": 150.0},
        ]
        pm_high, pm_low = compute_premarket_high_low(bars, session_day_ny=date(2026, 2, 23))
        self.assertEqual(pm_high, 155.0)
        self.assertEqual(pm_low, 150.0)

    def test_empty_bars_returns_none(self):
        from open_prep.run_open_prep import compute_premarket_high_low

        pm_high, pm_low = compute_premarket_high_low([], session_day_ny=date(2026, 2, 23))
        self.assertIsNone(pm_high)
        self.assertIsNone(pm_low)

    def test_no_premarket_bars_returns_none(self):
        from open_prep.run_open_prep import compute_premarket_high_low

        bars = [
            {"date": "2026-02-23 10:00:00", "high": 160.0, "low": 155.0},
        ]
        pm_high, pm_low = compute_premarket_high_low(bars, session_day_ny=date(2026, 2, 23))
        self.assertIsNone(pm_high)
        self.assertIsNone(pm_low)


class TestPickSymbolsForPMH(unittest.TestCase):
    """Test _pick_symbols_for_pmh attention list selection."""

    def test_movers_plus_top_ext(self):
        from open_prep.run_open_prep import _pick_symbols_for_pmh

        symbols = ["A", "B", "C", "D"]
        pm_ctx = {
            "A": {"is_premarket_mover": True, "ext_hours_score": 0.5},
            "B": {"is_premarket_mover": False, "ext_hours_score": 2.0},
            "C": {"is_premarket_mover": False, "ext_hours_score": 1.0},
            "D": {"is_premarket_mover": False, "ext_hours_score": -0.5},
        }
        result = _pick_symbols_for_pmh(symbols, pm_ctx, top_n_ext=2)
        # A is mover, B and C top-2 by ext_hours_score; D excluded
        self.assertIn("A", result)
        self.assertIn("B", result)
        self.assertIn("C", result)
        self.assertNotIn("D", result)

    def test_dedup_mover_and_top(self):
        from open_prep.run_open_prep import _pick_symbols_for_pmh

        symbols = ["X"]
        pm_ctx = {"X": {"is_premarket_mover": True, "ext_hours_score": 5.0}}
        result = _pick_symbols_for_pmh(symbols, pm_ctx, top_n_ext=10)
        self.assertEqual(result.count("X"), 1)


class TestAtrRobustness(unittest.TestCase):
    def test_calculate_atr_accepts_exact_period_bars(self):
        period = 14
        candles = [
            {"date": f"2026-02-{i:02d}", "high": 10.0 + i * 0.1, "low": 9.0 + i * 0.1, "close": 9.5 + i * 0.1}
            for i in range(1, period + 1)
        ]
        atr = _calculate_atr14_from_eod(candles, period=period)
        self.assertGreater(atr, 0.0)

    def test_fetch_symbol_atr_unwraps_historical_payload(self):
        client = MagicMock()
        client.get_historical_price_eod_full.return_value = {
            "historical": [
                {"date": f"2026-02-{i:02d}", "high": 10.0 + i * 0.1, "low": 9.0 + i * 0.1, "close": 9.5 + i * 0.1}
                for i in range(1, 20)
            ]
        }
        symbol, atr, _mom, _vwap, err = _fetch_symbol_atr(
            client,
            "NVDA",
            date(2026, 1, 1),
            date(2026, 2, 20),
            14,
        )
        self.assertEqual(symbol, "NVDA")
        self.assertGreater(atr, 0.0)
        self.assertIsNone(err)

    def test_fetch_symbol_atr_reports_zero_as_error(self):
        client = MagicMock()
        client.get_historical_price_eod_full.return_value = {"historical": []}
        symbol, atr, _mom, _vwap, err = _fetch_symbol_atr(
            client,
            "NVDA",
            date(2026, 1, 1),
            date(2026, 2, 20),
            14,
        )
        self.assertEqual(symbol, "NVDA")
        self.assertEqual(atr, 0.0)
        self.assertEqual(err, "atr_zero_or_insufficient_bars")

    def test_atr_cache_filters_non_positive_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            as_of = date(2026, 2, 23)
            with patch("open_prep.run_open_prep.ATR_CACHE_DIR", cache_dir):
                _save_atr_cache(
                    as_of=as_of,
                    period=14,
                    atr_map={"A": 0.0, "B": -1.0, "C": 2.5},
                    momentum_map={"A": 1.0, "B": 1.0, "C": 1.5},
                    prev_close_map={"A": 100.0, "B": 101.0, "C": 102.0},
                )
                atr_map, momentum_map, prev_close_map = _load_atr_cache(as_of, 14)
                self.assertEqual(atr_map, {"C": 2.5})
                self.assertEqual(momentum_map, {"C": 1.5})
                self.assertEqual(prev_close_map, {"C": 102.0})


class TestOpenPrepRegressions(unittest.TestCase):
    def test_generate_result_mirrors_pmh_into_premarket_context(self):
        with (
            patch("open_prep.run_open_prep._fetch_todays_events", return_value=[]),
            patch(
                "open_prep.run_open_prep._build_macro_context",
                return_value={
                    "macro_analysis": {"macro_bias": 0.1, "raw_score": 0.0, "score_components": []},
                    "macro_bias": 0.1,
                    "macro_event_count_today": 0,
                    "macro_us_event_count_today": 0,
                    "macro_us_high_impact_event_count_today": 0,
                    "macro_us_mid_impact_event_count_today": 0,
                    "macro_events_for_bias": [],
                    "macro_us_high_impact_events_today": [],
                    "macro_us_mid_impact_events_today": [],
                    "bea_audit": {},
                },
            ),
            patch("open_prep.run_open_prep._fetch_news_context", return_value=({}, {}, None)),
            patch(
                "open_prep.run_open_prep._fetch_quotes_with_atr",
                return_value=(
                    [{"symbol": "NVDA", "previousClose": 100.0, "price": 101.0, "atr": 2.0}],
                    {},
                    {},
                    {},
                    {},
                ),
            ),
            patch(
                "open_prep.run_open_prep._fetch_premarket_context",
                return_value=({"NVDA": {"is_premarket_mover": True}}, None),
            ),
            patch("open_prep.run_open_prep._pick_symbols_for_pmh", return_value=["NVDA"]),
            patch(
                "open_prep.run_open_prep._fetch_premarket_high_low_bulk",
                return_value=({"NVDA": {"premarket_high": 150.0, "premarket_low": 145.0}}, None),
            ),
            patch(
                "open_prep.run_open_prep.rank_candidates",
                return_value=[{"symbol": "NVDA", "warn_flags": "", "gap_bucket": "GO", "gap_grade": 1.0}],
            ),
            patch("open_prep.run_open_prep.build_trade_cards", return_value=[]),
        ):
            result = run_open_prep.generate_open_prep_result(
                symbols=["NVDA"],
                client=MagicMock(),
                top=1,
                trade_cards=1,
                now_utc=datetime(2026, 2, 23, 12, 0, tzinfo=UTC),
            )

        self.assertIn("NVDA", result["premarket_context"])
        self.assertEqual(result["premarket_context"]["NVDA"]["premarket_high"], 150.0)
        self.assertEqual(result["premarket_context"]["NVDA"]["premarket_low"], 145.0)

    def test_generate_result_forwards_pmh_timeout_env(self):
        with (
            patch("open_prep.run_open_prep._fetch_todays_events", return_value=[]),
            patch(
                "open_prep.run_open_prep._build_macro_context",
                return_value={
                    "macro_analysis": {"macro_bias": 0.1, "raw_score": 0.0, "score_components": []},
                    "macro_bias": 0.1,
                    "macro_event_count_today": 0,
                    "macro_us_event_count_today": 0,
                    "macro_us_high_impact_event_count_today": 0,
                    "macro_us_mid_impact_event_count_today": 0,
                    "macro_events_for_bias": [],
                    "macro_us_high_impact_events_today": [],
                    "macro_us_mid_impact_events_today": [],
                    "bea_audit": {},
                },
            ),
            patch("open_prep.run_open_prep._fetch_news_context", return_value=({}, {}, None)),
            patch(
                "open_prep.run_open_prep._fetch_quotes_with_atr",
                return_value=(
                    [{"symbol": "NVDA", "previousClose": 100.0, "price": 101.0, "atr": 2.0}],
                    {},
                    {},
                    {},
                    {},
                ),
            ),
            patch(
                "open_prep.run_open_prep._fetch_premarket_context",
                return_value=({"NVDA": {"is_premarket_mover": True}}, None),
            ),
            patch("open_prep.run_open_prep._pick_symbols_for_pmh", return_value=["NVDA"]),
            patch(
                "open_prep.run_open_prep._fetch_premarket_high_low_bulk",
                return_value=({"NVDA": {"premarket_high": None, "premarket_low": None}}, "pmh_pml_fetch_timeout_3.5s"),
            ) as pm_fetch_mock,
            patch(
                "open_prep.run_open_prep.rank_candidates",
                return_value=[{"symbol": "NVDA", "warn_flags": "", "gap_bucket": "GO", "gap_grade": 1.0}],
            ),
            patch("open_prep.run_open_prep.build_trade_cards", return_value=[]),
            patch.dict("os.environ", {"OPEN_PREP_PMH_FETCH_TIMEOUT_SECONDS": "3.5"}, clear=False),
        ):
            result = run_open_prep.generate_open_prep_result(
                symbols=["NVDA"],
                client=MagicMock(),
                top=1,
                trade_cards=1,
                now_utc=datetime(2026, 2, 23, 12, 0, tzinfo=UTC),
            )

        self.assertEqual(pm_fetch_mock.call_args.kwargs["fetch_timeout_seconds"], 3.5)
        self.assertIn("pmh_pml", str(result.get("premarket_fetch_error") or ""))

    def test_main_writes_latest_open_prep_artifact(self):
        fake_args = argparse.Namespace(
            symbols="NVDA",
            universe_source="fmp_us_mid_large",
            fmp_min_market_cap=2_000_000_000,
            fmp_max_symbols=10,
            mover_seed_max_symbols=10,
            days_ahead=1,
            top=1,
            trade_cards=1,
            max_macro_events=5,
            pre_open_only=False,
            pre_open_cutoff_utc="16:00:00",
            gap_mode="premarket_indicative",
            gap_scope="daily",
            atr_lookback_days=30,
            atr_period=14,
            atr_parallel_workers=2,
            analyst_catalyst_limit=5,
        )
        payload = {"schema_version": "open_prep_v1", "ranked_candidates": [], "trade_cards": []}

        with tempfile.TemporaryDirectory() as tmp_dir:
            with (
                patch("open_prep.run_open_prep._parse_args", return_value=fake_args),
                patch("open_prep.run_open_prep.generate_open_prep_result", return_value=payload),
                patch("sys.stdout", new_callable=io.StringIO),
            ):
                cwd = Path.cwd()
                try:
                    os.chdir(tmp_dir)
                    run_open_prep.main()
                    latest = Path("open_prep/latest_open_prep_run.json")
                    self.assertTrue(latest.exists())
                    self.assertEqual(json.loads(latest.read_text(encoding="utf-8")), payload)
                finally:
                    os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
