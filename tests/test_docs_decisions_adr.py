"""Structural pin-test for docs/DECISIONS.md ADR scaffolding.

Guards the canonical ADR log so future entries follow the same shape
and the Plan 2.8 3-layer-HTF decision stays pinned (the addendum §7
risk mitigation asks for an explicit reject-reason entry in this file).
"""

from __future__ import annotations

import re
from pathlib import Path

DECISIONS = Path(__file__).resolve().parents[1] / "docs" / "DECISIONS.md"


def _text() -> str:
    return DECISIONS.read_text(encoding="utf-8")


def test_decisions_file_exists_with_title() -> None:
    assert DECISIONS.exists()
    assert _text().startswith("# Architectural Decisions")


def test_format_spec_enumerates_required_subsections() -> None:
    text = _text()
    for label in (
        "**Context**", "**Decision**", "**Alternatives considered**",
        "**Consequences**", "**Evidence**", "**Status**",
    ):
        assert label in text, f"format spec missing {label}"


def test_plan_2_8_3_layer_htf_adr_present() -> None:
    text = _text()
    # H3 header with date prefix.
    m = re.search(r"^### \d{4}-\d{2}-\d{2} - 3-layer HTF trend stack",
                  text, re.MULTILINE)
    assert m is not None, "Plan 2.8 3-layer HTF ADR not found"


def test_plan_2_8_adr_cross_references_addendum_and_pin_tests() -> None:
    text = _text()
    assert "smc_improvement_plan_addendum_2_8_mtf_scope_2026-04-21.md" in text
    assert "test_plan_2_8_s0_pine_trend_tf_tooltips.py" in text
    assert "test_plan_2_8_s3_1_chart_tf_expansion.py" in text
    assert "test_plan_2_8_s3_1_per_tf_partitioning.py" in text
    assert "plan_2_8_q4_gate_evaluator.py" in text


def test_plan_2_8_adr_lists_rejected_alternatives() -> None:
    text = _text()
    # All three rejection paths the addendum enumerates must appear.
    assert "Flux-style 7-TF user-configurable bias stack" in text
    assert "4th intraday trend layer" in text
    assert "Sub-minute LTF" in text


def test_plan_2_8_adr_is_accepted_status() -> None:
    text = _text()
    # The final status line of the Plan 2.8 ADR.
    assert "**Status.** accepted." in text
