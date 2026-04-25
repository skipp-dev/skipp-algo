"""Semantic tests for the v5.5 OB Context Light adapter."""
from __future__ import annotations

from scripts.smc_ob_context_light import build_ob_context_light, DEFAULTS, FRESHNESS_MAX_BARS


class TestDefaults:
    def test_no_input_returns_defaults(self):
        result = build_ob_context_light()
        assert result == DEFAULTS

    def test_field_count(self):
        assert len(DEFAULTS) == 5

    def test_default_side_is_none(self):
        assert DEFAULTS["PRIMARY_OB_SIDE"] == "NONE"


class TestPrimarySelection:
    def test_fresh_bull_ob(self):
        ob = {"BULL_OB_FRESHNESS": 3, "NEAREST_BULL_OB_LEVEL": 100.0}
        result = build_ob_context_light(order_blocks=ob, current_price=102.0)
        assert result["PRIMARY_OB_SIDE"] == "BULL"
        assert result["OB_FRESH"] is True
        assert result["OB_AGE_BARS"] == 3
        assert result["OB_MITIGATION_STATE"] == "fresh"

    def test_fresh_bear_ob(self):
        ob = {"BEAR_OB_FRESHNESS": 5, "NEAREST_BEAR_OB_LEVEL": 105.0}
        result = build_ob_context_light(order_blocks=ob, current_price=100.0)
        assert result["PRIMARY_OB_SIDE"] == "BEAR"
        assert result["OB_FRESH"] is True

    def test_bull_preferred_when_both_fresh(self):
        """Bull preferred when equally fresh (higher score from freshness)."""
        ob = {
            "BULL_OB_FRESHNESS": 3,
            "BEAR_OB_FRESHNESS": 3,
            "NEAREST_BULL_OB_LEVEL": 100.0,
            "NEAREST_BEAR_OB_LEVEL": 105.0,
        }
        result = build_ob_context_light(order_blocks=ob, current_price=102.0)
        assert result["PRIMARY_OB_SIDE"] == "BULL"

    def test_fresher_ob_wins(self):
        ob = {
            "BULL_OB_FRESHNESS": 20,
            "BEAR_OB_FRESHNESS": 3,
            "NEAREST_BULL_OB_LEVEL": 100.0,
            "NEAREST_BEAR_OB_LEVEL": 105.0,
        }
        result = build_ob_context_light(order_blocks=ob, current_price=102.0)
        assert result["PRIMARY_OB_SIDE"] == "BEAR"

    def test_unmitigated_preferred_over_mitigated(self):
        ob = {
            "BULL_OB_FRESHNESS": 5,
            "BULL_OB_MITIGATED": True,
            "BEAR_OB_FRESHNESS": 5,
            "BEAR_OB_MITIGATED": False,
            "NEAREST_BULL_OB_LEVEL": 100.0,
            "NEAREST_BEAR_OB_LEVEL": 105.0,
        }
        result = build_ob_context_light(order_blocks=ob, current_price=102.0)
        assert result["PRIMARY_OB_SIDE"] == "BEAR"


class TestMitigationState:
    def test_fresh_within_threshold(self):
        ob = {"BULL_OB_FRESHNESS": FRESHNESS_MAX_BARS, "NEAREST_BULL_OB_LEVEL": 100.0}
        result = build_ob_context_light(order_blocks=ob, current_price=102.0)
        assert result["OB_MITIGATION_STATE"] == "fresh"
        assert result["OB_FRESH"] is True

    def test_touched_past_threshold(self):
        ob = {"BULL_OB_FRESHNESS": FRESHNESS_MAX_BARS + 5, "NEAREST_BULL_OB_LEVEL": 100.0}
        result = build_ob_context_light(order_blocks=ob, current_price=102.0)
        assert result["OB_MITIGATION_STATE"] == "touched"
        assert result["OB_FRESH"] is False

    def test_stale_old_ob(self):
        ob = {"BULL_OB_FRESHNESS": 40, "NEAREST_BULL_OB_LEVEL": 100.0}
        result = build_ob_context_light(order_blocks=ob, current_price=102.0)
        assert result["OB_MITIGATION_STATE"] == "stale"

    def test_mitigated_flag_overrides(self):
        ob = {"BULL_OB_FRESHNESS": 3, "BULL_OB_MITIGATED": True, "NEAREST_BULL_OB_LEVEL": 100.0}
        result = build_ob_context_light(order_blocks=ob, current_price=102.0)
        assert result["OB_MITIGATION_STATE"] == "mitigated"
        assert result["OB_FRESH"] is False


