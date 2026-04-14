from __future__ import annotations

from typing import Any

_HIGH_TRUST_MIN_EVENTS = 3
_HIGH_TRUST_MIN_FAMILIES = 2

TRUST_TIERS = ("high", "guarded", "degraded", "insufficient")
PROVIDER_STATES = ("ok", "degraded", "unavailable")


def resolve_provider_state(
    *,
    structure_state: str,
    missing_domains: list[str],
    stale_domains: list[str],
    provider_health_issue_count: int,
) -> str:
    if structure_state in {"none", "unknown"}:
        return "unavailable"
    if missing_domains or stale_domains or provider_health_issue_count > 0:
        return "degraded"
    return "ok"


def resolve_trust_tier(
    *,
    provider_state: str,
    measurement_status: str,
    measurement_available: bool,
    measurement_events: int,
    measurement_family_count: int,
    measurement_quality_tier: str,
    measurement_warning_count: int,
) -> str:
    if provider_state == "unavailable":
        return "insufficient"
    if measurement_status != "available" or not measurement_available:
        return "insufficient"
    if measurement_events <= 0:
        return "insufficient"
    if provider_state == "degraded":
        return "degraded"
    if measurement_warning_count > 0:
        return "guarded"
    if measurement_events < _HIGH_TRUST_MIN_EVENTS:
        return "guarded"
    if measurement_family_count < _HIGH_TRUST_MIN_FAMILIES:
        return "guarded"
    if measurement_quality_tier in {"good", "high"}:
        return "high"
    return "guarded"


def resolve_trust_main_blocker(
    *,
    structure_state: str,
    missing_domains: list[str],
    stale_domains: list[str],
    provider_health_issue_count: int,
    measurement_status: str,
    measurement_available: bool,
    measurement_events: int,
    measurement_family_count: int,
    measurement_quality_tier: str,
    measurement_warnings: list[str],
) -> str:
    if structure_state in {"none", "unknown"}:
        return "No structure source available"
    if missing_domains:
        return f"Missing meta domains: {', '.join(missing_domains)}"
    if stale_domains:
        return f"Stale meta domains: {', '.join(stale_domains)}"
    if provider_health_issue_count > 0:
        return f"Structure provider health issues: {provider_health_issue_count}"
    if measurement_status != "available" or not measurement_available:
        return "Measurement evidence unavailable"
    if measurement_events <= 0:
        return "No measured events yet"
    if measurement_warnings:
        return measurement_warnings[0]
    if measurement_events < _HIGH_TRUST_MIN_EVENTS:
        return f"Measurement sample thin: {measurement_events} event(s)"
    if measurement_family_count < _HIGH_TRUST_MIN_FAMILIES:
        family_label = "family" if measurement_family_count == 1 else "families"
        return f"Measurement coverage thin: {measurement_family_count} {family_label}"
    if measurement_quality_tier not in {"good", "high"}:
        return "Measurement quality not yet mature"
    return "No active blocker"


def derive_trust_summary(
    *,
    provider_state: str,
    structure_state: str,
    structure_missing_categories: list[str],
    missing_domains: list[str],
    stale_domains: list[str],
    provider_health_issue_count: int,
    measurement_status: str,
    measurement_available: bool,
    measurement_events: int,
    measurement_family_count: int,
    measurement_quality_tier: str,
    measurement_quality_score: float | None,
    measurement_warning_count: int,
    measurement_warnings: list[str],
) -> dict[str, Any]:
    trust_state = resolve_trust_tier(
        provider_state=provider_state,
        measurement_status=measurement_status,
        measurement_available=measurement_available,
        measurement_events=measurement_events,
        measurement_family_count=measurement_family_count,
        measurement_quality_tier=measurement_quality_tier,
        measurement_warning_count=measurement_warning_count,
    )
    main_blocker = resolve_trust_main_blocker(
        structure_state=structure_state,
        missing_domains=missing_domains,
        stale_domains=stale_domains,
        provider_health_issue_count=provider_health_issue_count,
        measurement_status=measurement_status,
        measurement_available=measurement_available,
        measurement_events=measurement_events,
        measurement_family_count=measurement_family_count,
        measurement_quality_tier=measurement_quality_tier,
        measurement_warnings=measurement_warnings,
    )

    return {
        "trust_state": trust_state,
        "provider_state": provider_state,
        "main_blocker": main_blocker,
        "measurement_status": measurement_status,
        "measurement_events": measurement_events,
        "measurement_family_count": measurement_family_count,
        "measurement_quality_tier": measurement_quality_tier,
        "measurement_quality_score": measurement_quality_score,
        "measurement_warning_count": measurement_warning_count,
        "provider_health_issue_count": provider_health_issue_count,
        "structure_state": structure_state,
        "structure_missing_categories": structure_missing_categories,
        "missing_domains": missing_domains,
        "stale_domains": stale_domains,
    }
