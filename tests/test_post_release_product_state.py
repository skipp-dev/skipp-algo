"""Tests for post-release product-state validation (ENG-WS5-04)."""
from __future__ import annotations

from scripts.post_release_product_state import (
    HERO_ACTION_REQUIRED,
    HERO_MARKET_REQUIRED,
    HERO_QUALITY_REQUIRED,
    TRUST_REQUIRED,
    CheckStatus,
    validate_post_release,
)


def _market(**overrides) -> dict:
    base = {"regime": "Trend Up", "bias": "Long", "session": "RTH",
            "trust": "high", "freshness": "fresh"}
    base.update(overrides)
    return base


def _quality(**overrides) -> dict:
    base = {"tier": "A", "why_now": "OB+FVG confluence",
            "main_risk": "Liquidity sweep", "family_health": "OB:ok|FVG:ok"}
    base.update(overrides)
    return base


def _action(**overrides) -> dict:
    base = {"verb": "ENTER", "verb_de": "EINSTEIGEN",
            "reason": "Quality A + clean trust",
            "degradation": "none", "quality": "A"}
    base.update(overrides)
    return base


def _trust(**overrides) -> dict:
    base = {"trust": "high", "freshness": "fresh",
            "trust_reason": "all sources fresh"}
    base.update(overrides)
    return base


class TestAllPass:
    def test_full_payload_passes(self) -> None:
        report = validate_post_release(
            market_mode=_market(),
            setup_quality=_quality(),
            action=_action(),
            trust=_trust(),
        )
        assert report.overall_status is CheckStatus.PASS
        assert all(c.status is CheckStatus.PASS for c in report.checks)
        assert "besetzt" in report.summary


class TestProductLanguage:
    def test_failure_messages_reference_product_functions(self) -> None:
        report = validate_post_release(
            market_mode=_market(regime=""),  # empty -> fail
            setup_quality=_quality(),
            action=_action(),
            trust=_trust(),
        )
        assert report.overall_status is CheckStatus.FAIL
        failures = [c for c in report.checks if c.status is CheckStatus.FAIL]
        assert len(failures) == 1
        # Product-facing language, not technical pipeline step.
        assert "Hero" in failures[0].product_function
        assert "Marktregime" in failures[0].product_function

    def test_missing_field_records_explicit_gap(self) -> None:
        broken_quality = {k: v for k, v in _quality().items() if k != "tier"}
        report = validate_post_release(
            market_mode=_market(),
            setup_quality=broken_quality,
            action=_action(),
            trust=_trust(),
        )
        assert report.overall_status is CheckStatus.FAIL
        failed_fields = [c.field for c in report.checks
                         if c.status is CheckStatus.FAIL]
        assert "tier" in failed_fields


class TestSkippedSurfaces:
    def test_missing_payload_marks_surface_skipped(self) -> None:
        report = validate_post_release(
            market_mode=_market(),
            setup_quality=_quality(),
            action=None,             # surface unavailable
            trust=_trust(),
        )
        action_checks = [c for c in report.checks if c.surface == "Action"]
        assert len(action_checks) == len(HERO_ACTION_REQUIRED)
        assert all(c.status is CheckStatus.SKIPPED for c in action_checks)

    def test_all_skipped_returns_skipped_overall(self) -> None:
        report = validate_post_release(
            market_mode=None, setup_quality=None,
            action=None, trust=None,
        )
        assert report.overall_status is CheckStatus.SKIPPED


class TestRequiredKeyTables:
    def test_required_keys_published(self) -> None:
        # Pin the required keys so the validation contract is visible.
        assert HERO_MARKET_REQUIRED == ("regime", "bias", "session",
                                        "trust", "freshness")
        assert HERO_QUALITY_REQUIRED == ("tier", "why_now", "main_risk",
                                         "family_health")
        assert HERO_ACTION_REQUIRED == ("verb", "verb_de", "reason",
                                        "degradation", "quality")
        assert TRUST_REQUIRED == ("trust", "freshness", "trust_reason")


class TestAsDict:
    def test_failure_block_lists_failures(self) -> None:
        report = validate_post_release(
            market_mode=_market(regime=None),
            setup_quality=_quality(),
            action=_action(),
            trust=_trust(),
        )
        d = report.as_dict()
        assert d["overall_status"] == "fail"
        assert len(d["failures"]) == 1
        assert d["failures"][0]["field"] == "regime"
