from __future__ import annotations

import re
import ssl
import urllib.error
from typing import Any
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import certifi

BEA_PCE_INDEX_URL = "https://www.bea.gov/data/personal-consumption-expenditures-price-index"

PCE_AUDIT_CANONICAL_EVENTS: set[str] = {
    "core_pce_mom",
    "pce_mom",
    "core_pce_yoy",
    "pce_yoy",
}

PCE_AUDIT_TRIGGER_FLAGS: set[str] = {
    "duplicate_event",
    "missing_consensus",
    "missing_unit",
}


def _collect_audit_triggers(events: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    canonical_hits: set[str] = set()
    quality_flags: set[str] = set()

    for event in events:
        canonical = str(event.get("canonical_event") or "").strip()
        if canonical in PCE_AUDIT_CANONICAL_EVENTS:
            canonical_hits.add(canonical)

        for flag in event.get("data_quality_flags") or []:
            if str(flag).strip():
                quality_flags.add(str(flag).strip())

        dedup_info = event.get("dedup")
        if isinstance(dedup_info, dict) and bool(dedup_info.get("was_deduped")):
            quality_flags.add("duplicate_event")

    return canonical_hits, quality_flags


def should_audit_pce_release(events: list[dict[str, Any]]) -> tuple[bool, dict[str, list[str]]]:
    canonical_hits, quality_flags = _collect_audit_triggers(events)
    relevant_flags = quality_flags.intersection(PCE_AUDIT_TRIGGER_FLAGS)
    should_audit = bool(canonical_hits or relevant_flags)
    return should_audit, {
        "canonical_events": sorted(canonical_hits),
        "data_quality_flags": sorted(relevant_flags),
    }


def extract_current_release_url(html: str) -> str | None:
    """Extract the BEA 'Current Release' URL from the PCE index page HTML."""
    # Prefer explicit “Current Release” anchor neighborhood.
    match = re.search(
        r'href="(?P<href>/news/\d{4}/personal-income-and-outlays[^"#?]+)"[^>]*>\s*Current\s+Release\s*<',
        html,
        flags=re.IGNORECASE,
    )
    if match:
        return urljoin(BEA_PCE_INDEX_URL, match.group("href"))

    # Fallback: first matching personal-income-and-outlays news link.
    fallback = re.search(
        r'href="(?P<href>/news/\d{4}/personal-income-and-outlays[^"#?]+)"',
        html,
        flags=re.IGNORECASE,
    )
    if fallback:
        return urljoin(BEA_PCE_INDEX_URL, fallback.group("href"))
    return None


def resolve_current_pio_release_url(timeout_seconds: int = 12) -> tuple[str | None, str | None]:
    """Resolve the current BEA Personal Income and Outlays release URL.

    Returns (url, error). Errors are non-fatal by design to keep this layer fail-open.
    """
    request = Request(
        BEA_PCE_INDEX_URL,
        headers={
            "Accept": "text/html",
            "User-Agent": "skipp-algo-open-prep/1.0 (+bea-audit)",
        },
    )
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    try:
        with urlopen(request, timeout=timeout_seconds, context=ssl_ctx) as response:
            html = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return None, f"bea_http_{exc.code}"
    except urllib.error.URLError as exc:
        return None, f"bea_network_error:{exc.reason}"
    except Exception as exc:  # pragma: no cover - defensive fallback
        return None, f"bea_unexpected_error:{exc}"

    url = extract_current_release_url(html)
    if not url:
        return None, "bea_release_url_not_found"
    return url, None


def build_bea_audit_payload(
    events: list[dict[str, Any]],
    enabled: bool = True,
) -> dict[str, Any]:
    """Build BEA audit metadata for open-prep outputs.

    This is intentionally telemetry-oriented and fail-open:
      - never raises;
      - exposes trigger reason(s);
      - includes release URL when discoverable.
    """
    if not enabled:
        return {
            "enabled": False,
            "status": "disabled",
            "release_url": None,
            "trigger": {"canonical_events": [], "data_quality_flags": []},
            "error": None,
        }

    should_audit, trigger = should_audit_pce_release(events)
    if not should_audit:
        return {
            "enabled": True,
            "status": "not_required",
            "release_url": None,
            "trigger": trigger,
            "error": None,
        }

    release_url, error = resolve_current_pio_release_url()
    return {
        "enabled": True,
        "status": "ok" if release_url else "fail_open",
        "release_url": release_url,
        "trigger": trigger,
        "error": error,
    }
