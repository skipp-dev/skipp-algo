"""Compile/regression tests for SMC_Event_Overlay.pine and generated import snippet.

Tests verify:
1. Overlay file structure — version header, indicator declaration, import, BUS input
2. Overlay independence — no direct mp.FIELD writes, no strategy/entry logic
3. Overlay field coverage — reads only published event-risk fields
4. Generated library import snippet — presence and accuracy of usage comment
"""
from __future__ import annotations

import pathlib
import re

import pytest

from tests.smc_manifest_test_utils import (
    extract_group_titles,
    extract_input_bindings,
    published_micro_profiles_import_line,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
OVERLAY_PATH = ROOT / "SMC_Event_Overlay.pine"
ENGINE_PATH = ROOT / "SMC_Long_Dip_Suite.pine"

# ── Helpers ──────────────────────────────────────────────────────


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# Event-risk fields the overlay is allowed to reference
EXPECTED_OVERLAY_BINDINGS = (("BUS LeanPackA", "g_ev"),)
EXPECTED_MP_FIELDS_IN_ORDER = (
    "EVENT_WINDOW_STATE",
    "EVENT_RISK_LEVEL",
    "NEXT_EVENT_NAME",
    "NEXT_EVENT_TIME",
    "NEXT_EVENT_IMPACT",
    "EVENT_RESTRICT_BEFORE_MIN",
    "EVENT_RESTRICT_AFTER_MIN",
    "EVENT_COOLDOWN_ACTIVE",
    "MARKET_EVENT_BLOCKED",
    "SYMBOL_EVENT_BLOCKED",
    "HIGH_RISK_EVENT_TICKERS",
    "EARNINGS_SOON_TICKERS",
    "ASOF_DATE", "ASOF_DATE", "ASOF_DATE",  # staleness check: year, month, day
    "ASOF_DATE",  # exact event timestamp date anchor
)
ALLOWED_MP_FIELDS = {
    "EVENT_WINDOW_STATE", "EVENT_RISK_LEVEL",
    "NEXT_EVENT_NAME", "NEXT_EVENT_TIME", "NEXT_EVENT_IMPACT",
    "NEXT_EVENT_CLASS",
    "EVENT_RESTRICT_BEFORE_MIN", "EVENT_RESTRICT_AFTER_MIN",
    "EVENT_COOLDOWN_ACTIVE",
    "MARKET_EVENT_BLOCKED", "SYMBOL_EVENT_BLOCKED",
    "HIGH_RISK_EVENT_TICKERS", "EARNINGS_SOON_TICKERS",
    "EVENT_PROVIDER_STATUS",
    "ASOF_DATE",  # Library freshness check (companion staleness pattern)
}

_MP_FIELD_RE = re.compile(r"\bmp\.([A-Z][A-Z0-9_]+)")
_LEAN_SLOT_RE = re.compile(r"pack_slot\(src_lean_pack_a,\s*(\d+)\)")


# ═════════════════════════════════════════════════════════════════
# 1. Overlay structure
# ═════════════════════════════════════════════════════════════════


class TestOverlayStructure:
    def test_file_exists(self):
        assert OVERLAY_PATH.exists(), "SMC_Event_Overlay.pine must exist"

    def test_version_header(self):
        src = _read(OVERLAY_PATH)
        assert "//@version=6" in src

    def test_indicator_declaration(self):
        src = _read(OVERLAY_PATH)
        assert 'indicator("SMC Event Overlay"' in src

    def test_overlay_true(self):
        src = _read(OVERLAY_PATH)
        assert "overlay = true" in src

    def test_imports_library(self):
        src = _read(OVERLAY_PATH)
        assert published_micro_profiles_import_line() in src
        assert "import preuss_steffen/smc_utils/4 as u" in src

    def test_bus_lean_pack_a_input(self):
        src = _read(OVERLAY_PATH)
        assert '"BUS LeanPackA"' in src

    def test_overlay_bus_binding_order_and_group_are_exact(self):
        src = _read(OVERLAY_PATH)
        assert extract_input_bindings(src) == EXPECTED_OVERLAY_BINDINGS

    def test_overlay_group_title_stays_stable(self):
        src = _read(OVERLAY_PATH)
        assert extract_group_titles(src)["g_ev"] == "Event Overlay"

    def test_overlay_reconstructs_event_state_from_lean_slot(self):
        src = _read(OVERLAY_PATH)
        assert 'pack_slot(src_lean_pack_a, 2)' in src
        assert 'overlay_event_status_text' in src

    def test_event_status_plotchars_use_compile_time_chars(self):
        src = _read(OVERLAY_PATH)
        assert "char = rt_status" not in src
        for title, char in (
            ("Event Status · Market Block", "M"),
            ("Event Status · Earnings Block", "E"),
            ("Event Status · Incoming", "I"),
            ("Event Status · Cooldown", "C"),
            ("Event Status · Clear", "✓"),
        ):
            assert f'"{title}", "{char}"' in src

    def test_overlay_uses_only_lean_slot_2_for_runtime_state(self):
        src = _read(OVERLAY_PATH)
        assert tuple(_LEAN_SLOT_RE.findall(src)) == ("2",)


# ═════════════════════════════════════════════════════════════════
# 2. Overlay independence
# ═════════════════════════════════════════════════════════════════


class TestOverlayIndependence:
    def test_no_strategy_logic(self):
        src = _read(OVERLAY_PATH)
        assert "strategy(" not in src
        assert "strategy.entry" not in src
        assert "strategy.exit" not in src

    def test_no_order_logic(self):
        src = _read(OVERLAY_PATH)
        assert "strategy.order" not in src

    def test_no_import_of_core_engine(self):
        """Overlay must not import the Engine — it only reads the BUS."""
        src = _read(OVERLAY_PATH)
        assert "smc_core_engine" not in src.lower().replace("_", "").replace(" ", "")

    def test_no_trade_state_modification(self):
        src = _read(OVERLAY_PATH)
        for keyword in ["TRADE_STATE", "MARKET_REGIME", "GLOBAL_HEAT"]:
            # Must not write/assign these — reading is fine for regime fields
            assert f'{keyword} =' not in src or f'{keyword} =' in ''.join(
                line for line in src.splitlines()
                if line.strip().startswith("//")
            ), f"Overlay must not modify {keyword}"


# ═════════════════════════════════════════════════════════════════
# 3. Overlay reads only event-risk fields
# ═════════════════════════════════════════════════════════════════


class TestOverlayFieldScope:
    def test_event_risk_fields_referenced_in_canonical_order(self):
        src = _read(OVERLAY_PATH)
        assert tuple(_MP_FIELD_RE.findall(src)) == EXPECTED_MP_FIELDS_IN_ORDER

    def test_only_event_risk_fields_referenced(self):
        """Overlay should only read event-risk mp.FIELD values."""
        src = _read(OVERLAY_PATH)
        found = set(_MP_FIELD_RE.findall(src))
        unexpected = found - ALLOWED_MP_FIELDS
        assert not unexpected, (
            f"Overlay references non-event-risk fields: {unexpected}"
        )

    def test_reads_at_least_core_event_fields(self):
        """Must read at minimum the key event fields."""
        src = _read(OVERLAY_PATH)
        found = set(_MP_FIELD_RE.findall(src))
        required = {
            "EVENT_WINDOW_STATE", "EVENT_RISK_LEVEL",
            "NEXT_EVENT_NAME", "NEXT_EVENT_IMPACT",
            "MARKET_EVENT_BLOCKED", "SYMBOL_EVENT_BLOCKED",
        }
        missing = required - found
        assert not missing, f"Overlay is missing required fields: {missing}"


# ═════════════════════════════════════════════════════════════════
# 4. Pine syntax basics
# ═════════════════════════════════════════════════════════════════


class TestOverlayPineSyntax:
    def test_balanced_parentheses(self):
        src = _read(OVERLAY_PATH)
        depth = 0
        for i, ch in enumerate(src):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            assert depth >= 0, (
                f"Unmatched ')' at position {i} "
                f"(line {src[:i].count(chr(10)) + 1})"
            )
        assert depth == 0, f"Unclosed parentheses (depth={depth})"

    def test_balanced_brackets(self):
        src = _read(OVERLAY_PATH)
        depth = 0
        for i, ch in enumerate(src):
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
            assert depth >= 0, (
                f"Unmatched ']' at position {i} "
                f"(line {src[:i].count(chr(10)) + 1})"
            )
        assert depth == 0, f"Unclosed brackets (depth={depth})"

    def test_no_python_literals(self):
        src = _read(OVERLAY_PATH)
        assert "True" not in src or "True" in "".join(
            line for line in src.splitlines() if line.strip().startswith("//")
        )
        assert "False" not in src or "False" in "".join(
            line for line in src.splitlines() if line.strip().startswith("//")
        )
        assert "None" not in src or "None" in "".join(
            line for line in src.splitlines() if line.strip().startswith("//")
        )


# ═════════════════════════════════════════════════════════════════
# 5. Overlay visual elements declared
# ═════════════════════════════════════════════════════════════════


class TestOverlayVisualElements:
    def test_has_bgcolor(self):
        src = _read(OVERLAY_PATH)
        assert "bgcolor(" in src

    def test_has_line_new(self):
        src = _read(OVERLAY_PATH)
        assert "line.new(" in src

    def test_has_label_new(self):
        src = _read(OVERLAY_PATH)
        assert "label.new(" in src

    def test_has_alertcondition(self):
        src = _read(OVERLAY_PATH)
        assert "alertcondition(" in src

    def test_exact_event_line_uses_dst_aware_absolute_timestamp(self):
        src = _read(OVERLAY_PATH)
        assert 'timestamp("America/New_York"' in src
        assert "event_timestamp_et(mp.ASOF_DATE, ev_time)" in src
        assert re.search(
            r"line\.new\(event_ts, high, event_ts, low, xloc\.bar_time",
            src,
        )
        assert "line.new(bar_index" not in src

    def test_event_time_and_restriction_start_are_separate_semantics(self):
        src = _read(OVERLAY_PATH)
        assert "restriction_start_ts = event_time_valid ? event_ts -" in src
        assert "restriction_just_started" in src
        assert 'title = "Event Restriction Window Started"' in src
        assert 'title = "Event Restriction Hard Block Started"' in src
        assert "window_just_started" not in src

    def test_static_snapshot_does_not_shade_all_historical_bars(self):
        src = _read(OVERLAY_PATH)
        assert "in_pre_restriction" in src
        assert "in_post_restriction" in src
        assert "fallback_restriction" in src
        assert 'ev_window == "PRE_EVENT"  ? col_zone_pre' not in src


# ═════════════════════════════════════════════════════════════════
# 6. Generated library import snippet
# ═════════════════════════════════════════════════════════════════


class TestGeneratedImportSnippet:
    """Verify the generator produces a usage comment in the library header."""

    @pytest.fixture()
    def pine_text(self, tmp_path: pathlib.Path) -> str:
        from scripts.generate_smc_micro_profiles import write_pine_library

        write_pine_library(
            path=tmp_path / "lib.pine",
            lists={
                "clean_reclaim": [],
                "stop_hunt_prone": [],
                "midday_dead": [],
                "rth_only": [],
                "weak_premarket": [],
                "weak_afterhours": [],
                "fast_decay": [],
            },
            asof_date="2026-03-28",
            universe_size=0,
            enrichment=None,
        )
        return (tmp_path / "lib.pine").read_text(encoding="utf-8")

    def test_import_comment_present(self, pine_text: str):
        assert "import preuss_steffen/smc_micro_profiles_generated/1 as mp" in pine_text

    def test_usage_header_mentions_v5(self, pine_text: str):
        assert "v5" in pine_text

    def test_usage_header_mentions_field_count(self, pine_text: str):
        assert "v5.5b Lean" in pine_text
        assert "fields" in pine_text

    def test_usage_header_lists_event_risk_section(self, pine_text: str):
        assert "Event Risk" in pine_text

    def test_usage_header_mentions_export_const(self, pine_text: str):
        assert "export const" in pine_text
        assert "mp.FIELD_NAME" in pine_text

    def test_usage_header_before_first_export(self, pine_text: str):
        """Usage comment must appear before the first export const."""
        usage_pos = pine_text.find("// ── Usage")
        first_export = pine_text.find("export const")
        assert usage_pos != -1, "Usage comment block missing"
        assert usage_pos < first_export, "Usage comment must precede exports"