class TestDistance:
    def test_distance_calculation(self):
        ob = {"BULL_OB_FRESHNESS": 3, "NEAREST_BULL_OB_LEVEL": 100.0}
        result = build_ob_context_light(order_blocks=ob, current_price=102.0)
        expected = abs(102.0 - 100.0) / 102.0 * 100.0
        assert abs(result["PRIMARY_OB_DISTANCE"] - round(expected, 4)) < 0.001

    def test_zero_price_no_crash(self):
        ob = {"BULL_OB_FRESHNESS": 3, "NEAREST_BULL_OB_LEVEL": 100.0}
        result = build_ob_context_light(order_blocks=ob, current_price=0.0)
        assert result["PRIMARY_OB_DISTANCE"] == 0.0


class TestOverrides:
    def test_override_side(self):
        result = build_ob_context_light(overrides={"PRIMARY_OB_SIDE": "BEAR"})
        assert result["PRIMARY_OB_SIDE"] == "BEAR"

    def test_override_on_computed(self):
        ob = {"BULL_OB_FRESHNESS": 3, "NEAREST_BULL_OB_LEVEL": 100.0}
        result = build_ob_context_light(
            order_blocks=ob, current_price=102.0,
            overrides={"OB_FRESH": False}
        )
        assert result["OB_FRESH"] is False


class TestEmptyOBSubnormalRobustness:
    """Regression: H-1 (system review 2026-04-24).

    The "no OBs at all" early-return previously used ``level == 0.0``
    which would silently fail for IEEE-754 subnormals if upstream ever
    switches the empty-sentinel from a literal 0.0 to a computed value.
    The fix uses ``abs(level) < _OB_LEVEL_EPS`` (1e-12) — well above the
    subnormal range and well below any tradable price.
    """

    def test_subnormal_bull_level_still_treated_as_empty(self):
        import math
        ob = {
            "BULL_OB_FRESHNESS": 0,
            "BEAR_OB_FRESHNESS": 0,
            "NEAREST_BULL_OB_LEVEL": math.ulp(0.0),  # ≈ 5e-324, smallest subnormal
            "NEAREST_BEAR_OB_LEVEL": 0.0,
        }
        result = build_ob_context_light(order_blocks=ob, current_price=100.0)
        assert result == DEFAULTS, (
            "Subnormal bull level slipped past the empty-OB early-return — "
            "the level == 0.0 comparison has regressed to exact equality."
        )

    def test_subnormal_negative_levels_still_treated_as_empty(self):
        import math
        ob = {
            "BULL_OB_FRESHNESS": 0,
            "BEAR_OB_FRESHNESS": 0,
            "NEAREST_BULL_OB_LEVEL": -math.ulp(0.0),
            "NEAREST_BEAR_OB_LEVEL": math.ulp(0.0),
        }
        result = build_ob_context_light(order_blocks=ob, current_price=100.0)
        assert result == DEFAULTS

    def test_real_level_just_above_eps_is_not_treated_as_empty(self):
        """Sanity: a real OB level (1e-2 / one tick) must NOT be empty."""
        ob = {
            "BULL_OB_FRESHNESS": 5,
            "BEAR_OB_FRESHNESS": 0,
            "NEAREST_BULL_OB_LEVEL": 1e-2,
            "NEAREST_BEAR_OB_LEVEL": 0.0,
        }
        result = build_ob_context_light(order_blocks=ob, current_price=100.0)
        assert result["PRIMARY_OB_SIDE"] == "BULL"

