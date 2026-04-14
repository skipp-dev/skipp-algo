from __future__ import annotations

from smc_integration.trust_tier import (
    PROVIDER_STATES,
    TRUST_TIERS,
    derive_trust_summary,
    resolve_provider_state,
    resolve_trust_main_blocker,
    resolve_trust_tier,
)


def test_trust_tiers_are_bounded_constants() -> None:
    assert TRUST_TIERS == ("high", "guarded", "degraded", "insufficient")
    assert PROVIDER_STATES == ("ok", "degraded", "unavailable")


def test_resolve_provider_state_ok() -> None:
    assert resolve_provider_state(
        structure_state="full",
        missing_domains=[],
        stale_domains=[],
        provider_health_issue_count=0,
    ) == "ok"


def test_resolve_provider_state_unavailable_for_none_structure() -> None:
    for mode in ("none", "unknown"):
        assert resolve_provider_state(
            structure_state=mode,
            missing_domains=[],
            stale_domains=[],
            provider_health_issue_count=0,
        ) == "unavailable"


def test_resolve_provider_state_degraded_for_stale_domain() -> None:
    assert resolve_provider_state(
        structure_state="full",
        missing_domains=[],
        stale_domains=["volume"],
        provider_health_issue_count=0,
    ) == "degraded"


def test_resolve_provider_state_degraded_for_health_issues() -> None:
    assert resolve_provider_state(
        structure_state="full",
        missing_domains=[],
        stale_domains=[],
        provider_health_issue_count=1,
    ) == "degraded"


def _high_tier_kwargs() -> dict:
    return {
        "provider_state": "ok",
        "measurement_status": "available",
        "measurement_available": True,
        "measurement_events": 5,
        "measurement_family_count": 3,
        "measurement_quality_tier": "high",
        "measurement_warning_count": 0,
    }


def test_resolve_trust_tier_high() -> None:
    assert resolve_trust_tier(**_high_tier_kwargs()) == "high"


def test_resolve_trust_tier_insufficient_for_unavailable_provider() -> None:
    kw = _high_tier_kwargs()
    kw["provider_state"] = "unavailable"
    assert resolve_trust_tier(**kw) == "insufficient"


def test_resolve_trust_tier_insufficient_for_no_measurement() -> None:
    kw = _high_tier_kwargs()
    kw["measurement_status"] = "unavailable"
    kw["measurement_available"] = False
    assert resolve_trust_tier(**kw) == "insufficient"


def test_resolve_trust_tier_insufficient_for_zero_events() -> None:
    kw = _high_tier_kwargs()
    kw["measurement_events"] = 0
    assert resolve_trust_tier(**kw) == "insufficient"


def test_resolve_trust_tier_degraded_for_degraded_provider() -> None:
    kw = _high_tier_kwargs()
    kw["provider_state"] = "degraded"
    assert resolve_trust_tier(**kw) == "degraded"


def test_resolve_trust_tier_guarded_for_warnings() -> None:
    kw = _high_tier_kwargs()
    kw["measurement_warning_count"] = 1
    assert resolve_trust_tier(**kw) == "guarded"


def test_resolve_trust_tier_guarded_for_thin_events() -> None:
    kw = _high_tier_kwargs()
    kw["measurement_events"] = 2
    assert resolve_trust_tier(**kw) == "guarded"


def test_resolve_trust_tier_guarded_for_thin_families() -> None:
    kw = _high_tier_kwargs()
    kw["measurement_family_count"] = 1
    assert resolve_trust_tier(**kw) == "guarded"


def test_resolve_trust_tier_guarded_for_low_quality() -> None:
    kw = _high_tier_kwargs()
    kw["measurement_quality_tier"] = "ok"
    assert resolve_trust_tier(**kw) == "guarded"


def test_resolve_trust_tier_is_deterministic() -> None:
    kw = _high_tier_kwargs()
    results = {resolve_trust_tier(**kw) for _ in range(100)}
    assert results == {"high"}


def test_resolve_trust_main_blocker_waterfall_priority() -> None:
    assert resolve_trust_main_blocker(
        structure_state="none",
        missing_domains=["volume"],
        stale_domains=["news"],
        provider_health_issue_count=5,
        measurement_status="unavailable",
        measurement_available=False,
        measurement_events=0,
        measurement_family_count=0,
        measurement_quality_tier="unknown",
        measurement_warnings=["drift"],
    ) == "No structure source available"


def test_resolve_trust_main_blocker_no_active_blocker() -> None:
    assert resolve_trust_main_blocker(
        structure_state="full",
        missing_domains=[],
        stale_domains=[],
        provider_health_issue_count=0,
        measurement_status="available",
        measurement_available=True,
        measurement_events=5,
        measurement_family_count=3,
        measurement_quality_tier="high",
        measurement_warnings=[],
    ) == "No active blocker"


def test_derive_trust_summary_returns_canonical_schema() -> None:
    summary = derive_trust_summary(
        provider_state="ok",
        structure_state="full",
        structure_missing_categories=[],
        missing_domains=[],
        stale_domains=[],
        provider_health_issue_count=0,
        measurement_status="available",
        measurement_available=True,
        measurement_events=5,
        measurement_family_count=3,
        measurement_quality_tier="high",
        measurement_quality_score=0.88,
        measurement_warning_count=0,
        measurement_warnings=[],
    )

    assert summary["trust_state"] == "high"
    assert summary["provider_state"] == "ok"
    assert summary["main_blocker"] == "No active blocker"
    assert set(summary.keys()) == {
        "trust_state", "provider_state", "main_blocker",
        "measurement_status", "measurement_events", "measurement_family_count",
        "measurement_quality_tier", "measurement_quality_score",
        "measurement_warning_count", "provider_health_issue_count",
        "structure_state", "structure_missing_categories",
        "missing_domains", "stale_domains",
    }


def test_derive_trust_summary_degraded_state() -> None:
    summary = derive_trust_summary(
        provider_state="degraded",
        structure_state="partial",
        structure_missing_categories=["fvg"],
        missing_domains=[],
        stale_domains=["volume"],
        provider_health_issue_count=1,
        measurement_status="available",
        measurement_available=True,
        measurement_events=5,
        measurement_family_count=3,
        measurement_quality_tier="high",
        measurement_quality_score=0.88,
        measurement_warning_count=0,
        measurement_warnings=[],
    )

    assert summary["trust_state"] == "degraded"
    assert summary["provider_state"] == "degraded"
    assert summary["main_blocker"] == "Stale meta domains: volume"


def test_all_trust_tiers_are_reachable() -> None:
    reached = set()

    reached.add(resolve_trust_tier(**_high_tier_kwargs()))

    kw = _high_tier_kwargs()
    kw["measurement_warning_count"] = 1
    reached.add(resolve_trust_tier(**kw))

    kw = _high_tier_kwargs()
    kw["provider_state"] = "degraded"
    reached.add(resolve_trust_tier(**kw))

    kw = _high_tier_kwargs()
    kw["provider_state"] = "unavailable"
    reached.add(resolve_trust_tier(**kw))

    assert reached == set(TRUST_TIERS)
