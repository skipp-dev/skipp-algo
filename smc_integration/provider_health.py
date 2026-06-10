from __future__ import annotations

import enum
import contextlib
import json
import os
import time
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .provider_matrix import discover_provider_matrix
from .repo_sources import (
    discover_composite_source_plan,
    discover_structure_source_status,
    load_raw_meta_input_composite,
    load_raw_structure_input,
)
from .service import build_snapshot_bundle_for_symbol_timeframe
from .sources import structure_artifact_json

CANONICAL_STRUCTURE_KEYS = ("bos", "orderblocks", "fvg", "liquidity_sweeps")
_ALL_VISIBILITY_DOMAINS = ("structure", "volume", "technical", "news")
_FATAL_ARTIFACT_HEALTH_CODES = {
    "INVALID_MANIFEST_JSON",
    "INVALID_MANIFEST_SHAPE",
    "INVALID_STRUCTURE_ARTIFACT",
    "INVALID_LEGACY_STRUCTURE_ARTIFACT",
}
_STRICT_RELEASE_WARNING_CODES = {
    "ARTIFACT_LOOKUP_FAILED",
    "DOMAIN_DROP_DURING_BUILD",
    "MISSING_ARTIFACT",
    "MISSING_MANIFEST",
    "MISSING_MANIFEST_GENERATED_AT",
    "INVALID_MANIFEST_JSON",
    "INVALID_MANIFEST_SHAPE",
    "INVALID_STRUCTURE_ARTIFACT",
    "INVALID_LEGACY_STRUCTURE_ARTIFACT",
    "MISSING_META_ASOF_TS",
}

_STRICT_RELEASE_DEGRADATION_CODES = {
    # EMPTY_CONTEXT_BARS removed: on GitHub-hosted runners without a local
    # Databento cache, context bars are always 0.  The library generator
    # already handles this with fallback data; promoting it to a hard failure
    # here creates an unresolvable CI blocker.
    "STALE_MANIFEST_GENERATED_AT",
    "STALE_MANIFEST_FILE_MTIME",
    "STALE_META_ASOF_TS",
    "STALE_META_TECHNICAL_DOMAIN",
    "STALE_META_NEWS_DOMAIN",
    "STALE_META_VOLUME_DOMAIN",
}


def _write_text_atomic(path: Path, content: str) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


# ── Provider Failure Semantics (F-04) ────────────────────────────


class FailureAction(enum.Enum):
    """Machine-readable reaction to a provider failure.

    FALLBACK    — switch to next provider in chain; no user-visible degradation.
    ADVISORY    — log + surface warning; do NOT suppress entry signals.
    SUPPRESS    — suppress new entry signals while the failure persists.
    HARD_DEGRADE — mark trust tier as degraded; block operational release.
    """

    FALLBACK = "fallback"
    ADVISORY = "advisory"
    SUPPRESS = "suppress"
    HARD_DEGRADE = "hard_degrade"


@dataclass(frozen=True)
class FailureSemantics:
    """Structured description of how a domain failure should be handled."""

    domain: str
    failure_type: str
    action: FailureAction
    max_tolerable_hours: float | None
    affects_entry: bool
    description: str


# ── Failure Semantics Matrix ─────────────────────────────────────
# One entry per (domain, failure_type) pair.  Ordered by severity.
_FAILURE_SEMANTICS_MATRIX: tuple[FailureSemantics, ...] = (
    # --- structure ---
    FailureSemantics("structure", "missing",     FailureAction.HARD_DEGRADE, None, True,  "No structure source available — cannot build snapshot."),
    FailureSemantics("structure", "stale",       FailureAction.SUPPRESS,     24,   True,  "Structure artifact older than 24 h — entry signals unreliable."),
    FailureSemantics("structure", "invalid",     FailureAction.HARD_DEGRADE, None, True,  "Structure artifact malformed — snapshot build blocked."),
    # --- volume ---
    FailureSemantics("volume",    "missing",     FailureAction.ADVISORY,     None, False, "Volume domain absent — quality scoring incomplete."),
    FailureSemantics("volume",    "stale",       FailureAction.ADVISORY,     48,   False, "Volume data stale — regime classification may drift."),
    FailureSemantics("volume",    "fallback",    FailureAction.FALLBACK,     None, False, "Volume domain from fallback provider (e.g. Benzinga)."),
    # --- technical ---
    FailureSemantics("technical", "missing",     FailureAction.FALLBACK,     None, False, "Technical domain absent — optional enrichment dropped."),
    FailureSemantics("technical", "stale",       FailureAction.ADVISORY,     48,   False, "Technical data stale — enrichment may be outdated."),
    FailureSemantics("technical", "fallback",    FailureAction.FALLBACK,     None, False, "Technical domain from fallback provider."),
    # --- news ---
    FailureSemantics("news",      "missing",     FailureAction.FALLBACK,     None, False, "News domain absent — fallback to Benzinga or skip."),
    FailureSemantics("news",      "stale",       FailureAction.ADVISORY,     24,   False, "News data stale — sentiment scores may not reflect current events."),
    FailureSemantics("news",      "fallback",    FailureAction.FALLBACK,     None, False, "News domain from Benzinga fallback — reduced depth vs. live NewsAPI."),
)

