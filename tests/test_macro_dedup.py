import unittest
from open_prep.macro import (
    canonicalize_event_name,
    dedupe_events,
    macro_bias_score,
    macro_bias_with_components,
    filter_us_mid_impact_events,
)

class TestMacroDedup(unittest.TestCase):
    def test_canonicalization(self):
        self.assertEqual(canonicalize_event_name("Gross Domestic Product QoQ (Q4)"), "gdp_qoq")
        self.assertEqual(canonicalize_event_name("GDP Growth Rate QoQ (Q4)"), "gdp_qoq")
        self.assertEqual(canonicalize_event_name("S&P Global Manufacturing PMI (Feb)"), "pmi_sp_global")

    def test_dedupe(self):
        events = [
            {"country": "US", "date": "2026-02-20", "event": "Gross Domestic Product QoQ (Q4)", "actual": 1.4, "consensus": 2.8, "impact": "High"},
            {"country": "US", "date": "2026-02-20", "event": "GDP Growth Rate QoQ (Q4)", "actual": 1.4, "consensus": 3.5, "impact": "High"}
        ]
        deduped = dedupe_events(events)
        self.assertEqual(len(deduped), 1)
        self.assertTrue(deduped[0].get("dedup", {}).get("was_deduped"))
        self.assertEqual(deduped[0]["dedup"]["duplicates_count"], 2)
        self.assertEqual(
            deduped[0]["dedup"].get("chosen_event"),
            "Gross Domestic Product QoQ (Q4)",
        )

    def test_score_components_include_dedup_metadata(self):
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
        ]
        analysis = macro_bias_with_components(events)
        gdp_component = next(c for c in analysis["score_components"] if c.get("canonical_event") == "gdp_qoq")
        self.assertTrue(gdp_component.get("dedup", {}).get("was_deduped"))
        self.assertEqual(gdp_component["dedup"].get("chosen_event"), "Gross Domestic Product QoQ (Q4)")

    def test_bias_stability(self):
        events = [
            {"country": "US", "date": "2026-02-20", "event": "Core PCE Price Index MoM (Dec)", "actual": 0.4, "consensus": 0.2, "impact": "High"},
            {"country": "US", "date": "2026-02-20", "event": "Gross Domestic Product QoQ (Q4)", "actual": 1.4, "consensus": 2.8, "impact": "High"},
            {"country": "US", "date": "2026-02-20", "event": "GDP Growth Rate QoQ (Q4)", "actual": 1.4, "consensus": 3.5, "impact": "High"},
            {"country": "US", "date": "2026-02-20", "event": "S&P Global Manufacturing PMI (Feb)", "actual": 51.2, "consensus": 52.4, "impact": "High"}
        ]
        score = macro_bias_score(events)
        # PCE: -1.0
        # GDP (deduped, 1.4 vs 2.8 or 3.5): -0.5
        # PMI (51.2 vs 52.4): -0.25
        # Total: -1.75 -> Normalized: -0.875
        self.assertEqual(score, -0.875)

    def test_estimate_field_is_used_as_consensus_with_audit(self):
        events = [
            {"country": "US", "date": "2026-02-20", "event": "Core PCE Price Index MoM (Dec)", "actual": 0.4, "estimate": 0.2, "impact": "High"}
        ]
        analysis = macro_bias_with_components(events)
        self.assertEqual(analysis["macro_bias"], -0.5)
        # Verify consensus_field is surfaced in score_components (not mutated onto input)
        pce_comp = next(c for c in analysis["score_components"] if c.get("canonical_event") == "core_pce_mom")
        self.assertEqual(pce_comp["consensus_field"], "estimate")
        # Input event must NOT be mutated
        self.assertNotIn("consensus_field", events[0])

    def test_core_and_headline_pce_have_different_weights(self):
        events = [
            {"country": "US", "date": "2026-02-20", "event": "Core PCE Price Index MoM (Dec)", "actual": 0.4, "estimate": 0.2, "impact": "High"},
            {"country": "US", "date": "2026-02-20", "event": "PCE Price Index MoM (Dec)", "actual": 0.4, "estimate": 0.3, "impact": "Medium"},
        ]
        score = macro_bias_score(events)
        # Core PCE: -1.0
        # Headline PCE: -0.25
        # Total: -1.25 -> Normalized: -0.625
        self.assertEqual(score, -0.625)

    def test_headline_pce_confirm_can_be_disabled_explicitly(self):
        events = [
            {
                "country": "US",
                "date": "2026-02-20",
                "event": "Core PCE Price Index MoM (Dec)",
                "actual": 0.4,
                "estimate": 0.2,
                "impact": "High",
            },
            {
                "country": "US",
                "date": "2026-02-20",
                "event": "PCE Price Index MoM (Dec)",
                "actual": 0.4,
                "estimate": 0.3,
                "impact": "Medium",
            },
        ]

        with_confirm = macro_bias_score(
            events,
            include_mid_if_no_high=True,
            include_headline_pce_confirm=True,
        )
        without_confirm = macro_bias_score(
            events,
            include_mid_if_no_high=True,
            include_headline_pce_confirm=False,
        )

        self.assertEqual(with_confirm, -0.625)
        self.assertEqual(without_confirm, -0.5)

    def test_dedupe_preserves_non_canonical_events(self):
        """Non-canonical events (e.g. Consumer Sentiment) must survive dedupe
        so mid-impact fallback and display lists see them."""
        events = [
            {"country": "US", "date": "2026-02-20", "event": "Michigan Consumer Sentiment", "impact": "Medium", "actual": 70.0, "consensus": 68.0},
            {"country": "US", "date": "2026-02-20", "event": "New Home Sales", "impact": "Medium", "actual": 650, "consensus": 640},
            {"country": "US", "date": "2026-02-20", "event": "Core CPI MoM", "impact": "High", "actual": 0.3, "consensus": 0.2},
        ]
        deduped = dedupe_events(events)
        names = [e.get("event") for e in deduped]
        self.assertIn("Michigan Consumer Sentiment", names)
        self.assertIn("New Home Sales", names)
        self.assertIn("Core CPI MoM", names)

    def test_mid_impact_events_reachable_after_dedupe(self):
        """After dedupe, non-canonical mid-impact events must still pass
        through filter_us_mid_impact_events."""
        events = [
            {"country": "US", "date": "2026-02-20", "event": "Michigan Consumer Sentiment", "impact": "Medium"},
            {"country": "US", "date": "2026-02-20", "event": "Existing Home Sales", "impact": "Medium"},
        ]
        from open_prep.macro import filter_us_events
        deduped = dedupe_events(filter_us_events(events))
        mid = filter_us_mid_impact_events(deduped)
        mid_names = [e.get("event") for e in mid]
        self.assertIn("Michigan Consumer Sentiment", mid_names)
        self.assertIn("Existing Home Sales", mid_names)

    def test_dedupe_keeps_usd_events_when_country_missing(self):
        """Regression: provider may omit `country` while still setting USD.
        These events must not be silently dropped during dedupe."""
        events = [
            {
                "country": None,
                "currency": "USD",
                "date": "2026-02-20",
                "event": "Core CPI MoM",
                "actual": 0.3,
                "consensus": 0.2,
                "impact": "High",
            },
            {
                "country": "",
                "currency": "USD",
                "date": "2026-02-20",
                "event": "Core CPI MoM",
                "actual": 0.3,
                "consensus": 0.2,
                "impact": "High",
            },
        ]
        deduped = dedupe_events(events)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0].get("country"), "US")
        self.assertEqual(deduped[0].get("canonical_event"), "core_cpi_mom")

    def test_mid_impact_fallback_scores_non_canonical_events(self):
        """On a day with ZERO high-impact events, non-canonical mid-impact
        events (e.g. Consumer Sentiment) must contribute to macro bias."""
        events = [
            {
                "country": "US",
                "date": "2026-02-20",
                "event": "Michigan Consumer Sentiment",
                "impact": "Medium",
                "actual": 75.0,
                "consensus": 70.0,
            }
        ]
        analysis = macro_bias_with_components(events, include_mid_if_no_high=True)
        self.assertNotEqual(analysis["macro_bias"], 0.0, "Non-canonical mid-impact should move bias")
        components = analysis["score_components"]
        self.assertTrue(
            any(c["weight"] > 0 for c in components),
            "At least one component should have non-zero weight",
        )

    def test_non_canonical_inflation_yoy_gets_reduced_weight(self):
        """Inflation YoY prints should get weight 0.25, not 1.0."""
        events = [
            {
                "country": "US",
                "date": "2026-02-20",
                "event": "PCE Price Index YoY",
                "actual": 2.8,
                "consensus": 2.5,
                "impact": "High",
            }
        ]
        analysis = macro_bias_with_components(events)
        comps = [c for c in analysis["score_components"] if c["weight"] > 0]
        self.assertEqual(len(comps), 1)
        self.assertEqual(comps[0]["canonical_event"], "pce_yoy")
        self.assertEqual(comps[0]["weight"], 0.25, "Inflation YoY should use reduced weight")

    def test_annotate_does_not_mutate_input_events(self):
        """macro_bias_with_components must not mutate the caller's event dicts."""
        events = [
            {
                "country": "US",
                "date": "2026-02-20",
                "event": "Core CPI MoM",
                "actual": 0.3,
                "consensus": 0.2,
                "impact": "High",
            }
        ]
        original_keys = set(events[0].keys())
        macro_bias_with_components(events)
        self.assertEqual(set(events[0].keys()), original_keys, "Input event should not gain new keys")

    def test_pce_yoy_and_core_pce_yoy_canonicalize_and_score(self):
        """Regression: pce_yoy / core_pce_yoy must be recognized canonical keys.
        Before the fix they were dead code in PCE_AUDIT_CANONICAL_EVENTS because
        CANONICAL_EVENT_PATTERNS had no YoY PCE patterns."""
        from open_prep.macro import canonicalize_event_name
        self.assertEqual(canonicalize_event_name("PCE Price Index YoY"), "pce_yoy")
        self.assertEqual(canonicalize_event_name("Core PCE Price Index YoY"), "core_pce_yoy")
        self.assertEqual(canonicalize_event_name("PCE YoY"), "pce_yoy")
        self.assertEqual(canonicalize_event_name("Core PCE YoY"), "core_pce_yoy")

        # Scoring: both should use weight 0.25 (same as pce_mom)
        for event_name, expected_canonical in (
            ("PCE Price Index YoY", "pce_yoy"),
            ("Core PCE Price Index YoY", "core_pce_yoy"),
        ):
            with self.subTest(event=event_name):
                analysis = macro_bias_with_components([
                    {
                        "country": "US",
                        "date": "2026-02-20",
                        "event": event_name,
                        "actual": 3.0,
                        "consensus": 2.5,
                        "impact": "High",
                    }
                ])
                comp = next(
                    (c for c in analysis["score_components"] if c.get("canonical_event") == expected_canonical),
                    None,
                )
                self.assertIsNotNone(comp, f"{expected_canonical} should appear in score_components")
                self.assertEqual(comp["weight"], 0.25, "YoY PCE variants must use reduced weight 0.25")

    def test_events_for_bias_carry_data_quality_flags(self):
        """Regression: after Fix #4 removed event mutation in _annotate_event_quality,
        events_for_bias had empty data_quality_flags, silently breaking the BEA audit's
        missing_consensus and missing_unit triggers.  Verify flags are now set."""
        events = [
            {
                "country": "US",
                "date": "2026-02-20",
                "event": "Core PCE MoM",
                "actual": 0.3,
                # No consensus field at all → should produce missing_consensus flag
                "impact": "High",
                "unit": None,  # also missing → should produce missing_unit flag
            }
        ]
        analysis = macro_bias_with_components(events)
        bias_events = analysis["events_for_bias"]
        pce = next((e for e in bias_events if e.get("canonical_event") == "core_pce_mom"), None)
        self.assertIsNotNone(pce)
        flags = pce.get("data_quality_flags", [])
        self.assertIn("missing_consensus", flags)
        self.assertIn("missing_unit", flags)
        # Sanity: input was not mutated
        self.assertNotIn("data_quality_flags", events[0])

    def test_cpi_ppi_yoy_canonicalize_and_score_at_reduced_weight(self):
        """Regression: CPI YoY / Core CPI YoY / PPI YoY / Core PPI YoY must
        canonicalize to their own keys and score at weight 0.25, not fall through
        to the bare cpi/ppi patterns at weight 1.0 (which causes double-counting
        with the MoM prints from the same release)."""
        from open_prep.macro import canonicalize_event_name

        yoy_cases = [
            ("CPI YoY", "cpi_yoy"),
            ("CPI Price Index YoY", "cpi_yoy"),
            ("Core CPI YoY", "core_cpi_yoy"),
            ("Core CPI Price Index YoY", "core_cpi_yoy"),
            ("PPI YoY", "ppi_yoy"),
            ("PPI Price Index YoY", "ppi_yoy"),
            ("Core PPI YoY", "core_ppi_yoy"),
            ("Core PPI Price Index YoY", "core_ppi_yoy"),
        ]
        for raw_name, expected_key in yoy_cases:
            with self.subTest(raw_name=raw_name):
                self.assertEqual(
                    canonicalize_event_name(raw_name), expected_key,
                    f"{raw_name!r} should canonicalize to {expected_key!r}",
                )

        # Verify scoring weight is 0.25 for all YoY variants
        for event_name, expected_canonical in yoy_cases[:4]:
            with self.subTest(scoring=event_name):
                analysis = macro_bias_with_components([
                    {
                        "country": "US",
                        "date": "2026-02-20",
                        "event": event_name,
                        "actual": 3.0,
                        "consensus": 2.5,
                        "impact": "High",
                    }
                ])
                comp = next(
                    (c for c in analysis["score_components"] if c.get("canonical_event") == expected_canonical),
                    None,
                )
                self.assertIsNotNone(comp)
                self.assertEqual(comp["weight"], 0.25, f"{expected_canonical} YoY must use 0.25")

    def test_cpi_mom_and_cpi_yoy_same_day_no_double_counting(self):
        """On a real CPI day, MoM and YoY arrive together. MoM should get 1.0
        and YoY only 0.25 — they must NOT both get 1.0."""
        events = [
            {
                "country": "US",
                "date": "2026-02-20",
                "event": "CPI MoM",
                "actual": 0.4,
                "consensus": 0.2,
                "impact": "High",
            },
            {
                "country": "US",
                "date": "2026-02-20",
                "event": "CPI YoY",
                "actual": 3.0,
                "consensus": 2.8,
                "impact": "High",
            },
        ]
        analysis = macro_bias_with_components(events)
        mom_comp = next(c for c in analysis["score_components"] if c.get("canonical_event") == "cpi_mom")
        yoy_comp = next(c for c in analysis["score_components"] if c.get("canonical_event") == "cpi_yoy")
        self.assertEqual(mom_comp["weight"], 1.0)
        self.assertEqual(yoy_comp["weight"], 0.25)
        # Total: -(1.0 + 0.25) = -1.25 raw / 2.0 = -0.625
        self.assertEqual(analysis["macro_bias"], -0.625)

    def test_dedupe_events_handles_mixed_date_formats(self):
        """Deduplication key must use only the date portion so that events
        with the same canonical key are merged even when one provider returns
        a date-only string ('2026-02-20') and another returns a full datetime
        ('2026-02-20 08:30:00') for the same release."""
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
                "date": "2026-02-20 08:30:00",
                "event": "GDP Growth Rate QoQ (Q4)",
                "actual": 1.4,
                "consensus": 3.5,
                "impact": "High",
            },
        ]
        deduped = dedupe_events(events)
        self.assertEqual(len(deduped), 1, "Mixed date formats must still deduplicate to one event")
        self.assertTrue(deduped[0].get("dedup", {}).get("was_deduped"))
        self.assertEqual(deduped[0]["dedup"]["duplicates_count"], 2)

if __name__ == "__main__":
    unittest.main()
