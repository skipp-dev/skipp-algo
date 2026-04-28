"""Sprint C7.1 — Decision-first panel snapshot tests.

The panel is asserted against the four standard postures
(green/yellow/orange/red). Decision dicts are hand-crafted to match
the X2 ``governance.types.Decision`` shape so this test is independent
of X2's merge order.
"""
from __future__ import annotations

import textwrap

from dashboard.decision_first_panel import (
    POSTURE_GLYPH,
    build_card,
    render_card,
    render_panel,
    sparkline,
)

# ---------------------------------------------------------------------------
# Decision fixtures matching governance.types.Decision shape.
# ---------------------------------------------------------------------------


def _green() -> dict:
    return {
        "schema_version": 1,
        "family": "BOS",
        "promoted": True,
        "posture": "green",
        "blockers": [],
        "metrics": {"brier": 0.18, "psr": 0.97, "psi": 0.05},
    }


def _yellow() -> dict:
    return {
        "schema_version": 1,
        "family": "OB",
        "promoted": False,
        "posture": "yellow",
        "blockers": [
            {
                "check": "psi_drift",
                "severity": "warning",
                "observed": 0.20,
                "threshold": 0.25,
                "message": "psi=0.2000 nearing 0.2500 cap",
            },
        ],
        "metrics": {"brier": 0.21, "psr": 0.96, "psi": 0.20},
    }


def _orange() -> dict:
    return {
        "schema_version": 1,
        "family": "FVG",
        "promoted": False,
        "posture": "orange",
        "blockers": [
            {
                "check": "fdr_significance",
                "severity": "blocker",
                "observed": 0.08,
                "threshold": 0.05,
                "message": "fdr_pvalue=0.0800 fails <= 0.0500",
            },
        ],
        "metrics": {"brier": 0.22, "fdr_pvalue": 0.08},
    }


def _red() -> dict:
    return {
        "schema_version": 1,
        "family": "SWEEP",
        "promoted": False,
        "posture": "red",
        "blockers": [
            {
                "check": "psr_minimum",
                "severity": "blocker",
                "observed": 0.80,
                "threshold": 0.95,
                "message": "psr=0.8000 fails >= 0.9500",
            },
            {
                "check": "live_vs_wf_ratio",
                "severity": "blocker",
                "observed": 1.80,
                "threshold": 1.50,
                "message": "live/wf brier ratio=1.80 exceeds 1.50",
            },
        ],
        "metrics": {"brier": 0.30, "psr": 0.80, "live_vs_wf_ratio": 1.80},
    }


# ---------------------------------------------------------------------------
# Sparkline.
# ---------------------------------------------------------------------------


def test_sparkline_empty_returns_empty() -> None:
    assert sparkline([]) == ""


def test_sparkline_constant_input_no_div_by_zero() -> None:
    out = sparkline([0.5, 0.5, 0.5, 0.5])
    assert len(out) == 4
    assert len(set(out)) == 1


def test_sparkline_monotone_increasing_uses_full_range() -> None:
    out = sparkline([0.0, 0.25, 0.5, 0.75, 1.0])
    assert out[0] == "▁"
    assert out[-1] == "█"
    assert len(out) == 5


# ---------------------------------------------------------------------------
# Card renderer — per-posture snapshots.
# ---------------------------------------------------------------------------


def test_render_card_green_snapshot() -> None:
    card = build_card(_green(), walkforward_history=[0.20, 0.19, 0.18])
    out = render_card(card)
    expected = textwrap.dedent(
        """\
        [GREEN]  BOS                    PROMOTED
            top: (no blockers)
            sparkline: █▅▁
            metrics: brier=0.1800, psi=0.0500, psr=0.9700"""
    )
    assert out == expected


def test_render_card_yellow_snapshot() -> None:
    card = build_card(_yellow(), walkforward_history=[0.18, 0.19, 0.21])
    out = render_card(card)
    expected = textwrap.dedent(
        """\
        [YELLOW]  OB                     BLOCKED
            top: warning/psi_drift: psi=0.2000 nearing 0.2500 cap
            sparkline: ▁▃█
            metrics: brier=0.2100, psi=0.2000, psr=0.9600"""
    )
    assert out == expected


def test_render_card_orange_snapshot() -> None:
    card = build_card(_orange())
    out = render_card(card)
    expected = textwrap.dedent(
        """\
        [ORANGE]  FVG                    BLOCKED
            top: blocker/fdr_significance: fdr_pvalue=0.0800 fails <= 0.0500
            sparkline: (no history)
            metrics: brier=0.2200, fdr_pvalue=0.0800"""
    )
    assert out == expected


def test_render_card_red_snapshot_picks_highest_severity_blocker_first() -> None:
    card = build_card(_red())
    out = render_card(card)
    # Highest-severity blocker (psr_minimum is first in input + tied severity)
    # appears in the 'top:' line; the renderer is stable on input order.
    assert "[RED]" in out
    assert "blocker/psr_minimum" in out
    assert "BLOCKED" in out


# ---------------------------------------------------------------------------
# Panel — multi-card rendering.
# ---------------------------------------------------------------------------


def test_render_panel_emits_one_block_per_decision() -> None:
    out = render_panel([_green(), _yellow(), _orange(), _red()])
    blocks = out.split("\n\n")
    assert len(blocks) == 4
    assert blocks[0].startswith("[GREEN]")
    assert blocks[1].startswith("[YELLOW]")
    assert blocks[2].startswith("[ORANGE]")
    assert blocks[3].startswith("[RED]")


def test_render_panel_uses_provided_histories() -> None:
    out = render_panel(
        [_green()],
        walkforward_histories={"BOS": [0.10, 0.20, 0.30]},
    )
    assert "sparkline: ▁▅█" in out


def test_render_panel_no_history_marks_no_history_label() -> None:
    out = render_panel([_orange()])
    assert "(no history)" in out


# ---------------------------------------------------------------------------
# Build-card — defensive defaults on incomplete dicts.
# ---------------------------------------------------------------------------


def test_build_card_handles_missing_metrics_and_blockers() -> None:
    minimal = {"family": "BOS", "promoted": True, "posture": "green"}
    card = build_card(minimal)
    assert card.metrics_summary == "(no metrics)"
    assert card.top_blocker == ""


def test_posture_glyph_covers_all_four_postures() -> None:
    assert set(POSTURE_GLYPH) == {"green", "yellow", "orange", "red"}
