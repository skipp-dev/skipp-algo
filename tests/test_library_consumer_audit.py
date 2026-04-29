"""Tests for scripts/audit_library_consumers.py (WP-OV6)."""

from __future__ import annotations

from pathlib import Path

from scripts.audit_library_consumers import (
    audit,
    extract_consumer_refs,
    extract_exports,
)

_LIBRARY_SNIPPET = """\
//@version=6
library("smc_micro_profiles_generated")
export const string ASOF_DATE = "2026-04-10"
export const int LOOKBACK_DAYS = 20
export const string MARKET_REGIME = "bullish"
export const float ENSEMBLE_QUALITY_SCORE = 0.72
export const string UNUSED_FIELD = "never_read"
"""

_CONSUMER_SNIPPET = """\
//@version=6
import preuss_steffen/smc_micro_profiles_generated/1 as mp
regime = mp.MARKET_REGIME
score  = mp.ENSEMBLE_QUALITY_SCORE
date   = mp.ASOF_DATE
days   = mp.LOOKBACK_DAYS
"""


class TestExtractExports:
    def test_extracts_field_names(self) -> None:
        fields = extract_exports(_LIBRARY_SNIPPET)
        assert "ASOF_DATE" in fields
        assert "MARKET_REGIME" in fields
        assert "UNUSED_FIELD" in fields
        assert len(fields) == 5


class TestExtractConsumerRefs:
    def test_extracts_mp_references(self) -> None:
        refs = extract_consumer_refs([_CONSUMER_SNIPPET])
        assert refs == {"MARKET_REGIME", "ENSEMBLE_QUALITY_SCORE", "ASOF_DATE", "LOOKBACK_DAYS"}


class TestAudit:
    def test_finds_no_consumer_fields(self, tmp_path: Path) -> None:
        lib_path = tmp_path / "lib.pine"
        lib_path.write_text(_LIBRARY_SNIPPET)

        consumer_path = tmp_path / "consumer.pine"
        consumer_path.write_text(_CONSUMER_SNIPPET)

        result = audit(
            library_path=lib_path,
            consumer_paths=[consumer_path],
        )
        assert "UNUSED_FIELD" in result.no_consumer
        assert len(result.missing_export) == 0
        assert result.exported == {"ASOF_DATE", "LOOKBACK_DAYS", "MARKET_REGIME", "ENSEMBLE_QUALITY_SCORE", "UNUSED_FIELD"}
        assert result.consumed == {"ASOF_DATE", "LOOKBACK_DAYS", "MARKET_REGIME", "ENSEMBLE_QUALITY_SCORE"}

    def test_finds_missing_exports(self, tmp_path: Path) -> None:
        lib_path = tmp_path / "lib.pine"
        lib_path.write_text('export const string FOO = "bar"\n')

        consumer_path = tmp_path / "consumer.pine"
        consumer_path.write_text("x = mp.FOO\ny = mp.MISSING_FIELD\n")

        result = audit(library_path=lib_path, consumer_paths=[consumer_path])
        assert "MISSING_FIELD" in result.missing_export
        assert "FOO" not in result.no_consumer

    def test_empty_consumers(self, tmp_path: Path) -> None:
        lib_path = tmp_path / "lib.pine"
        lib_path.write_text('export const string A = "x"\n')

        result = audit(library_path=lib_path, consumer_paths=[])
        assert result.no_consumer == {"A"}
        assert result.consumed == set()
