"""Hero Information Architecture (ENG-WS3-01).

Realises ticket ``ENG-WS3-01`` from
``docs/engineering-program/smc_deep_review_2026-04-20_engineering_backlog.md``
("Hero-Informationsarchitektur fixieren").

The dashboards already expose five view modes (``Focus``, ``Hero``,
``Explain``, ``Decision Brief``, ``Audit View``) plus a separate
mobile/compact toggle. This module pins the **information-architecture
contract** that every later WS3 ticket (Hero head, Setup-Quality card,
Action recommendation) must respect:

- The visible product surface is structured into exactly **three
  reading levels** — Hero, Compact, Pro.
- Each row a dashboard view can show is assigned to **exactly one**
  level. No row may double-count.
- The Hero level carries a fixed, ordered set of three primary lines:
  ``HERO_MARKET_MODE``, ``HERO_SETUP_QUALITY``, ``HERO_ACTION``. No
  other line is "primary" inside the Hero level.
- The view modes from the Pine surface are mapped to a deterministic
  set of allowed levels.

This module is read-only: it defines the contract as data and exposes
small pure helpers so downstream tests can pin the architecture
without parsing Pine.
"""
from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

# ── Reading levels ────────────────────────────────────────────────────


class HeroReadingLevel(enum.Enum):
    """Three canonical reading levels for the dashboard surface."""

    HERO = "hero"
    COMPACT = "compact"
    PRO = "pro"


# Stable ordering used by the documentation surface and by every test
# that iterates levels (Hero first, Pro last).
_LEVEL_ORDER: tuple[HeroReadingLevel, ...] = (
    HeroReadingLevel.HERO,
    HeroReadingLevel.COMPACT,
    HeroReadingLevel.PRO,
)


def all_reading_levels() -> tuple[HeroReadingLevel, ...]:
    """Return the canonical iteration order over reading levels."""
    return _LEVEL_ORDER


# ── Hero primary lines ────────────────────────────────────────────────
# The Hero level has exactly three primary lines, in this order.
HERO_PRIMARY_LINES: tuple[str, ...] = (
    "HERO_MARKET_MODE",
    "HERO_SETUP_QUALITY",
    "HERO_ACTION",
)


# ── Row catalog ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class HeroRow:
    """One named visible row + the level it belongs to."""

    row_id: str
    level: HeroReadingLevel
    description: str


# Each row is named once and assigned to exactly one level. The Pine
# dashboards must not surface the same logical row in two levels.
_HERO_ROW_CATALOG: tuple[HeroRow, ...] = (
    # ── Hero level ──────────────────────────────────────────
    HeroRow(
        row_id="HERO_MARKET_MODE",
        level=HeroReadingLevel.HERO,
        description="Market mode + bias + trust badge (ENG-WS3-03 head)",
    ),
    HeroRow(
        row_id="HERO_SETUP_QUALITY",
        level=HeroReadingLevel.HERO,
        description="Setup quality + why now + main risk (ENG-WS3-04)",
    ),
    HeroRow(
        row_id="HERO_ACTION",
        level=HeroReadingLevel.HERO,
        description="Primary action recommendation (ENG-WS3-05)",
    ),
    # ── Compact level ───────────────────────────────────────
    HeroRow(
        row_id="COMPACT_TRUST_DATA",
        level=HeroReadingLevel.COMPACT,
        description="Trust+data badge (ENG-WS2-03)",
    ),
    HeroRow(
        row_id="COMPACT_SESSION_MARKET",
        level=HeroReadingLevel.COMPACT,
        description="Session + market context",
    ),
    HeroRow(
        row_id="COMPACT_EVENT_RISK",
        level=HeroReadingLevel.COMPACT,
        description="Event risk light",
    ),
    HeroRow(
        row_id="COMPACT_PRESSURE",
        level=HeroReadingLevel.COMPACT,
        description="LTF delta + swing pressure",
    ),
    HeroRow(
        row_id="COMPACT_RISK_PLAN",
        level=HeroReadingLevel.COMPACT,
        description="Trigger / stop / targets",
    ),
    HeroRow(
        row_id="COMPACT_WHY_NOW",
        level=HeroReadingLevel.COMPACT,
        description="Compact why-now sentence",
    ),
    HeroRow(
        row_id="COMPACT_STRUCTURE",
        level=HeroReadingLevel.COMPACT,
        description="Structure + zone state",
    ),
    HeroRow(
        row_id="COMPACT_MAIN_BLOCKER",
        level=HeroReadingLevel.COMPACT,
        description="Main blocker (single line)",
    ),
    # ── Pro level ───────────────────────────────────────────
    HeroRow(
        row_id="PRO_AUDIT_TABLE",
        level=HeroReadingLevel.PRO,
        description="Full audit table (Audit View)",
    ),
    HeroRow(
        row_id="PRO_BUS_DIAGNOSTICS",
        level=HeroReadingLevel.PRO,
        description="BUS v2 / packed-bus diagnostics",
    ),
    HeroRow(
        row_id="PRO_CALIBRATION_CONFIDENCE",
        level=HeroReadingLevel.PRO,
        description="Calibration confidence section",
    ),
    HeroRow(
        row_id="PRO_FAMILY_PERFORMANCE",
        level=HeroReadingLevel.PRO,
        description="Per-family performance section",
    ),
    HeroRow(
        row_id="PRO_FVG_HEALTH",
        level=HeroReadingLevel.PRO,
        description="FVG health section",
    ),
    HeroRow(
        row_id="PRO_LIBRARY_DIAGNOSTICS",
        level=HeroReadingLevel.PRO,
        description="Library diagnostics (versions, refresh count)",
    ),
)

