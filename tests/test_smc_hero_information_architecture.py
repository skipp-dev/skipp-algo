"""Tests for the Hero Information Architecture (ENG-WS3-01)."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from scripts.smc_hero_information_architecture import (
    HERO_PRIMARY_LINES,
    HERO_ROW_CATALOG,
    VIEW_MODE_LEVELS,
    HeroReadingLevel,
    HeroRow,
    all_reading_levels,
    hero_primary_lines,
    level_of,
    rows_for_level,
    view_mode_levels,
)


class TestReadingLevels:
    def test_three_canonical_levels(self) -> None:
        assert {lvl.value for lvl in HeroReadingLevel} == {"hero", "compact", "pro"}

    def test_iteration_order_is_hero_first(self) -> None:
        assert all_reading_levels() == (
            HeroReadingLevel.HERO,
            HeroReadingLevel.COMPACT,
            HeroReadingLevel.PRO,
        )


class TestHeroPrimaryLines:
    def test_hero_has_exactly_three_primary_lines(self) -> None:
        assert HERO_PRIMARY_LINES == (
            "HERO_MARKET_MODE",
            "HERO_SETUP_QUALITY",
            "HERO_ACTION",
        )

    def test_helper_returns_same_tuple(self) -> None:
        assert hero_primary_lines() == HERO_PRIMARY_LINES

    def test_each_primary_line_is_a_hero_row(self) -> None:
        hero_rows = {row.row_id for row in rows_for_level(HeroReadingLevel.HERO)}
        assert set(HERO_PRIMARY_LINES) == hero_rows


class TestRowCatalog:
    def test_every_row_has_unique_id(self) -> None:
        ids = [row.row_id for row in HERO_ROW_CATALOG]
        dupes = [rid for rid, count in Counter(ids).items() if count > 1]
        assert dupes == []

    def test_every_row_assigned_to_exactly_one_level(self) -> None:
        for row in HERO_ROW_CATALOG:
            assert isinstance(row, HeroRow)
            assert isinstance(row.level, HeroReadingLevel)

    def test_every_level_has_at_least_one_row(self) -> None:
        for level in HeroReadingLevel:
            assert rows_for_level(level), f"empty level: {level!r}"

    def test_level_of_resolves_known_row(self) -> None:
        assert level_of("HERO_ACTION") is HeroReadingLevel.HERO
        assert level_of("COMPACT_TRUST_DATA") is HeroReadingLevel.COMPACT
        assert level_of("PRO_AUDIT_TABLE") is HeroReadingLevel.PRO

    def test_level_of_raises_for_unknown_row(self) -> None:
        with pytest.raises(KeyError):
            level_of("DOES_NOT_EXIST")


class TestViewModes:
    def test_all_pine_view_modes_are_mapped(self) -> None:
        # The Pine surface_mode input declares these five options.
        pine_modes = {"Focus", "Hero", "Explain", "Decision Brief", "Audit View"}
        # Plus the synthetic Mobile mode that mirrors the compact-dashboard toggle.
        expected = pine_modes | {"Mobile"}
        assert set(VIEW_MODE_LEVELS) == expected

    @pytest.mark.parametrize(
        "view_mode,expected",
        [
            ("Focus", (HeroReadingLevel.HERO,)),
            ("Hero", (HeroReadingLevel.HERO,)),
            ("Decision Brief", (HeroReadingLevel.HERO, HeroReadingLevel.COMPACT)),
            ("Explain", (HeroReadingLevel.COMPACT,)),
            ("Audit View", (HeroReadingLevel.HERO, HeroReadingLevel.COMPACT, HeroReadingLevel.PRO)),
            ("Mobile", (HeroReadingLevel.HERO, HeroReadingLevel.COMPACT)),
        ],
    )
    def test_view_mode_to_levels_mapping_is_stable(
        self, view_mode: str, expected: tuple[HeroReadingLevel, ...]
    ) -> None:
        assert view_mode_levels(view_mode) == expected

    def test_unknown_view_mode_raises(self) -> None:
        with pytest.raises(KeyError):
            view_mode_levels("Diagnostics")

    def test_view_modes_never_contain_duplicate_levels(self) -> None:
        for mode, levels in VIEW_MODE_LEVELS.items():
            assert len(set(levels)) == len(levels), f"duplicate levels in {mode}"

    def test_view_modes_are_hero_before_compact_before_pro(self) -> None:
        order = {lvl: i for i, lvl in enumerate(all_reading_levels())}
        for mode, levels in VIEW_MODE_LEVELS.items():
            seen = [order[lvl] for lvl in levels]
            assert seen == sorted(seen), f"{mode} levels not in canonical order"


class TestHeroFirstReadingOrder:
    """The Hero level always reads first; no view may render Pro before Hero."""

    def test_no_view_renders_pro_without_compact_or_hero(self) -> None:
        for mode, levels in VIEW_MODE_LEVELS.items():
            if HeroReadingLevel.PRO in levels:
                # Pro is only allowed in the deepest view, alongside the lighter ones.
                assert HeroReadingLevel.HERO in levels or HeroReadingLevel.COMPACT in levels, (
                    f"{mode} renders Pro without lighter context"
                )

    def test_focus_and_hero_views_carry_only_hero_lines(self) -> None:
        for mode in ("Focus", "Hero"):
            assert view_mode_levels(mode) == (HeroReadingLevel.HERO,)


class TestDocumentation:
    """ENG-WS3-01 DoD: hero-first Lesestufe ist explizit dokumentiert."""

    def test_hero_surface_plan_documents_three_levels(self) -> None:
        plan = Path("docs/smc_deep_review_2026-04-20_hero_surface_plan.md").read_text(
            encoding="utf-8"
        )
        assert "Hero-first Lesestufe (ENG-WS3-01)" in plan
        assert "scripts/smc_hero_information_architecture" in plan
        assert "HERO_PRIMARY_LINES" in plan
        assert "HERO_ROW_CATALOG" in plan
        assert "VIEW_MODE_LEVELS" in plan
