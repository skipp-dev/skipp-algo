"""Tests for the Default-Surface visual budget (ENG-WS3-02)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.smc_default_surface_budget import (
    DEFAULT_VIEW_MODE,
    VISUAL_BUDGET,
    default_facing_views,
    forbidden_tokens_in,
    validate_default_visible_rows,
    visual_budget_for,
)


class TestDefaults:
    def test_default_view_mode_is_decision_brief(self) -> None:
        assert DEFAULT_VIEW_MODE == "Decision Brief"

    def test_default_facing_views_exclude_audit_and_explain(self) -> None:
        facing = default_facing_views()
        assert "Audit View" not in facing
        assert "Explain" not in facing
        assert facing == frozenset({"Focus", "Hero", "Decision Brief", "Mobile"})


class TestVisualBudget:
    @pytest.mark.parametrize(
        "view_mode,expected",
        [
            ("Focus", 3),
            ("Hero", 7),
            ("Decision Brief", 7),
            ("Explain", 8),
            ("Mobile", 5),
        ],
    )
    def test_default_facing_budgets_are_bounded(
        self, view_mode: str, expected: int
    ) -> None:
        assert visual_budget_for(view_mode) == expected

    def test_audit_view_has_largest_budget(self) -> None:
        audit = visual_budget_for("Audit View")
        for mode in default_facing_views():
            assert audit > visual_budget_for(mode)

    def test_unknown_view_mode_raises(self) -> None:
        with pytest.raises(KeyError):
            visual_budget_for("Diagnostics")


class TestForbiddenVocabulary:
    @pytest.mark.parametrize(
        "label,expected",
        [
            ("Action", ()),
            ("Trust", ()),
            ("BUS_v2 PACK_state", ("BUS_", "PACK_")),
            ("Operator_only", ("OPERATOR_",)),
            ("ENSEMBLE_TIER", ("ENSEMBLE_",)),
            ("Diag_label", ("DIAG_",)),
        ],
    )
    def test_forbidden_token_detection(
        self, label: str, expected: tuple[str, ...]
    ) -> None:
        assert forbidden_tokens_in(label) == expected

    def test_validate_passes_for_clean_default_view(self) -> None:
        validate_default_visible_rows(
            "Decision Brief",
            ["Trust", "Market", "Quality", "Action", "Why now", "Risk", "Plan"],
        )

    def test_validate_rejects_forbidden_token_in_default_view(self) -> None:
        with pytest.raises(ValueError, match="forbidden"):
            validate_default_visible_rows(
                "Decision Brief", ["Trust", "BUS_state", "Action"]
            )

    def test_validate_allows_forbidden_token_in_audit_view(self) -> None:
        # Pro diagnostics may legitimately surface BUS / ensemble vocabulary.
        validate_default_visible_rows(
            "Audit View", ["BUS_state", "ENSEMBLE_TIER", "PACKED_BUS_v2"]
        )

    def test_validate_rejects_overflow(self) -> None:
        with pytest.raises(ValueError, match="exceeds visual budget"):
            validate_default_visible_rows(
                "Focus", ["a", "b", "c", "d"]
            )

    def test_validate_rejects_unknown_view(self) -> None:
        with pytest.raises(ValueError, match="Unknown view"):
            validate_default_visible_rows("Diagnostics", [])


# ── Pine surface contract ─────────────────────────────────────────────


class TestPineSurfaceDefault:
    """The Pine surface_mode default must match DEFAULT_VIEW_MODE."""

    def test_pine_surface_mode_default_is_decision_brief(self) -> None:
        text = Path("SMC_Dashboard.pine").read_text(encoding="utf-8")
        # Match: surface_mode = input.string("<default>", "View", ...)
        match = re.search(
            r'surface_mode\s*=\s*input\.string\(\s*"([^"]+)"', text
        )
        assert match is not None, "surface_mode input not found in SMC_Dashboard.pine"
        assert match.group(1) == DEFAULT_VIEW_MODE

    def test_pine_surface_mode_options_match_visual_budget(self) -> None:
        text = Path("SMC_Dashboard.pine").read_text(encoding="utf-8")
        match = re.search(
            r'surface_mode\s*=\s*input\.string\([^)]*options\s*=\s*\[([^\]]+)\]',
            text,
        )
        assert match is not None, "surface_mode options not found"
        options = re.findall(r'"([^"]+)"', match.group(1))
        # All Pine view modes must be priced in the visual budget.
        for mode in options:
            assert mode in VISUAL_BUDGET, f"Pine view mode {mode!r} missing budget"
