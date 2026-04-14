from __future__ import annotations

from smc_integration import service


def _raw_meta(*, missing_domains: list[str] | None = None, stale_domains: list[str] | None = None) -> dict[str, object]:
    diagnostics: dict[str, object] = {
        "volume": "present",
        "technical": "present",
        "news": "present",
        "volume_stale": False,
        "technical_stale": False,
        "news_stale": False,
    }
    for domain in stale_domains or []:
        diagnostics[f"{domain}_stale"] = True

    return {
        "meta_domains_missing": list(missing_domains or []),
        "meta_domain_diagnostics": diagnostics,
        "volume": {"stale": False},
    }


def _structure_status(*, mode: str = "full", health_issues: int = 0) -> dict[str, object]:
    return {
        "selected_structure_mode": mode,
        "selected_missing_categories": [],
        "selected_health_issue_count": health_issues,
    }


def _measurement_summary(
    *,
    status: str = "available",
    available: bool = True,
    events: int = 4,
    families: list[str] | None = None,
    quality_tier: str = "high",
    quality_score: float | None = 0.84,
    warnings: list[str] | None = None,
) -> dict[str, object]:
    return {
        "status": status,
        "measurement_evidence_present": available,
        "scoring": {
            "n_events": events,
            "families_present": list(families or ["BOS", "OB"]),
        },
        "ensemble_quality": {
            "tier": quality_tier,
            "score": quality_score,
        },
        "warnings": list(warnings or []),
    }


def test_trust_summary_is_high_for_clean_mature_truth() -> None:
    summary = service._build_trust_summary(
        raw_meta=_raw_meta(),
        structure_status=_structure_status(),
        measurement_summary=_measurement_summary(events=5, families=["BOS", "OB"], quality_tier="high", quality_score=0.88),
    )

    assert summary == {
        "trust_state": "high",
        "provider_state": "ok",
        "main_blocker": "No active blocker",
        "measurement_status": "available",
        "measurement_events": 5,
        "measurement_family_count": 2,
        "measurement_quality_tier": "high",
        "measurement_quality_score": 0.88,
        "measurement_warning_count": 0,
        "provider_health_issue_count": 0,
        "structure_state": "full",
        "structure_missing_categories": [],
        "missing_domains": [],
        "stale_domains": [],
    }


def test_trust_summary_is_guarded_for_thin_measurement_sample() -> None:
    summary = service._build_trust_summary(
        raw_meta=_raw_meta(),
        structure_status=_structure_status(),
        measurement_summary=_measurement_summary(events=1, families=["BOS"], quality_tier="high", quality_score=0.84),
    )

    assert summary["trust_state"] == "guarded"
    assert summary["provider_state"] == "ok"
    assert summary["main_blocker"] == "Measurement sample thin: 1 event(s)"
    assert summary["measurement_family_count"] == 1
    assert summary["measurement_quality_tier"] == "high"


def test_trust_summary_is_degraded_when_runtime_truth_is_degraded() -> None:
    summary = service._build_trust_summary(
        raw_meta=_raw_meta(stale_domains=["technical"]),
        structure_status=_structure_status(health_issues=1),
        measurement_summary=_measurement_summary(events=5, families=["BOS", "OB"], quality_tier="high", quality_score=0.87),
    )

    assert summary["trust_state"] == "degraded"
    assert summary["provider_state"] == "degraded"
    assert summary["main_blocker"] == "Stale meta domains: technical"
    assert summary["provider_health_issue_count"] == 1
    assert summary["stale_domains"] == ["technical"]


def test_trust_summary_is_insufficient_without_measurement_truth() -> None:
    summary = service._build_trust_summary(
        raw_meta=_raw_meta(),
        structure_status=_structure_status(),
        measurement_summary=_measurement_summary(status="unavailable", available=False, events=0, families=[], quality_tier="unknown", quality_score=None),
    )

    assert summary["trust_state"] == "insufficient"
    assert summary["provider_state"] == "ok"
    assert summary["main_blocker"] == "Measurement evidence unavailable"
    assert summary["measurement_quality_tier"] == "unknown"
    assert summary["measurement_quality_score"] is None