_FAILURE_SEMANTICS_INDEX: dict[tuple[str, str], FailureSemantics] = {
    (fs.domain, fs.failure_type): fs for fs in _FAILURE_SEMANTICS_MATRIX
}


def resolve_failure_action(domain: str, failure_type: str) -> FailureSemantics:
    """Look up the canonical failure semantics for a (domain, failure_type) pair.

    Returns a default ADVISORY entry for unknown combinations so callers
    never need to handle missing keys.
    """
    key = (domain.lower().strip(), failure_type.lower().strip())
    entry = _FAILURE_SEMANTICS_INDEX.get(key)
    if entry is not None:
        return entry
    return FailureSemantics(
        domain=key[0],
        failure_type=key[1],
        action=FailureAction.ADVISORY,
        max_tolerable_hours=None,
        affects_entry=False,
        description=f"Unknown failure ({key[0]}/{key[1]}) — treated as advisory.",
    )


def classify_domain_alerts_to_failure_actions(
    domain_alerts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Translate raw domain_alerts into structured failure-action records.

    Each returned dict contains the original alert fields plus:
      failure_action, failure_affects_entry, failure_max_tolerable_hours
    """
    enriched: list[dict[str, Any]] = []
    for alert in domain_alerts:
        domain = str(alert.get("domain", "")).strip().lower()
        code = str(alert.get("code", "")).strip().upper()
        # Map alert codes to failure_type
        if "STALE" in code:
            failure_type = "stale"
        elif "MISSING" in code or "DROPPED" in code or "SILENT_DOMAIN_DROP" in code:
            failure_type = "missing"
        elif "FALLBACK" in code:
            failure_type = "fallback"
        elif "INVALID" in code:
            failure_type = "invalid"
        else:
            failure_type = "unknown"
        sem = resolve_failure_action(domain, failure_type)
        record = dict(alert)
        record["failure_action"] = sem.action.value
        record["failure_affects_entry"] = sem.affects_entry
        record["failure_max_tolerable_hours"] = sem.max_tolerable_hours
        enriched.append(record)
    return enriched


def worst_failure_action(enriched_alerts: list[dict[str, Any]]) -> FailureAction:
    """Return the most severe FailureAction across enriched alerts."""
    severity_order = [FailureAction.FALLBACK, FailureAction.ADVISORY, FailureAction.SUPPRESS, FailureAction.HARD_DEGRADE]
    worst = FailureAction.FALLBACK
    for alert in enriched_alerts:
        action_str = str(alert.get("failure_action", "")).strip()
        try:
            action = FailureAction(action_str)
        except ValueError:
            continue
        if severity_order.index(action) > severity_order.index(worst):
            worst = action
    return worst


def _now_ts() -> float:
    return float(time.time())


def _iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), tz=UTC).isoformat()


def _status_from_lists(*, failures: list[dict[str, Any]], warnings: list[dict[str, Any]], degradations: list[dict[str, Any]]) -> str:
    if failures:
        return "fail"
    if warnings or degradations:
        return "warn"
    return "ok"


def _build_domain_alert(
    *,
    code: str,
    severity: str,
    symbol: str,
    timeframe: str,
    domain: str,
    status: str,
    planned_source: str,
    actual_source: str,
    fallback_used: bool,
    age_hours: float | None,
    message: str,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "code": code,
        "severity": severity,
        "symbol": symbol,
        "timeframe": timeframe,
        "domain": domain,
        "status": status,
        "planned_source": planned_source,
        "actual_source": actual_source,
        "fallback_used": bool(fallback_used),
        "message": message,
    }
    if age_hours is not None:
        row["age_hours"] = age_hours
    return row


def _source_plan_value(source_plan: dict[str, Any] | None, domain: str) -> str:
    if not isinstance(source_plan, dict):
        return ""
    for key in (domain, f"snapshot_{domain}"):
        value = str(source_plan.get(key) or "").strip()
        if value:
            return value
    return ""


def _missing_meta_domains(raw_meta: dict[str, Any] | None) -> set[str]:
    if not isinstance(raw_meta, dict):
        return set()
    raw_missing = raw_meta.get("meta_domains_missing")
    if not isinstance(raw_missing, list):
        return set()
    return {
        str(item).strip()
        for item in raw_missing
        if isinstance(item, str) and str(item).strip()
    }


def _domain_drop_reason_map(raw_meta: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(raw_meta, dict):
        return {}
    raw_reasons = raw_meta.get("domain_drop_reasons")
    if not isinstance(raw_reasons, dict):
        return {}
    return {
        str(key).strip(): str(value).strip()
        for key, value in raw_reasons.items()
        if str(key).strip() and str(value).strip()
    }


def _domain_drop_provider_map(raw_meta: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(raw_meta, dict):
        return {}
    raw_providers = raw_meta.get("domain_drop_providers")
    if not isinstance(raw_providers, dict):
        return {}
    return {
        str(key).strip(): str(value).strip()
        for key, value in raw_providers.items()
        if str(key).strip() and str(value).strip()
    }


def _present_meta_domains(raw_meta: dict[str, Any] | None) -> set[str]:
    if not isinstance(raw_meta, dict):
        return set()

    raw_present = raw_meta.get("meta_domains_present")
    present = {
        str(item).strip()
        for item in raw_present
        if isinstance(item, str) and str(item).strip()
    } if isinstance(raw_present, list) else set()

    for domain in ("volume", "technical", "news"):
        if isinstance(raw_meta.get(domain), dict):
            present.add(domain)
    return present


def _domain_visibility_snapshot(
    *,
    structure_present: bool,
    raw_meta: dict[str, Any] | None,
    domain_diag: dict[str, Any] | None,
) -> dict[str, Any]:
    present = set()
    if structure_present:
        present.add("structure")

    meta_present = _present_meta_domains(raw_meta)
    missing_meta = _missing_meta_domains(raw_meta)
    present.update(meta_present)

    if isinstance(domain_diag, dict):
        for domain in ("volume", "technical", "news"):
            if domain in present or domain in missing_meta:
                continue
            status = str(domain_diag.get(domain) or "").strip()
            if status in {"present", "synthetic_fallback"} and domain_diag.get(f"{domain}_stale") is not True:
                present.add(domain)

    missing = [domain for domain in _ALL_VISIBILITY_DOMAINS if domain not in present]
    score = len(present) / float(len(_ALL_VISIBILITY_DOMAINS))
    return {
        "domain_visibility_domains_present": sorted(present),
        "domain_visibility_domains_missing": missing,
        "domain_visibility_total_domains": len(_ALL_VISIBILITY_DOMAINS),
        "domain_visibility_score": round(score, 4),
        "domain_visibility_complete": len(missing) == 0,
    }


def _summarize_domain_visibility(results: list[dict[str, Any]]) -> dict[str, Any]:
    visibility_rows: list[dict[str, Any]] = []
    for row in results:
        score = row.get("domain_visibility_score")
        if not isinstance(score, (int, float)):
            continue
        visibility_rows.append(
            {
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "score": round(float(score), 4),
                "complete": bool(row.get("domain_visibility_complete")),
                "domains_present": list(row.get("domain_visibility_domains_present") or []),
                "domains_missing": list(row.get("domain_visibility_domains_missing") or []),
            }
        )

    if not visibility_rows:
        return {
            "average_score": None,
            "full_coverage_ratio": None,
            "fully_visible_rows": 0,
            "evaluated_rows": 0,
            "rows": [],
        }

    fully_visible_rows = sum(1 for row in visibility_rows if row["complete"])
    return {
        "average_score": round(sum(row["score"] for row in visibility_rows) / len(visibility_rows), 4),
        "full_coverage_ratio": round(fully_visible_rows / len(visibility_rows), 4),
        "fully_visible_rows": fully_visible_rows,
        "evaluated_rows": len(visibility_rows),
        "rows": visibility_rows,
    }


def _raw_volume_regime(raw_meta: dict[str, Any] | None) -> str:
    if not isinstance(raw_meta, dict):
        return ""
    volume = raw_meta.get("volume")
    if not isinstance(volume, dict):
        return ""
    value = volume.get("value")
    if not isinstance(value, dict):
        return ""
    return str(value.get("regime") or "").strip().upper()


def _collect_meta_domain_alerts(
    *,
    symbol: str,
    timeframe: str,
    source_plan: dict[str, Any] | None,
    raw_meta: dict[str, Any] | None,
    domain_diag: dict[str, Any],
    allow_release_reference_meta_fallback: bool,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    missing_domains = _missing_meta_domains(raw_meta)
    drop_reasons = _domain_drop_reason_map(raw_meta)
    drop_providers = _domain_drop_provider_map(raw_meta)

    for domain in ("volume", "technical", "news"):
        status = str(domain_diag.get(domain) or "").strip()
        planned_source = _source_plan_value(source_plan, domain)
        actual_source = str(domain_diag.get(f"{domain}_source") or "").strip()
        fallback_used = bool(domain_diag.get(f"{domain}_fallback_used"))
        domain_stale = domain_diag.get(f"{domain}_stale") is True

        age_hours_raw = domain_diag.get(f"{domain}_age_hours")
        age_hours = float(age_hours_raw) if isinstance(age_hours_raw, (int, float)) else None

        if fallback_used:
            alerts.append(
                _build_domain_alert(
                    code=f"FALLBACK_META_{domain.upper()}_DOMAIN",
                    severity="info",
                    symbol=symbol,
                    timeframe=timeframe,
                    domain=domain,
                    status=status or "present",
                    planned_source=planned_source,
                    actual_source=actual_source,
                    fallback_used=True,
                    age_hours=age_hours,
                    message=(
                        f"{domain} domain used fallback provider "
                        f"{actual_source or 'unknown'} instead of {planned_source or 'unknown'}."
                    ),
                )
            )

        if domain in {"technical", "news"} and domain in missing_domains:
            if domain_stale:
                continue
            drop_reason = drop_reasons.get(domain) or status or "missing_optional_domain"
            drop_provider = drop_providers.get(domain) or actual_source or planned_source
            severity = "warn"
            if allow_release_reference_meta_fallback:
                severity = "info"
            alerts.append(
                _build_domain_alert(
                    code=f"DOMAIN_DROPPED_{domain.upper()}",
                    severity="info",
                    symbol=symbol,
                    timeframe=timeframe,
                    domain=domain,
                    status=drop_reason,
                    planned_source=planned_source,
                    actual_source=actual_source,
                    fallback_used=fallback_used,
                    age_hours=age_hours,
                    message=(
                        f"{domain} domain absent after provider resolution; reason={drop_reason}; "
                        f"drop_provider={drop_provider or 'unknown'}."
                    ),
                )
            )
            domain_drop_alert = _build_domain_alert(
                code="DOMAIN_DROP_DURING_BUILD",
                severity=severity,
                symbol=symbol,
                timeframe=timeframe,
                domain=domain,
                status=drop_reason,
                planned_source=planned_source,
                actual_source=actual_source,
                fallback_used=fallback_used,
                age_hours=age_hours,
                message=(
                    f"{domain} domain dropped during build; reason={drop_reason}; "
                    f"drop_provider={drop_provider or 'unknown'}; "
                    f"planned_source={planned_source or 'unknown'}."
                ),
            )
            domain_drop_alert["drop_provider"] = drop_provider
            alerts.append(domain_drop_alert)
            alerts.append(
                _build_domain_alert(
                    code=f"SILENT_DOMAIN_DROP_{domain.upper()}",
                    severity=severity,
                    symbol=symbol,
                    timeframe=timeframe,
                    domain=domain,
                    status=drop_reason,
                    planned_source=planned_source,
                    actual_source=actual_source,
                    fallback_used=fallback_used,
                    age_hours=age_hours,
                    message=(
                        f"{domain} domain dropped before merge; reason={drop_reason}; "
                        f"planned_source={planned_source or 'unknown'}; "
                        f"actual_source={actual_source or 'unknown'}."
                    ),
                )
            )
            continue

        if not status or status in {"present", "synthetic_fallback"}:
            continue

        severity = "warn"
        if allow_release_reference_meta_fallback and domain in {"technical", "news"}:
            severity = "info"

        alerts.append(
            _build_domain_alert(
                code=f"META_{domain.upper()}_DOMAIN_STATUS",
                severity=severity,
                symbol=symbol,
                timeframe=timeframe,
                domain=domain,
                status=status,
                planned_source=planned_source,
                actual_source=actual_source,
                fallback_used=fallback_used,
                age_hours=age_hours,
                message=(
                    f"{domain} domain status={status}; planned_source={planned_source or 'unknown'}; "
                    f"actual_source={actual_source or 'unknown'}."
                ),
            )
        )

    return alerts


def _normalize_symbols(symbols: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in symbols or ["IBG"]:
        symbol = str(raw).strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return out or ["IBG"]


def _normalize_timeframes(timeframes: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in timeframes or ["15m"]:
        timeframe = str(raw).strip()
        if not timeframe or timeframe in seen:
            continue
        seen.add(timeframe)
        out.append(timeframe)
    return out or ["15m"]


def _shape_ok(raw_structure: Any) -> bool:
    if not isinstance(raw_structure, dict):
        return False
    return set(raw_structure.keys()) == set(CANONICAL_STRUCTURE_KEYS)


def _structure_is_empty(raw_structure: dict[str, Any]) -> bool:
    for key in CANONICAL_STRUCTURE_KEYS:
        value = raw_structure.get(key, [])
        if isinstance(value, list) and value:
            return False
    return True


def _provider_domain_results() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in discover_provider_matrix():
        status = "ok"
        if not entry.potential.can_supply_symbols:
            status = "warn"
        rows.append(
            {
                "provider": entry.name,
                "status": status,
                "path_hint": entry.path_hint,
                "structure_mode": entry.current.snapshot_structure_mode,
                "meta_mode": entry.current.snapshot_meta_mode,
                "maps_structure": bool(entry.current.currently_maps_structure),
                "maps_meta": bool(entry.current.currently_maps_meta),
                "maps_technical": bool(entry.current.currently_maps_technical),
                "maps_news": bool(entry.current.currently_maps_news),
                "known_gaps": list(entry.known_gaps),
            }
        )
    rows.sort(key=lambda item: str(item["provider"]))
    return rows


def _collect_artifact_health(
    *,
    symbols: list[str],
    timeframes: list[str],
    checked_at: float,
    stale_after_seconds: int | None,
) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    degradations: list[dict[str, Any]] = []
    missing_artifacts: list[dict[str, Any]] = []
    stale_artifacts: list[dict[str, Any]] = []

    summary = structure_artifact_json.discover_normalized_contract_summary(repo_state_only=True)
    raw_health = summary.get("health", {}) if isinstance(summary, dict) else {}
    health_issues = raw_health.get("issues", []) if isinstance(raw_health, dict) else []
    health_issue_rows = [item for item in health_issues if isinstance(item, dict)]

    for issue in health_issue_rows:
        code = str(issue.get("code", "UNKNOWN_HEALTH_ISSUE"))
        record = {
            "code": code,
            "message": str(issue.get("message", "")),
            "path": issue.get("path"),
        }
        if code in _FATAL_ARTIFACT_HEALTH_CODES:
            failures.append(record)
        else:
            warnings.append(record)

    for symbol in symbols:
        for timeframe in timeframes:
            try:
                has_artifact = structure_artifact_json.has_artifact_for_symbol_timeframe(symbol, timeframe)
            except Exception as exc:
                failures.append(
                    {
                        "code": "ARTIFACT_LOOKUP_FAILED",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": str(exc),
                    }
                )
                continue

            if not has_artifact:
                row = {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "code": "MISSING_ARTIFACT",
                }
                missing_artifacts.append(row)
                warnings.append(
                    {
                        "code": "MISSING_ARTIFACT",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": "No structure artifact could be resolved for symbol/timeframe.",
                    }
                )

    manifest_rows: list[dict[str, Any]] = []
    for timeframe in timeframes:
        manifest_path = structure_artifact_json.STRUCTURE_ARTIFACTS_DIR / f"manifest_{timeframe}.json"
        manifest_info: dict[str, Any] = {
            "timeframe": timeframe,
            "manifest_path": str(manifest_path.as_posix()),
            "exists": manifest_path.exists(),
        }

        if not manifest_path.exists():
            warnings.append(
                {
                    "code": "MISSING_MANIFEST",
                    "timeframe": timeframe,
                    "message": f"Manifest does not exist: {manifest_path.as_posix()}",
                }
            )
            manifest_rows.append(manifest_info)
            continue

        stat = manifest_path.stat()
        mtime_age = max(0.0, float(checked_at) - float(stat.st_mtime))
        manifest_info["mtime_age_seconds"] = mtime_age

        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            failures.append(
                {
                    "code": "INVALID_MANIFEST_JSON",
                    "timeframe": timeframe,
                    "manifest_path": str(manifest_path.as_posix()),
                    "message": str(exc),
                }
            )
            manifest_rows.append(manifest_info)
            continue

        generated_at = payload.get("generated_at") if isinstance(payload, dict) else None
        if isinstance(generated_at, (int, float)):
            generated_age = max(0.0, float(checked_at) - float(generated_at))
            manifest_info["generated_at"] = float(generated_at)
            manifest_info["generated_age_seconds"] = generated_age
            if stale_after_seconds is not None and generated_age > float(stale_after_seconds):
                stale_generated_row: dict[str, Any] = {
                    "timeframe": timeframe,
                    "manifest_path": str(manifest_path.as_posix()),
                    "generated_age_seconds": generated_age,
                    "stale_after_seconds": int(stale_after_seconds),
                    "code": "STALE_MANIFEST_GENERATED_AT",
                }
                stale_artifacts.append(stale_generated_row)
                degradations.append(dict(stale_generated_row))
        else:
            warnings.append(
                {
                    "code": "MISSING_MANIFEST_GENERATED_AT",
                    "timeframe": timeframe,
                    "manifest_path": str(manifest_path.as_posix()),
                    "message": "Manifest has no numeric generated_at field.",
                }
            )

        if stale_after_seconds is not None and mtime_age > float(stale_after_seconds):
            stale_mtime_row: dict[str, Any] = {
                "timeframe": timeframe,
                "manifest_path": str(manifest_path.as_posix()),
                "mtime_age_seconds": mtime_age,
                "stale_after_seconds": int(stale_after_seconds),
                "code": "STALE_MANIFEST_FILE_MTIME",
            }
            stale_artifacts.append(stale_mtime_row)
            degradations.append(dict(stale_mtime_row))

        manifest_rows.append(manifest_info)

    if stale_after_seconds is None:
        warnings.append(
            {
                "code": "STALE_THRESHOLD_UNSET",
                "message": "No staleness threshold configured; timestamps are inspected but not hard-gated by age.",
            }
        )

    status = _status_from_lists(failures=failures, warnings=warnings, degradations=degradations)
    return {
        "status": status,
        "contract_summary": {
            "mapped_structure_categories": dict(summary.get("mapped_structure_categories", {})),
            "structure_profile_supported": bool(summary.get("structure_profile_supported", False)),
            "diagnostics_available": bool(summary.get("diagnostics_available", False)),
        },
        "health_issue_count": len(health_issue_rows),
        "health_issues": health_issue_rows,
        "manifests": manifest_rows,
        "missing_artifacts": missing_artifacts,
        "stale_artifacts": stale_artifacts,
        "warnings": warnings,
        "failures": failures,
        "degradations": degradations,
    }


def _run_smoke_checks(
    *,
    symbols: list[str],
    timeframes: list[str],
    checked_at: float,
    stale_after_seconds: int | None,
    allow_release_reference_meta_fallback: bool = False,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    all_warnings: list[dict[str, Any]] = []
    all_failures: list[dict[str, Any]] = []
    all_degradations: list[dict[str, Any]] = []
    all_domain_alerts: list[dict[str, Any]] = []
    built_bundles: dict[tuple[str, str], dict[str, Any]] = {}

    for symbol in symbols:
        for timeframe in timeframes:
            warnings: list[dict[str, Any]] = []
            failures: list[dict[str, Any]] = []
            degradations: list[dict[str, Any]] = []

            row: dict[str, Any] = {
                "symbol": symbol,
                "timeframe": timeframe,
            }

            try:
                source_plan = discover_composite_source_plan(source="auto", symbol=symbol, timeframe=timeframe)
                row["source_plan"] = source_plan
            except Exception as exc:
                failures.append(
                    {
                        "code": "SOURCE_PLAN_RESOLUTION_FAILED",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": str(exc),
                    }
                )
                row["status"] = "fail"
                row["warnings"] = warnings
                row["failures"] = failures
                row["degradations"] = degradations
                results.append(row)
                all_failures.extend(failures)
                continue

            try:
                raw_structure = load_raw_structure_input(symbol, timeframe, source="auto")
            except Exception as exc:
                failures.append(
                    {
                        "code": "STRUCTURE_INPUT_LOAD_FAILED",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": str(exc),
                    }
                )
                row["status"] = "fail"
                row["warnings"] = warnings
                row["failures"] = failures
                row["degradations"] = degradations
                results.append(row)
                all_failures.extend(failures)
                continue

            row["structure_shape_ok"] = _shape_ok(raw_structure)
            if not row["structure_shape_ok"]:
                failures.append(
                    {
                        "code": "INVALID_STRUCTURE_SHAPE",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": "raw_structure is missing canonical top-level categories.",
                    }
                )
            elif _structure_is_empty(raw_structure):
                row["structure_empty"] = True
                planned_structure_source = _source_plan_value(
                    row.get("source_plan") if isinstance(row.get("source_plan"), dict) else None,
                    "structure",
                )
                if not (
                    allow_release_reference_meta_fallback
                    and planned_structure_source == "structure_artifact_json"
                ):
                    degradation = {
                        "code": "EMPTY_STRUCTURE_INPUT",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": "raw_structure contains only empty canonical category arrays.",
                    }
                    warnings.append(dict(degradation))
                    degradations.append(dict(degradation))

            structure_present = bool(row["structure_shape_ok"])

            try:
                if allow_release_reference_meta_fallback:
                    from .repo_sources import load_raw_meta_input_composite_for_release_reference

                    raw_meta = load_raw_meta_input_composite_for_release_reference(
                        symbol,
                        timeframe,
                        source="auto",
                        reference_time=checked_at,
                    )
                else:
                    raw_meta = load_raw_meta_input_composite(symbol, timeframe, source="auto")
            except Exception as exc:
                failures.append(
                    {
                        "code": "META_INPUT_LOAD_FAILED",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": str(exc),
                    }
                )
                raw_meta = None

            if isinstance(raw_meta, dict):
                asof_ts = raw_meta.get("asof_ts")
                if not isinstance(asof_ts, (int, float)):
                    warnings.append(
                        {
                            "code": "MISSING_META_ASOF_TS",
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "message": "raw_meta has no numeric asof_ts.",
                        }
                    )
                elif stale_after_seconds is not None:
                    age = max(0.0, float(checked_at) - float(asof_ts))
                    if age > float(stale_after_seconds):
                        stale_meta_degradation: dict[str, Any] = {
                            "code": "STALE_META_ASOF_TS",
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "age_seconds": age,
                            "stale_after_seconds": int(stale_after_seconds),
                        }
                        warnings.append(dict(stale_meta_degradation))
                        degradations.append(dict(stale_meta_degradation))

                if _raw_volume_regime(raw_meta) == "UNKNOWN":
                    unknown_volume_regime = {
                        "code": "UNKNOWN_VOLUME_REGIME",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": "raw_meta volume regime is UNKNOWN due to missing liquidity evidence.",
                    }
                    warnings.append(dict(unknown_volume_regime))
                    degradations.append(dict(unknown_volume_regime))

                # Per-domain staleness (volume / technical / news).
                domain_diag = raw_meta.get("meta_domain_diagnostics")
                if isinstance(domain_diag, dict):
                    row["meta_domain_diagnostics"] = domain_diag
                    domain_alerts = _collect_meta_domain_alerts(
                        symbol=symbol,
                        timeframe=timeframe,
                        source_plan=row.get("source_plan") if isinstance(row.get("source_plan"), dict) else None,
                        raw_meta=raw_meta,
                        domain_diag=domain_diag,
                        allow_release_reference_meta_fallback=allow_release_reference_meta_fallback,
                    )
                    if domain_alerts:
                        row["domain_alerts"] = domain_alerts
                        all_domain_alerts.extend(domain_alerts)
                        for alert in domain_alerts:
                            if alert.get("severity") == "warn":
                                warnings.append(
                                    {
                                        key: value
                                        for key, value in alert.items()
                                        if key != "severity"
                                    }
                                )
                    for domain in ("volume", "technical", "news"):
                        if (
                            allow_release_reference_meta_fallback
                            and domain in {"technical", "news", "volume"}
                            and domain_diag.get(domain) != "present"
                        ):
                            continue
                        if domain_diag.get(f"{domain}_stale") is True:
                            code = f"STALE_META_{domain.upper()}_DOMAIN"
                            stale_domain_row: dict[str, Any] = {
                                "code": code,
                                "symbol": symbol,
                                "timeframe": timeframe,
                                "message": f"{domain} domain meta is stale or missing.",
                            }
                            age_hours = domain_diag.get(f"{domain}_age_hours")
                            if age_hours is not None:
                                stale_domain_row["age_hours"] = age_hours
                            warnings.append(dict(stale_domain_row))
                            degradations.append(dict(stale_domain_row))

            row.update(
                _domain_visibility_snapshot(
                    structure_present=structure_present,
                    raw_meta=raw_meta if isinstance(raw_meta, dict) else None,
                    domain_diag=row.get("meta_domain_diagnostics") if isinstance(row.get("meta_domain_diagnostics"), dict) else None,
                )
            )

            if failures:
                row["status"] = "fail"
                row["warnings"] = warnings
                row["failures"] = failures
                row["degradations"] = degradations
                results.append(row)
                all_warnings.extend(warnings)
                all_failures.extend(failures)
                all_degradations.extend(degradations)
                continue

            # ── Fast-path: skip expensive bundle build when no real meta
            # domains are present.  The bundle would re-resolve all providers
            # and rebuild the snapshot from scratch (≈12 s per pair on slow
            # I/O).  When every domain is absent the result is predetermined:
            # status = warn (degradations only, no hard failures).
            _diag = row.get("meta_domain_diagnostics")
            if isinstance(_diag, dict) and all(
                _diag.get(d) not in {"present", "synthetic_fallback"}
                for d in ("volume", "technical", "news")
            ):
                row["status"] = _status_from_lists(
                    failures=failures, warnings=warnings, degradations=degradations,
                )
                row["warnings"] = warnings
                row["failures"] = failures
                row["degradations"] = degradations
                row["bundle_skipped"] = True
                row["bundle_skip_reason"] = "all_meta_domains_absent"
                results.append(row)
                all_warnings.extend(warnings)
                all_failures.extend(failures)
                all_degradations.extend(degradations)
                continue

            try:
                bundle_kwargs: dict[str, Any] = {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "source": "auto",
                    "generated_at": float(checked_at),
                }
                if allow_release_reference_meta_fallback:
                    bundle_kwargs["allow_release_reference_meta_fallback"] = True
                bundle = build_snapshot_bundle_for_symbol_timeframe(**bundle_kwargs)
                built_bundles[(symbol, timeframe)] = bundle
            except Exception as exc:
                failures.append(
                    {
                        "code": "BUNDLE_BUILD_FAILED",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": str(exc),
                    }
                )
                row["status"] = "fail"
                row["warnings"] = warnings
                row["failures"] = failures
                row["degradations"] = degradations
                results.append(row)
                all_warnings.extend(warnings)
                all_failures.extend(failures)
                all_degradations.extend(degradations)
                continue

            snapshot = bundle.get("snapshot")
            if not isinstance(snapshot, dict):
                failures.append(
                    {
                        "code": "INVALID_BUNDLE_SNAPSHOT",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": "bundle has no dict snapshot payload.",
                    }
                )
            else:
                snapshot_structure = snapshot.get("structure")
                if not isinstance(snapshot_structure, dict) or set(snapshot_structure.keys()) != set(CANONICAL_STRUCTURE_KEYS):
                    failures.append(
                        {
                            "code": "INVALID_SNAPSHOT_STRUCTURE_SHAPE",
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "message": "snapshot.structure does not expose canonical categories.",
                        }
                    )
                if "structure_context" in snapshot:
                    failures.append(
                        {
                            "code": "STRUCTURE_CONTEXT_POLLUTES_SNAPSHOT",
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "message": "structure_context must stay additive and not exist inside snapshot.",
                        }
                    )

            if not isinstance(bundle.get("dashboard_payload"), dict):
                failures.append(
                    {
                        "code": "MISSING_DASHBOARD_PAYLOAD",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": "bundle has no dashboard_payload object.",
                    }
                )
            if not isinstance(bundle.get("pine_payload"), dict):
                failures.append(
                    {
                        "code": "MISSING_PINE_PAYLOAD",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": "bundle has no pine_payload object.",
                    }
                )

            bundle_plan = bundle.get("source_plan")
            if isinstance(bundle_plan, dict):
                if bundle_plan != row.get("source_plan"):
                    degradation = {
                        "code": "SOURCE_PLAN_MISMATCH",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": "bundle.source_plan differs from pre-resolved composite plan.",
                    }
                    warnings.append(dict(degradation))
                    degradations.append(dict(degradation))
            else:
                warnings.append(
                    {
                        "code": "MISSING_BUNDLE_SOURCE_PLAN",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": "bundle has no source_plan object.",
                    }
                )

            if "structure_context" in bundle and not isinstance(bundle.get("structure_context"), dict):
                warnings.append(
                    {
                        "code": "INVALID_STRUCTURE_CONTEXT_SHAPE",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": "bundle structure_context exists but is not an object.",
                    }
                )

            context_diagnostics = bundle.get("context_diagnostics")
            if isinstance(context_diagnostics, dict):
                row["context_diagnostics"] = context_diagnostics
                if context_diagnostics.get("bars_available") is False:
                    degradation = {
                        "code": "EMPTY_CONTEXT_BARS",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": "bundle additive contexts were built without any context bars.",
                    }
                    if isinstance(context_diagnostics.get("bar_count"), int):
                        degradation["bar_count"] = context_diagnostics["bar_count"]
                    reason = str(context_diagnostics.get("reason") or "").strip()
                    if reason:
                        degradation["reason"] = reason
                    warnings.append(dict(degradation))
                    degradations.append(dict(degradation))

            row["status"] = _status_from_lists(failures=failures, warnings=warnings, degradations=degradations)
            row["warnings"] = warnings
            row["failures"] = failures
            row["degradations"] = degradations
            results.append(row)

            all_warnings.extend(warnings)
            all_failures.extend(failures)
            all_degradations.extend(degradations)

    return {
        "results": results,
        "warnings": all_warnings,
        "failures": all_failures,
        "degradations": all_degradations,
        "domain_alerts": all_domain_alerts,
        "bundles": built_bundles,
    }


def _sorted_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=True))


def _promote_release_strict_failures(
    *,
    warnings: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    degradations: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    promoted_warnings: list[dict[str, Any]] = []
    promoted_failures = list(failures)
    promoted_degradations: list[dict[str, Any]] = []

    for row in warnings:
        code = str(row.get("code", ""))
        if code in _STRICT_RELEASE_WARNING_CODES:
            promoted_failures.append(
                {
                    **row,
                    "promoted_by": "release_strict_policy",
                }
            )
            continue
        promoted_warnings.append(row)

    for row in degradations:
        code = str(row.get("code", ""))
        if code in _STRICT_RELEASE_DEGRADATION_CODES:
            promoted_failures.append(
                {
                    **row,
                    "promoted_by": "release_strict_policy",
                }
            )
            continue
        promoted_degradations.append(row)

    return promoted_warnings, promoted_failures, promoted_degradations


def run_provider_health_check(
    *,
    symbols: list[str] | None = None,
    timeframes: list[str] | None = None,
    stale_after_seconds: int | None = None,
    checked_at: float | None = None,
    strict_release_policy: bool = False,
    include_smoke_bundles: bool = False,
) -> dict[str, Any]:
    checked = float(checked_at) if checked_at is not None else _now_ts()
    resolved_symbols = _normalize_symbols(symbols)
    resolved_timeframes = _normalize_timeframes(timeframes)

    provider_results = _provider_domain_results()

    structure_status = discover_structure_source_status(
        source="auto",
        symbol=resolved_symbols[0],
        timeframe=resolved_timeframes[0],
    )

    artifact_health = _collect_artifact_health(
        symbols=resolved_symbols,
        timeframes=resolved_timeframes,
        checked_at=checked,
        stale_after_seconds=stale_after_seconds,
    )

    smoke = _run_smoke_checks(
        symbols=resolved_symbols,
        timeframes=resolved_timeframes,
        checked_at=checked,
        stale_after_seconds=stale_after_seconds,
        allow_release_reference_meta_fallback=bool(strict_release_policy),
    )

    warnings: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    degradations: list[dict[str, Any]] = []

    warnings.extend(artifact_health.get("warnings", []))
    failures.extend(artifact_health.get("failures", []))
    degradations.extend(artifact_health.get("degradations", []))

    warnings.extend(smoke.get("warnings", []))
    failures.extend(smoke.get("failures", []))
    degradations.extend(smoke.get("degradations", []))

    selected_health_issue_count = int(structure_status.get("selected_health_issue_count", 0))
    if selected_health_issue_count > 0:
        degradations.append(
            {
                "code": "STRUCTURE_SOURCE_HEALTH_ISSUES",
                "message": f"selected structure source reports {selected_health_issue_count} health issue(s)",
                "count": selected_health_issue_count,
            }
        )

    if strict_release_policy:
        warnings, failures, degradations = _promote_release_strict_failures(
            warnings=warnings,
            failures=failures,
            degradations=degradations,
        )

    warnings = _sorted_records(warnings)
    failures = _sorted_records(failures)
    degradations = _sorted_records(degradations)
    domain_alerts = _sorted_records(list(smoke.get("domain_alerts", [])))
    smoke_bundles: dict[tuple[str, str], dict[str, Any]] = smoke.get("bundles", {})
    domain_visibility = _summarize_domain_visibility(list(smoke.get("results", [])))

    overall_status = _status_from_lists(failures=failures, warnings=warnings, degradations=degradations)

    report = {
        "checked_at": checked,
        "checked_at_iso": _iso_utc(checked),
        "overall_status": overall_status,
        "reference_symbols": resolved_symbols,
        "reference_timeframes": resolved_timeframes,
        "strict_release_policy": bool(strict_release_policy),
        "provider_domain_results": provider_results,
        "structure_source_status": structure_status,
        "artifact_health": artifact_health,
        "missing_artifacts": list(artifact_health.get("missing_artifacts", [])),
        "stale_artifacts": list(artifact_health.get("stale_artifacts", [])),
        "smoke_test_results": list(smoke.get("results", [])),
        "domain_visibility_score": domain_visibility.get("average_score"),
        "domain_visibility_full_coverage_ratio": domain_visibility.get("full_coverage_ratio"),
        "domain_visibility": domain_visibility,
        "domain_alerts": domain_alerts,
        "warnings": warnings,
        "failures": failures,
        "degradations_detected": degradations,
    }
    if include_smoke_bundles:
        report["smoke_bundles"] = smoke_bundles
    return report


def provider_health_exit_code(report: dict[str, Any], *, fail_on_warn: bool = False) -> int:
    status = str(report.get("overall_status", "fail")).strip().lower()
    if status == "fail":
        return 1
    if fail_on_warn and status == "warn":
        return 2
    return 0


def write_provider_health_report(report: dict[str, Any], output_path: Path | None) -> None:
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if output_path is None:
        print(rendered)
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_text_atomic(output_path, rendered + "\n")