HERO_ROW_CATALOG: tuple[HeroRow, ...] = _HERO_ROW_CATALOG


# ── View-mode → allowed levels ────────────────────────────────────────
# The Pine ``surface_mode`` input has these five options, plus the
# separate Compact-Dashboard / Mobile toggle. Every view mode declares
# the levels it may render; each list is ordered from primary to
# supporting so a renderer can follow it top-down.

_VIEW_MODE_LEVELS: Mapping[str, tuple[HeroReadingLevel, ...]] = MappingProxyType({
    "Focus": (HeroReadingLevel.HERO,),
    "Hero": (HeroReadingLevel.HERO,),
    "Decision Brief": (HeroReadingLevel.HERO, HeroReadingLevel.COMPACT),
    "Explain": (HeroReadingLevel.COMPACT,),
    "Audit View": (HeroReadingLevel.HERO, HeroReadingLevel.COMPACT, HeroReadingLevel.PRO),
    # Mobile / Compact-Dashboard toggle is treated as a synthetic mode
    # so the same architecture applies to the mobile surface.
    "Mobile": (HeroReadingLevel.HERO, HeroReadingLevel.COMPACT),
})

VIEW_MODE_LEVELS: Mapping[str, tuple[HeroReadingLevel, ...]] = _VIEW_MODE_LEVELS


# ── Pure helpers ──────────────────────────────────────────────────────


def rows_for_level(level: HeroReadingLevel) -> tuple[HeroRow, ...]:
    """Return all catalog rows assigned to ``level`` in catalog order."""
    return tuple(row for row in HERO_ROW_CATALOG if row.level is level)


def level_of(row_id: str) -> HeroReadingLevel:
    """Return the level a row belongs to. Raises ``KeyError`` for unknown ids."""
    for row in HERO_ROW_CATALOG:
        if row.row_id == row_id:
            return row.level
    raise KeyError(f"Unknown hero row id: {row_id!r}")


def view_mode_levels(view_mode: str) -> tuple[HeroReadingLevel, ...]:
    """Return the ordered tuple of levels a view mode may render."""
    if view_mode not in VIEW_MODE_LEVELS:
        raise KeyError(f"Unknown view mode: {view_mode!r}")
    return VIEW_MODE_LEVELS[view_mode]


def hero_primary_lines() -> tuple[str, ...]:
    """Return the three Hero-level primary lines in canonical order."""
    return HERO_PRIMARY_LINES


__all__ = [
    "HERO_PRIMARY_LINES",
    "HERO_ROW_CATALOG",
    "VIEW_MODE_LEVELS",
    "HeroReadingLevel",
    "HeroRow",
    "all_reading_levels",
    "hero_primary_lines",
    "level_of",
    "rows_for_level",
    "view_mode_levels",
]
