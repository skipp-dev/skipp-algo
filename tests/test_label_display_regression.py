"""
Label and display regression tests (quasi-visual contract).

Goal:
- Guard label payload/schema (text blocks, style, color contracts) against silent drift.
- Validate event→label-type mapping via simulator outcomes (without TradingView UI).
"""

from __future__ import annotations

import pathlib
import unittest

from tests.pine_sim import Bar, BarSignals, SimConfig, SkippAlgoSim


ROOT = pathlib.Path(__file__).resolve().parents[1]
INDICATOR_PATH = ROOT / "SkippALGO.pine"
STRATEGY_PATH = ROOT / "SkippALGO_Strategy.pine"


def derive_virtual_labels(res) -> list[str]:
    """Small quasi-visual mapper from bar result to expected label family."""
    labels: list[str] = []

    if res.did_buy:
        labels.append("REV-BUY" if res.rev_buy_global else "BUY")
    if res.did_short:
        labels.append("REV-SHORT" if res.rev_short_global else "SHORT")
    if res.did_exit:
        labels.append("EXIT")
    if res.did_cover:
        labels.append("COVER")

    return labels


class TestLabelDisplayContractSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ind = INDICATOR_PATH.read_text(encoding="utf-8")
        cls.strat = STRATEGY_PATH.read_text(encoding="utf-8")

    def _assert_contract(self, text: str, name: str):
        # Safety guard for label text truncation
        has_safe_helper = "f_safe_label_text(txt)" in text
        has_direct_label_helpers = (
            "f_pre_label(x, y, txt, sty, txtCol, bgCol) =>" in text and
            "f_entry_label(x, y, txt, sty, txtCol, bgCol) =>" in text and
            "f_exit_label(x, y, txt, sty, txtCol, bgCol) =>" in text
        )
        self.assertTrue(
            has_safe_helper or has_direct_label_helpers,
            f"{name}: safe label text guard/helper contract missing"
        )
        if has_safe_helper:
            self.assertIn("_max = 120", text, f"{name}: label max length guard missing")

        # PRE labels payload contract
        self.assertIn('"PRE-BUY\\nGap: " + _gapTxt + "\\npU: " + _pTxt + "\\nConf: " + _cTxt', text,
                      f"{name}: PRE-BUY payload contract missing")
        self.assertIn('"PRE-SHORT\\nGap: " + _gapTxt + "\\npD: " + _pTxt + "\\nConf: " + _cTxt', text,
                      f"{name}: PRE-SHORT payload contract missing")
        self.assertIn("label.style_label_up", text, f"{name}: missing label up style")
        self.assertIn("label.style_label_down", text, f"{name}: missing label down style")

        # Entry label color/style contract
        self.assertIn("color.new(color.aqua, 0)", text, f"{name}: REV-BUY color contract missing")
        self.assertIn("color.new(color.fuchsia, 0)", text, f"{name}: REV-SHORT color contract missing")
        self.assertIn("color.new(color.green, 0)", text, f"{name}: BUY color contract missing")
        self.assertIn("color.new(color.red, 0)", text, f"{name}: SHORT color contract missing")

        # Exit/Cover payload contract
        self.assertIn('"EXIT" + entryTag + "\\n" + buyAgoTxt + exitSuffix + "\\n" + lastExitReason + "\\nHeld " + str.tostring(barsSinceEntry) + " bars"',
                      text, f"{name}: EXIT payload contract missing")
        self.assertIn('"COVER" + entryTag + "\\n" + shortAgoTxt + coverSuffix + "\\n" + lastExitReason + "\\nHeld " + str.tostring(barsSinceEntry) + " bars"',
                      text, f"{name}: COVER payload contract missing")

        # Strict display markers may be either enabled (legacy) or removed (newer token-budget variants).
        has_strict_markers = (
            'title="STRICT-CONF BUY"' in text or
            'title="STRICT-CONF SHORT"' in text or
            "STRICT-CONFIRMED BUY" in text or
            "STRICT-CONFIRMED SHORT" in text
        )
        has_strict_controls = (
            ("showStrictIcon" in text and "showStrictLabel" in text) or
            ("strictMarkerStyle" in text)
        )
        self.assertTrue(has_strict_markers or has_strict_controls,
                        f"{name}: strict marker/control contract missing")

    def test_indicator_label_display_contract(self):
        self._assert_contract(self.ind, "Indicator")

    def test_strategy_label_display_contract(self):
        self._assert_contract(self.strat, "Strategy")


class TestLabelDisplayContractBehavior(unittest.TestCase):
    def test_virtual_label_buy_family(self):
        sim = SkippAlgoSim(SimConfig(engine="Hybrid", hybrid_long_trigger=True))
        r = sim.process_bar(Bar(), BarSignals())
        self.assertEqual(derive_virtual_labels(r), ["BUY"])

    def test_virtual_label_rev_buy_family(self):
        sim = SkippAlgoSim(SimConfig(
            reliability_ok=False,
            allow_neural_reversals=True,
            p_u=0.60,
            in_rev_open_window_long=False,
        ))
        r = sim.process_bar(Bar(), BarSignals(is_choch_long=True))
        self.assertEqual(derive_virtual_labels(r), ["REV-BUY"])

    def test_virtual_label_short_family(self):
        sim = SkippAlgoSim(SimConfig(engine="Hybrid", hybrid_short_trigger=True, enable_shorts=True))
        r = sim.process_bar(Bar(), BarSignals())
        self.assertEqual(derive_virtual_labels(r), ["SHORT"])

    def test_virtual_label_rev_short_family(self):
        sim = SkippAlgoSim(SimConfig(
            reliability_ok=False,
            allow_neural_reversals=True,
            enable_shorts=True,
            p_d=0.60,
            in_rev_open_window_short=False,
        ))
        r = sim.process_bar(Bar(), BarSignals(is_choch_short=True))
        self.assertEqual(derive_virtual_labels(r), ["REV-SHORT"])

    def test_virtual_label_exit_and_cover_family(self):
        # EXIT path
        sim_long = SkippAlgoSim(SimConfig(allow_neural_reversals=True, exit_grace_bars=0))
        sim_long.process_bar(Bar(), BarSignals(is_choch_long=True))
        r_exit = sim_long.process_bar(Bar(), BarSignals(risk_hit=True, risk_msg="SL"))
        self.assertEqual(derive_virtual_labels(r_exit), ["EXIT"])

        # COVER path
        sim_short = SkippAlgoSim(SimConfig(
            reliability_ok=False,
            allow_neural_reversals=True,
            enable_shorts=True,
            p_d=0.60,
            exit_grace_bars=0,
        ))
        sim_short.process_bar(Bar(), BarSignals(is_choch_short=True))
        r_cover = sim_short.process_bar(Bar(), BarSignals(risk_hit=True, risk_msg="SL"))
        self.assertEqual(derive_virtual_labels(r_cover), ["COVER"])


if __name__ == "__main__":
    unittest.main()
