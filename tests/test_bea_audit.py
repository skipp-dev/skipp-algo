import unittest
from unittest.mock import patch

from open_prep.bea import (
    build_bea_audit_payload,
    extract_current_release_url,
    should_audit_pce_release,
)


class TestBeaAudit(unittest.TestCase):
    def test_extract_current_release_url_prefers_current_release_anchor(self):
        html = '''
        <html><body>
            <a href="/news/2026/personal-income-and-outlays-december-2025">Current Release</a>
            <a href="/news/2026/personal-income-and-outlays-november-2025">Older</a>
        </body></html>
        '''
        url = extract_current_release_url(html)
        self.assertEqual(
            url,
            "https://www.bea.gov/news/2026/personal-income-and-outlays-december-2025",
        )

    def test_should_audit_for_pce_canonical_event(self):
        should, trigger = should_audit_pce_release(
            [
                {
                    "canonical_event": "core_pce_mom",
                    "data_quality_flags": [],
                }
            ]
        )
        self.assertTrue(should)
        self.assertEqual(trigger["canonical_events"], ["core_pce_mom"])

    def test_should_audit_for_data_quality_flags(self):
        should, trigger = should_audit_pce_release(
            [
                {
                    "canonical_event": "gdp_qoq",
                    "data_quality_flags": ["missing_consensus"],
                }
            ]
        )
        self.assertTrue(should)
        self.assertEqual(trigger["data_quality_flags"], ["missing_consensus"])

    def test_should_audit_for_dedup_signal(self):
        should, trigger = should_audit_pce_release(
            [
                {
                    "canonical_event": "gdp_qoq",
                    "data_quality_flags": [],
                    "dedup": {"was_deduped": True},
                }
            ]
        )
        self.assertTrue(should)
        self.assertEqual(trigger["data_quality_flags"], ["duplicate_event"])

    def test_build_bea_audit_payload_is_fail_open(self):
        events = [{"canonical_event": "pce_mom", "data_quality_flags": []}]
        with patch("open_prep.bea.resolve_current_pio_release_url", return_value=(None, "bea_network_error:timeout")):
            payload = build_bea_audit_payload(events, enabled=True)

        self.assertEqual(payload["status"], "fail_open")
        self.assertIsNone(payload["release_url"])
        self.assertEqual(payload["error"], "bea_network_error:timeout")

    def test_pce_yoy_canonical_event_triggers_audit(self):
        """Regression: pce_yoy / core_pce_yoy must now be real canonical keys
        so the BEA audit fires when PCE YoY appears in events_for_bias."""
        for key in ("pce_yoy", "core_pce_yoy"):
            with self.subTest(canonical=key):
                should, trigger = should_audit_pce_release(
                    [{"canonical_event": key, "data_quality_flags": []}]
                )
                self.assertTrue(should, f"{key} should trigger the BEA audit")
                self.assertIn(key, trigger["canonical_events"])

    def test_missing_consensus_flag_on_events_for_bias_triggers_audit(self):
        """Regression (Fix #4 side-effect): after macro_bias_with_components stopped
        mutating events, data_quality_flags were lost from events_for_bias, breaking
        the missing_consensus and missing_unit audit triggers.  Now that
        macro_bias_with_components annotates copies, the flags must be present."""
        from open_prep.macro import macro_bias_with_components

        events = [
            {
                "country": "US",
                "date": "2026-02-20",
                "event": "Core PCE MoM",
                "actual": 0.3,
                "consensus": None,  # missing → should set missing_consensus flag
                "impact": "High",
                "unit": "percent",
            }
        ]
        analysis = macro_bias_with_components(events)
        bias_events = analysis["events_for_bias"]
        self.assertTrue(
            len(bias_events) > 0, "events_for_bias should not be empty"
        )
        pce_event = next(
            (e for e in bias_events if e.get("canonical_event") == "core_pce_mom"), None
        )
        self.assertIsNotNone(pce_event, "core_pce_mom should appear in events_for_bias")
        self.assertIn(
            "missing_consensus",
            pce_event.get("data_quality_flags", []),
            "missing_consensus flag must be set on events_for_bias copy",
        )

        # The BEA audit pipeline must pick this up.
        should, trigger = should_audit_pce_release(bias_events)
        self.assertTrue(should)
        self.assertIn("missing_consensus", trigger["data_quality_flags"])


if __name__ == "__main__":
    unittest.main()
