"""Pin-test for Plan 2.8 S0 Pine-dashboard tooltip accuracy.

Guards the three `Trend TF N` input tooltips that document the
intentional 3-layer HTF stack (4H / 1D / 1W) vs. a Flux-style 7-TF
bias stack. Regressions here would silently re-open the UX ambiguity
the addendum explicitly closes.
"""

from __future__ import annotations

import re
from pathlib import Path

PINE = Path(__file__).resolve().parents[1] / "SMC_Core_Engine.pine"


def _text() -> str:
    return PINE.read_text(encoding="utf-8")


def test_trend_tf1_tooltip_mentions_three_layer_hierarchy() -> None:
    m = re.search(r"'Trend TF 1'[^\n]*tooltip\s*=\s*'([^']+)'", _text())
    assert m is not None, "Trend TF 1 tooltip missing"
    t = m.group(1)
    assert "4H" in t and "1D" in t and "1W" in t
    assert "3-layer" in t.lower()


def test_trend_tf2_tooltip_documents_calibration_caveat() -> None:
    m = re.search(r"'Trend TF 2'[^\n]*tooltip\s*=\s*'([^']+)'", _text())
    assert m is not None
    t = m.group(1).lower()
    # Must warn that non-default TFs disable calibrated contribution.
    assert "calibrat" in t


def test_trend_tf3_tooltip_references_ipda_adaptive_layer() -> None:
    m = re.search(r"'Trend TF 3'[^\n]*tooltip\s*=\s*'([^']+)'", _text())
    assert m is not None
    t = m.group(1)
    assert "IPDA" in t
    assert "select_ipda_htf" in t


def test_all_three_trend_tfs_have_tooltips() -> None:
    # Regression guard: regex below must find all three.
    names = ["'Trend TF 1'", "'Trend TF 2'", "'Trend TF 3'"]
    for name in names:
        m = re.search(
            rf"{re.escape(name)}[^\n]*tooltip\s*=\s*'[^']+'", _text()
        )
        assert m is not None, f"{name} input has no tooltip"
