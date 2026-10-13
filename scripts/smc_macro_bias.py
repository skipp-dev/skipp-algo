"""Standalone macro-bias helpers for the v4 enrichment pipeline.

This module mirrors the macro-bias logic the broader open-prep stack uses,
but keeps the v4 runtime path free of any ``open_prep`` dependency.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any

DEFAULT_HIGH_IMPACT_EVENTS: tuple[str, ...] = (
    "cpi",
    "core cpi",
    "ppi",
    "pce",
    "core pce",
    "nonfarm payroll",
    "initial jobless claims",
    "jobless claims",
    "gdp growth",
    "gross domestic product",
    "philadelphia fed business outlook survey",
)

_CONSENSUS_FIELDS: tuple[str, ...] = (
    "consensus",
    "estimate",
    "forecast",
    "expected",
    "median",
)

_US_COUNTRY_ALIASES: set[str] = {
    "US",
    "USA",
    "U S",
    "UNITED STATES",
    "UNITED STATES OF AMERICA",
}


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_event_name(event_name: str) -> str:
    return " ".join(str(event_name or "").strip().lower().replace("_", " ").split())


def _normalize_scope_text(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    return " ".join(text.replace(".", " ").replace("-", " ").split())


def _normalize_country_code(event: dict[str, Any]) -> str:
    raw_country = next(
        (
            event.get(field_name)
            for field_name in ("country", "countryCode", "country_code")
            if event.get(field_name) not in (None, "")
        ),
        "",
    )
    normalized = _normalize_scope_text(raw_country)
    if normalized in _US_COUNTRY_ALIASES:
        return "US"
    return normalized


def _normalize_currency_code(event: dict[str, Any]) -> str:
    raw_currency = next(
        (
            event.get(field_name)
            for field_name in ("currency", "currencyCode", "currency_code")
            if event.get(field_name) not in (None, "")
        ),
        "",
    )
    return _normalize_scope_text(raw_currency)


def _resolve_us_scope(event: dict[str, Any]) -> tuple[str, str, bool]:
    country = _normalize_country_code(event)
    currency = _normalize_currency_code(event)
    if country == "US":
        return "US", currency, True
    if not country and currency == "USD":
        return "US", "USD", True
    return country, currency, False


def _normalize_event_date_key(raw_date: Any, fallback_index: int) -> str:
    if raw_date in (None, ""):
        return f"__missing_date__{fallback_index}"
    text = str(raw_date).strip()
    if not text:
        return f"__missing_date__{fallback_index}"
    date_part = text.split("T", 1)[0].split(" ", 1)[0]
    if len(date_part) == 10 and date_part[4:5] == "-" and date_part[7:8] == "-":
        return date_part
    parts = date_part.split("/")
    if len(parts) == 3:
        try:
            month = int(parts[0])
            day = int(parts[1])
            year = int(parts[2])
            if year < 100:
                year += 2000
            return date(year, month, day).isoformat()
        except ValueError:
            return date_part
    return date_part


def _event_impact_rank(event: dict[str, Any]) -> int:
    impact = str(event.get("impact") or event.get("importance") or event.get("priority") or "").strip().lower()
    if impact == "high":
        return 2
    if impact in {"medium", "mid", "moderate"}:
        return 1
    return 0


def _canonical_event_name(event_name: str) -> str:
    normalized = _normalize_event_name(event_name)
    if "gdpnow" in normalized:
        return "gdpnow"
    if (
        "gross domestic product" in normalized
        or "gdp growth rate" in normalized
        or normalized.startswith("gdp ")
        or normalized == "gdp"
    ):
        return "gdp_qoq"
    if "s&p global" in normalized and "pmi" in normalized:
        return "pmi_sp_global"
    if "core pce" in normalized:
        if "yoy" in normalized:
            return "core_pce_yoy"
        if "mom" in normalized:
            return "core_pce_mom"
        return "core_pce"
    if "pce" in normalized:
        if "yoy" in normalized:
            return "pce_yoy"
        if "mom" in normalized:
            return "pce_mom"
        return "pce"
    if "core cpi" in normalized:
        if "yoy" in normalized:
            return "core_cpi_yoy"
        if "mom" in normalized:
            return "core_cpi_mom"
        return "core_cpi"
    if "cpi" in normalized:
        if "yoy" in normalized:
            return "cpi_yoy"
        if "mom" in normalized:
            return "cpi_mom"
        return "cpi"
    if "core ppi" in normalized:
        if "yoy" in normalized:
            return "core_ppi_yoy"
        if "mom" in normalized:
            return "core_ppi_mom"
        return "core_ppi"
    if "ppi" in normalized:
        if "yoy" in normalized:
            return "ppi_yoy"
        if "mom" in normalized:
            return "ppi_mom"
        return "ppi"
    if "nonfarm payroll" in normalized:
        return "nonfarm_payrolls"
    if "jobless claims" in normalized:
        return "jobless_claims"
    if "ism services" in normalized or "ism non-manufacturing" in normalized:
        return "ism_services"
    if "ism manufacturing" in normalized:
        return "ism_manufacturing"
    if "consumer sentiment" in normalized:
        return "consumer_sentiment"
    if "philadelphia fed" in normalized:
        return "philadelphia_fed"
    return normalized.replace(" ", "_")


def canonicalize_event_name(event_name: str) -> str:
    return _canonical_event_name(event_name)


def get_consensus(event: dict[str, Any]) -> tuple[Any | None, str | None]:
    for field_name in _CONSENSUS_FIELDS:
        if event.get(field_name) not in (None, ""):
            return event.get(field_name), field_name
    return None, None


def _is_high_impact_event_name(
    event_name: str,
    high_impact_events: tuple[str, ...] = DEFAULT_HIGH_IMPACT_EVENTS,
) -> bool:
    normalized = _normalize_event_name(event_name)
    if "gdpnow" in normalized:
        return False
    return any(token in normalized for token in high_impact_events)


def filter_us_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for event in events:
        country, currency, passes_us_scope = _resolve_us_scope(event)
        if passes_us_scope:
            cloned = dict(event)
            cloned["country"] = country
            if currency:
                cloned["currency"] = currency
            filtered.append(cloned)
    return filtered


def _prepare_event_clone(event: dict[str, Any], audit_index: int) -> dict[str, Any]:
    cloned = dict(event)
    country, currency, _passes_us_scope = _resolve_us_scope(cloned)
    if country:
        cloned["country"] = country
    if currency:
        cloned["currency"] = currency
    cloned["_audit_index"] = audit_index
    cloned["canonical_event"] = _canonical_event_name(str(cloned.get("event") or cloned.get("name") or ""))
    return cloned


def _coerce_audit_index(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dedupe_events_internal(events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[tuple[str, str], list[dict[str, Any]]]]:
    kept: dict[tuple[str, str], dict[str, Any]] = {}
    dropped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    order: list[tuple[str, str]] = []

    for index, event in enumerate(events):
        audit_index = _coerce_audit_index(event.get("_audit_index"))
        cloned = _prepare_event_clone(event, audit_index if audit_index is not None else index)
        key_date = _normalize_event_date_key(cloned.get("date"), index)
        key = (key_date, str(cloned["canonical_event"]))
        if key not in kept:
            kept[key] = cloned
            dropped[key] = []
            order.append(key)
            continue

        existing = kept[key]
        existing_score = (_event_impact_rank(existing), existing.get("actual") is not None)
        new_score = (_event_impact_rank(cloned), cloned.get("actual") is not None)
        if new_score > existing_score:
            dropped[key].append(existing)
            kept[key] = cloned
        else:
            dropped[key].append(cloned)

    result: list[dict[str, Any]] = []
    dropped_details: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for key in order:
        event = dict(kept[key])
        chosen_event = event.get("event") or event.get("name")
        event["dedup"] = {
            "was_deduped": bool(dropped[key]),
            "duplicates_count": 1 + len(dropped[key]),
            "dropped_count": len(dropped[key]),
            "chosen_event": chosen_event,
        }
        result.append(event)
        dropped_details[key] = [dict(item) for item in dropped[key]]
    return result, dropped_details


def dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result, _ = _dedupe_events_internal(events)
    for event in result:
        event.pop("_audit_index", None)
    return result


def _macro_event_base_audit(event: dict[str, Any], audit_index: int) -> dict[str, Any]:
    country, currency, passes_us_scope = _resolve_us_scope(event)
    return {
        "raw_index": audit_index,
        "event": str(event.get("event") or event.get("name") or "").strip(),
        "canonical_event": _canonical_event_name(str(event.get("event") or event.get("name") or "")),
        "date": str(event.get("date") or "").strip(),
        "country": country,
        "currency": currency,
        "impact": str(event.get("impact") or event.get("importance") or event.get("priority") or "").strip(),
        "passes_us_scope": passes_us_scope,
        "passes_dedupe": False,
        "used_for_scoring": False,
        "contributed_to_bias": False,
        "weight": 0.0,
        "consensus_field": None,
        "quality_flags": [],
        "rejection_reasons": [] if passes_us_scope else ["non_us_event"],
    }


def _summarize_macro_event_audit(event_audit: list[dict[str, Any]]) -> dict[str, Any]:
    rejection_reason_counts = Counter(
        reason
        for event in event_audit
        for reason in list(event.get("rejection_reasons") or [])
    )
    quality_flag_counts = Counter(
        flag
        for event in event_audit
        for flag in list(event.get("quality_flags") or [])
    )
    return {
        "raw_event_count": len(event_audit),
        "us_scoped_event_count": sum(1 for event in event_audit if event.get("passes_us_scope")),
        "deduped_event_count": sum(1 for event in event_audit if event.get("passes_dedupe")),
        "scored_event_count": sum(1 for event in event_audit if event.get("used_for_scoring")),
        "contributing_event_count": sum(1 for event in event_audit if event.get("contributed_to_bias")),
        "rejection_reason_counts": dict(rejection_reason_counts),
        "quality_flag_counts": dict(quality_flag_counts),
    }


def _macro_orientation(canonical_event: str) -> float:
    if canonical_event.startswith(("cpi", "core_cpi", "ppi", "core_ppi", "pce", "core_pce", "jobless_claims")):
        return -1.0
    return 1.0


def _macro_weight(
    event: dict[str, Any],
    *,
    allow_mid_impact: bool,
    include_headline_pce_confirm: bool,
) -> float:
    impact_rank = _event_impact_rank(event)
    canonical_event = str(event.get("canonical_event") or _canonical_event_name(str(event.get("event") or event.get("name") or "")))
    if canonical_event in {"pce_mom", "pce_yoy"}:
        return 0.25 if include_headline_pce_confirm else 0.0
    if canonical_event == "gdp_qoq":
        return 0.5
    if canonical_event in {
        "pce_yoy",
        "core_pce_yoy",
        "cpi_yoy",
        "core_cpi_yoy",
        "ppi_yoy",
        "core_ppi_yoy",
        "pmi_sp_global",
    }:
        return 0.25
    if canonical_event in {"consumer_sentiment", "ism_services", "ism_manufacturing", "philadelphia_fed"}:
        return 0.25 if allow_mid_impact or impact_rank == 2 else 0.0
    if impact_rank == 2:
        return 1.0
    if impact_rank == 1:
        return 0.25 if allow_mid_impact else 0.0
    if canonical_event in {"consumer_sentiment", "ism_services", "ism_manufacturing", "philadelphia_fed"}:
        return 0.25 if allow_mid_impact else 0.0
    return 1.0 if _is_high_impact_event_name(str(event.get("event") or event.get("name") or "")) else 0.0


def macro_bias_with_components(
    events: list[dict[str, Any]],
    *,
    include_mid_if_no_high: bool = True,
    include_headline_pce_confirm: bool = True,
) -> dict[str, Any]:
    event_audit = [_macro_event_base_audit(event, audit_index) for audit_index, event in enumerate(events)]
    filtered_events = [
        _prepare_event_clone(event, int(audit["raw_index"]))
        for event, audit in zip(events, event_audit, strict=False)
        if audit["passes_us_scope"]
    ]
    events_for_bias, dropped_duplicates = _dedupe_events_internal(filtered_events)
    dropped_audit_indices = {
        audit_index
        for items in dropped_duplicates.values()
        for item in items
        for audit_index in [_coerce_audit_index(item.get("_audit_index"))]
        if audit_index is not None
    }
    for audit_index in dropped_audit_indices:
        event_audit[audit_index]["rejection_reasons"].append("deduped_duplicate")

    has_high_impact = any(
        _event_impact_rank(event) == 2 or _is_high_impact_event_name(str(event.get("event") or event.get("name") or ""))
        for event in events_for_bias
    )

    annotated_events: list[dict[str, Any]] = []
    score_components: list[dict[str, Any]] = []
    total = 0.0

    for event in events_for_bias:
        event_audit_index = _coerce_audit_index(event.get("_audit_index"))
        canonical_event = str(event.get("canonical_event") or _canonical_event_name(str(event.get("event") or event.get("name") or "")))
        actual = _to_float(event.get("actual"))
        consensus_value, consensus_field = get_consensus(event)
        consensus = _to_float(consensus_value)
        quality_flags: list[str] = []
        if actual is None:
            quality_flags.append("missing_actual")
        if consensus is None:
            quality_flags.append("missing_consensus")
        if not event.get("unit"):
            quality_flags.append("missing_unit")

        annotated_event = dict(event)
        annotated_event["canonical_event"] = canonical_event
        annotated_event["data_quality_flags"] = list(quality_flags)
        annotated_event["dedup"] = event.get("dedup") or {
            "was_deduped": False,
            "duplicates_count": 1,
            "dropped_count": 0,
            "chosen_event": event.get("event") or event.get("name"),
        }
        annotated_events.append(annotated_event)

        weight = _macro_weight(
            annotated_event,
            allow_mid_impact=include_mid_if_no_high and not has_high_impact,
            include_headline_pce_confirm=include_headline_pce_confirm,
        )

        if event_audit_index is not None and event_audit_index >= 0:
            audit_entry = event_audit[event_audit_index]
            audit_entry["passes_dedupe"] = True
            audit_entry["used_for_scoring"] = True
            audit_entry["weight"] = float(weight)
            audit_entry["consensus_field"] = consensus_field
            audit_entry["quality_flags"] = list(quality_flags)
            if weight <= 0.0:
                audit_entry["rejection_reasons"].append("zero_weight")
            if weight > 0.0 and actual is None:
                audit_entry["rejection_reasons"].append("missing_actual")
            if weight > 0.0 and consensus is None:
                audit_entry["rejection_reasons"].append("missing_consensus")

        surprise = 0.0
        contribution = 0.0
        if weight > 0.0 and actual is not None and consensus is not None:
            surprise = (actual - consensus) / max(abs(consensus), 1.0)
            if actual > consensus:
                contribution = _macro_orientation(canonical_event) * weight
            elif actual < consensus:
                contribution = -_macro_orientation(canonical_event) * weight
            total += contribution
        if event_audit_index is not None and event_audit_index >= 0 and contribution != 0.0:
            event_audit[event_audit_index]["contributed_to_bias"] = True

        score_components.append(
            {
                "canonical_event": canonical_event,
                "consensus_value": consensus,
                "consensus_field": consensus_field,
                "surprise": surprise,
                "weight": weight,
                "contribution": contribution,
                "data_quality_flags": list(quality_flags),
                "dedup": dict(annotated_event["dedup"]),
            }
        )

        annotated_event.pop("_audit_index", None)
        event.clear()
        event.update(annotated_event)

    return {
        "macro_bias": max(min(total / 2.0, 1.0), -1.0),
        "events_for_bias": annotated_events,
        "score_components": score_components,
        "event_audit": event_audit,
        "input_diagnostics": _summarize_macro_event_audit(event_audit),
    }


def macro_bias_score(
    events: list[dict[str, Any]],
    *,
    include_mid_if_no_high: bool = True,
    include_headline_pce_confirm: bool = True,
) -> float:
    return float(
        macro_bias_with_components(
            events,
            include_mid_if_no_high=include_mid_if_no_high,
            include_headline_pce_confirm=include_headline_pce_confirm,
        ).get("macro_bias", 0.0)
    )


__all__ = [
    "canonicalize_event_name",
    "get_consensus",
    "macro_bias_score",
    "macro_bias_with_components",
]
