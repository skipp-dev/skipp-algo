from __future__ import annotations

import pytest

from scripts.smc_macro_bias import filter_us_events, get_consensus, macro_bias_with_components


def test_filter_us_events_promotes_usd_records_without_country() -> None:
    events = [
        {
            "country": "",
            "currency": "USD",
            "date": "2026-04-13 08:30:00",
            "event": "GDP Growth Rate QoQ",
        },
        {
            "country": "JP",
            "currency": "JPY",
            "date": "2026-04-13 23:50:00",
            "event": "M3 Money Supply (Mar)",
        },
    ]

    filtered = filter_us_events(events)

    assert filtered == [
        {
            "country": "US",
            "currency": "USD",
            "date": "2026-04-13 08:30:00",
            "event": "GDP Growth Rate QoQ",
        }
    ]


def test_filter_us_events_rejects_non_us_country_even_with_usd_currency() -> None:
    events = [
        {
            "country": "SV",
            "currency": "USD",
            "date": "2026-04-13 18:30:00",
            "event": "Inflation Rate YoY (Mar)",
        },
        {
            "country": "United States",
            "currency": "usd",
            "date": "2026-04-13 14:00:00",
            "event": "Existing Home Sales MoM (Mar)",
        },
    ]

    filtered = filter_us_events(events)

    assert filtered == [
        {
            "country": "US",
            "currency": "USD",
            "date": "2026-04-13 14:00:00",
            "event": "Existing Home Sales MoM (Mar)",
        }
    ]


def test_macro_bias_with_components_frozen_payload_normalizes_scope_consensus_and_dedupe() -> None:
    events = [
        {
            "country": "",
            "currency": "USD",
            "date": "2026-04-13 08:30:00",
            "event": "GDP Growth Rate QoQ",
            "actual": 3.1,
            "estimate": 2.3,
            "impact": "High",
            "unit": "%",
        },
        {
            "country": "US",
            "currency": "USD",
            "date": "2026-04-13 08:30:00",
            "event": "Gross Domestic Product QoQ",
            "actual": 3.0,
            "consensus": 2.2,
            "impact": "Medium",
            "unit": "%",
        },
        {
            "country": "US",
            "currency": "USD",
            "date": "2026-04-13 08:30:00",
            "event": "Initial Jobless Claims",
            "actual": 221,
            "forecast": 235,
            "impact": "High",
            "unit": "k",
        },
        {
            "country": "JP",
            "currency": "JPY",
            "date": "2026-04-13 23:50:00",
            "event": "M3 Money Supply (Mar)",
            "actual": 1.8,
            "estimate": 1.9,
            "impact": "Low",
            "unit": "%",
        },
    ]

    analysis = macro_bias_with_components(events)

    assert analysis["macro_bias"] == pytest.approx(0.75)
    assert analysis["input_diagnostics"] == {
        "raw_event_count": 4,
        "us_scoped_event_count": 3,
        "deduped_event_count": 2,
        "scored_event_count": 2,
        "contributing_event_count": 2,
        "rejection_reason_counts": {
            "deduped_duplicate": 1,
            "non_us_event": 1,
        },
        "quality_flag_counts": {},
    }

    audit_by_event = {entry["event"]: entry for entry in analysis["event_audit"]}
    assert audit_by_event["GDP Growth Rate QoQ"]["passes_us_scope"] is True
    assert audit_by_event["GDP Growth Rate QoQ"]["country"] == "US"
    assert audit_by_event["GDP Growth Rate QoQ"]["consensus_field"] == "estimate"
    assert audit_by_event["GDP Growth Rate QoQ"]["canonical_event"] == "gdp_qoq"
    assert audit_by_event["GDP Growth Rate QoQ"]["contributed_to_bias"] is True
    assert audit_by_event["Gross Domestic Product QoQ"]["rejection_reasons"] == ["deduped_duplicate"]
    assert audit_by_event["Gross Domestic Product QoQ"]["passes_dedupe"] is False
    assert audit_by_event["Initial Jobless Claims"]["consensus_field"] == "forecast"
    assert audit_by_event["Initial Jobless Claims"]["canonical_event"] == "jobless_claims"
    assert audit_by_event["Initial Jobless Claims"]["contributed_to_bias"] is True
    assert audit_by_event["M3 Money Supply (Mar)"]["rejection_reasons"] == ["non_us_event"]

    score_components = {
        component["canonical_event"]: component for component in analysis["score_components"]
    }
    assert score_components["gdp_qoq"]["consensus_field"] == "estimate"
    assert score_components["gdp_qoq"]["weight"] == pytest.approx(0.5)
    assert score_components["gdp_qoq"]["contribution"] == pytest.approx(0.5)
    assert score_components["jobless_claims"]["consensus_field"] == "forecast"
    assert score_components["jobless_claims"]["weight"] == pytest.approx(1.0)
    assert score_components["jobless_claims"]["contribution"] == pytest.approx(1.0)


def test_macro_bias_with_components_rejects_non_us_usd_rows_but_accepts_us_alias() -> None:
    events = [
        {
            "country": "SV",
            "currency": "USD",
            "date": "2026-04-13 18:30:00",
            "event": "Inflation Rate YoY (Mar)",
            "actual": 1.6,
            "estimate": 1.4,
            "impact": "Low",
            "unit": "%",
        },
        {
            "country": "United States",
            "currency": "usd",
            "date": "2026-04-13 14:00:00",
            "event": "Existing Home Sales MoM (Mar)",
            "actual": -1.5,
            "estimate": -2.0,
            "impact": "High",
            "unit": "%",
        },
    ]

    analysis = macro_bias_with_components(events)

    assert analysis["input_diagnostics"] == {
        "raw_event_count": 2,
        "us_scoped_event_count": 1,
        "deduped_event_count": 1,
        "scored_event_count": 1,
        "contributing_event_count": 1,
        "rejection_reason_counts": {"non_us_event": 1},
        "quality_flag_counts": {},
    }
    audit_by_event = {entry["event"]: entry for entry in analysis["event_audit"]}
    assert audit_by_event["Inflation Rate YoY (Mar)"]["passes_us_scope"] is False
    assert audit_by_event["Inflation Rate YoY (Mar)"]["rejection_reasons"] == ["non_us_event"]
    assert audit_by_event["Existing Home Sales MoM (Mar)"]["passes_us_scope"] is True
    assert audit_by_event["Existing Home Sales MoM (Mar)"]["country"] == "US"
    assert analysis["score_components"][0]["canonical_event"] == "existing_home_sales_mom_(mar)"


def test_get_consensus_uses_estimate_then_forecast_aliases() -> None:
    assert get_consensus({"estimate": 2.3}) == (2.3, "estimate")
    assert get_consensus({"forecast": 235}) == (235, "forecast")