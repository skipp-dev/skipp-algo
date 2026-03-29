"""Tests for smc_zone_intelligence — zone intelligence layer (v5.1).

Covers:
- defaults when no zones
- support-heavy context
- resistance-heavy context
- mitigated zones
- sweep count changes
"""
from __future__ import annotations

import pytest

from scripts.smc_zone_intelligence import DEFAULTS, build_zone_intelligence


def _support(level=100.0, strength=3, tests=2, sweeps=0, mitigated=False, volume=1000):
    return {"type": "support", "level": level, "strength": strength,
            "tests": tests, "sweeps": sweeps, "mitigated": mitigated, "volume": volume}


def _resistance(level=200.0, strength=3, tests=2, sweeps=0, mitigated=False, volume=1000):
    return {"type": "resistance", "level": level, "strength": strength,
            "tests": tests, "sweeps": sweeps, "mitigated": mitigated, "volume": volume}


# ═══════════════════════════════════════════════════════════════
# 1. Defaults
# ═══════════════════════════════════════════════════════════════


class TestDefaults:
    def test_no_zones_returns_defaults(self):
        assert build_zone_intelligence() == DEFAULTS

    def test_empty_zone_list(self):
        assert build_zone_intelligence(zones=[]) == DEFAULTS

    def test_all_keys_present(self):
        result = build_zone_intelligence()
        for key in DEFAULTS:
            assert key in result


# ═══════════════════════════════════════════════════════════════
# 2. Support-heavy context
# ═══════════════════════════════════════════════════════════════


class TestSupportHeavy:
    @pytest.fixture()
    def result(self):
        return build_zone_intelligence(
            zones=[
                _support(level=95.0, strength=5, volume=5000),
                _support(level=90.0, strength=3, volume=3000),
                _support(level=85.0, strength=2, volume=2000),
            ]
        )

    def test_support_count(self, result):
        assert result["ACTIVE_SUPPORT_COUNT"] == 3

    def test_resistance_count(self, result):
        assert result["ACTIVE_RESISTANCE_COUNT"] == 0

    def test_total_zone_count(self, result):
        assert result["ACTIVE_ZONE_COUNT"] == 3

    def test_bias_support_heavy(self, result):
        assert result["ZONE_CONTEXT_BIAS"] == "SUPPORT_HEAVY"

    def test_primary_support_strongest(self, result):
        assert result["PRIMARY_SUPPORT_LEVEL"] == 95.0
        assert result["PRIMARY_SUPPORT_STRENGTH"] == 5

    def test_liquidity_imbalance_positive(self, result):
        assert result["ZONE_LIQUIDITY_IMBALANCE"] == 1.0


# ═══════════════════════════════════════════════════════════════
# 3. Resistance-heavy context
# ═══════════════════════════════════════════════════════════════


class TestResistanceHeavy:
    @pytest.fixture()
    def result(self):
        return build_zone_intelligence(
            zones=[
                _resistance(level=210.0, strength=4, volume=6000),
                _resistance(level=220.0, strength=5, volume=4000),
                _resistance(level=230.0, strength=2, volume=2000),
                _support(level=190.0, strength=2, volume=1000),
            ]
        )

    def test_bias_resistance_heavy(self, result):
        assert result["ZONE_CONTEXT_BIAS"] == "RESISTANCE_HEAVY"

    def test_primary_resistance(self, result):
        assert result["PRIMARY_RESISTANCE_LEVEL"] == 220.0
        assert result["PRIMARY_RESISTANCE_STRENGTH"] == 5

    def test_imbalance_negative(self, result):
        assert result["ZONE_LIQUIDITY_IMBALANCE"] < 0


# ═══════════════════════════════════════════════════════════════
# 4. Mitigated zones
# ═══════════════════════════════════════════════════════════════


class TestMitigatedZones:
    def test_all_mitigated(self):
        result = build_zone_intelligence(
            zones=[
                _support(mitigated=True),
                _support(mitigated=True),
            ]
        )
        assert result["SUPPORT_MITIGATION_PCT"] == 100.0

    def test_half_mitigated(self):
        result = build_zone_intelligence(
            zones=[
                _resistance(mitigated=True),
                _resistance(mitigated=False),
            ]
        )
        assert result["RESISTANCE_MITIGATION_PCT"] == 50.0

    def test_none_mitigated(self):
        result = build_zone_intelligence(
            zones=[_support(mitigated=False), _resistance(mitigated=False)]
        )
        assert result["SUPPORT_MITIGATION_PCT"] == 0.0
        assert result["RESISTANCE_MITIGATION_PCT"] == 0.0


# ═══════════════════════════════════════════════════════════════
# 5. Sweep count changes
# ═══════════════════════════════════════════════════════════════


class TestSweeps:
    def test_support_sweeps_summed(self):
        result = build_zone_intelligence(
            zones=[
                _support(sweeps=2),
                _support(sweeps=1),
            ]
        )
        assert result["SUPPORT_SWEEP_COUNT"] == 3

    def test_resistance_sweeps_summed(self):
        result = build_zone_intelligence(
            zones=[
                _resistance(sweeps=3),
                _resistance(sweeps=0),
            ]
        )
        assert result["RESISTANCE_SWEEP_COUNT"] == 3

    def test_zero_sweeps(self):
        result = build_zone_intelligence(
            zones=[_support(sweeps=0), _resistance(sweeps=0)]
        )
        assert result["SUPPORT_SWEEP_COUNT"] == 0
        assert result["RESISTANCE_SWEEP_COUNT"] == 0


# ═══════════════════════════════════════════════════════════════
# 6. Neutral balanced
# ═══════════════════════════════════════════════════════════════


class TestBalanced:
    def test_equal_counts_neutral(self):
        result = build_zone_intelligence(
            zones=[
                _support(volume=1000),
                _resistance(volume=1000),
            ]
        )
        assert result["ZONE_CONTEXT_BIAS"] == "NEUTRAL"
        assert result["ZONE_LIQUIDITY_IMBALANCE"] == 0.0
