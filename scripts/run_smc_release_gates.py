from __future__ import annotations

# F-V5-A1-2 / F-CI-O1 (2026-05-01) + F-V?-? (2026-05-03): bootstrap repo
# root onto sys.path BEFORE the first-party `from scripts._logging_init`
# import so this file works under both `python -m scripts.X` and
# `python scripts/X.py`. The unconditional `sys.path.insert` (literal
# `sys` name, NOT an alias) also satisfies
# tests/test_workflow_invoked_scripts_import_order.py which detects
# the mutation via AST chain `sys.path.insert` — aliased forms
# (`_v5a12_sys.path.insert`) are not detected and were considered
# late-bootstrap, flagging the early bootstrap import as out-of-order.
import os as _bootstrap_os
import sys as _bootstrap_sys_mod

sys = _bootstrap_sys_mod

_BOOTSTRAP_ROOT = _bootstrap_os.path.dirname(_bootstrap_os.path.dirname(_bootstrap_os.path.abspath(__file__)))
if _BOOTSTRAP_ROOT not in sys.path:
    sys.path.insert(0, _BOOTSTRAP_ROOT)

import argparse
import json
import math
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts._logging_init import init_cli_logging

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Bug-Hunt 2026-05-01 F-01: deferred so the script also works when
# invoked as `python scripts/X.py` (no PYTHONPATH=.) — sys.path.insert
# above must happen before any first-party `from scripts.` import.
from scripts.smc_atomic_write import atomic_write_text
from scripts.smc_pine_evidence_gate import build_evidence_lane_gate
from scripts.verify_smc_micro_publish_contract import verify_publish_contract
from smc_core.benchmark import EventFamily, build_benchmark, export_benchmark_artifacts
from smc_core.schema_version import SCHEMA_VERSION
from smc_core.scoring import (
    export_scoring_artifact,
    score_events,
    serialize_calibration_summary,
    summarize_contextual_calibration,
    summarize_stratified_calibration,
)
from smc_integration.measurement_evidence import build_evidence_id, build_measurement_evidence
from smc_integration.provider_health import run_provider_health_check
from smc_integration.release_policy import (
    RELEASE_REFERENCE_SYMBOLS,
    RELEASE_REFERENCE_TIMEFRAMES,
    RELEASE_STALE_AFTER_SECONDS,
    assess_measurement_shadow_degradations,
    classify_measurement_degradation_severity,
    csv_from_values,
    diagnose_gate_failure,
    get_measurement_shadow_thresholds,
    parse_csv,
    resolve_release_policy,
    runtime_metadata,
    serialize_measurement_shadow_thresholds,
)
from smc_integration.service import build_snapshot_bundle_for_symbol_timeframe
from smc_integration.trust_tier import derive_quality_recommendation


def _iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), tz=UTC).isoformat()


def _parse_csv(raw: str) -> list[str]:
    return parse_csv(raw, normalize_upper=False)


def _normalize_symbols(raw: str) -> list[str]:
    return parse_csv(raw, normalize_upper=True)


def _finite_metric(value: Any) -> float | None:
    try:
        metric = float(value)
    except (TypeError, ValueError):
        return None
    return metric if math.isfinite(metric) else None


def _path_token(raw: str) -> str:
    return str(raw).strip().replace("/", "_").replace(" ", "_")


def _resolve_measurement_output_root(*, report_output: str, explicit_root: str | None) -> Path:
    if explicit_root:
        return Path(explicit_root)
    if report_output != "-":
        return Path(report_output).parent / "measurement"
    return Path("artifacts/ci/measurement")


def _measurement_output_dir(output_root: Path, *, symbol: str, timeframe: str) -> Path:
    return output_root / _path_token(symbol) / _path_token(timeframe)


def _path_for_report(path: Path, *, report_output: str) -> str:
    if report_output != "-":
        base = Path(report_output).parent
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            pass
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


_DATA_ABSENT_CODES = frozenset({
    "source_file_not_found",
    "NONCANONICAL_MANIFEST_WORKBOOK_PATH",
    "MISSING_SMOKE_RESULT",
    # CI-environment codes caused by missing production data files:
    "MISSING_ARTIFACT",
    "EMPTY_CONTEXT_BARS",
    "DOMAIN_DROPPED_NEWS",
    "DOMAIN_DROPPED_TECHNICAL",
    "DOMAIN_DROP_DURING_BUILD",
    "FALLBACK_META_VOLUME_DOMAIN",
    "FALLBACK_META_TECHNICAL_DOMAIN",
    "FALLBACK_META_NEWS_DOMAIN",
    "SILENT_DOMAIN_DROP_NEWS",
    "SILENT_DOMAIN_DROP_TECHNICAL",
    "STRUCTURE_INPUT_LOAD_FAILED",
    # Manifest/artifact staleness — fires when artefacts exist but are old
    # (e.g. stale structure manifests in a local checkout or after a partial
    # refresh on CI):
    "STALE_MANIFEST_GENERATED_AT",
    "STALE_MANIFEST_FILE_MTIME",
    "MISSING_MANIFEST",
    "MISSING_MANIFEST_GENERATED_AT",
    # Meta-domain staleness promoted from degradations by strict policy:
    "STALE_META_ASOF_TS",
    "STALE_META_VOLUME_DOMAIN",
    "STALE_META_TECHNICAL_DOMAIN",
    "STALE_META_NEWS_DOMAIN",
    "META_INPUT_LOAD_FAILED",
    "SOURCE_PLAN_RESOLUTION_FAILED",
    # Domain status alerts — fire when domain status is not "present":
    "META_VOLUME_DOMAIN_STATUS",
    "META_TECHNICAL_DOMAIN_STATUS",
    "META_NEWS_DOMAIN_STATUS",
})


# ---------------------------------------------------------------------------
# TV-Resilience classification (WP-R11)
# ---------------------------------------------------------------------------
# Failure codes emitted by TradingView post-release validation that indicate
# the TradingView web UI itself drifted (selector changes, page structure,
# auth expiry) rather than an actual code or data problem in *our* system.

_TV_EXTERNAL_DRIFT_CODES: frozenset[str] = frozenset({
    # Post-release normalization could not evaluate TV output because one of
    # its TV-side inputs was absent or unreadable (for example a missing raw
    # readonly preflight report, corrupt JSON, or a report with no targets).
    "POST_RELEASE_VALIDATION_FAILED",
    "NO_TARGETS",
    # Auth / storage-state problems — external credential expiry or TV
    # session rotation, not a code defect.
    "AUTH_FAILED",
    "AUTH_NOT_REUSED",
    # Preflight infrastructure — Playwright cannot interact with TV because
    # selectors, modals, or page layout changed on TV side.
    "PREFLIGHT_FAILED",
    "TARGET_FAILED",
    "TARGET_PREFLIGHT_FAILED",
})

# Failure codes that represent *our* code/data responsibility even when
# they appear in a TV-validation gate.
_TV_CODE_OR_DATA_CODES: frozenset[str] = frozenset({
    "PUBLISH_STATUS_NOT_PUBLISHED",
    "VERSION_MISMATCH",
    "MANIFEST_STALE",
    "MANIFEST_MISSING_TIMESTAMP",
    "READONLY_MODE_REQUIRED",
})


def classify_tv_gate_failure(gate: dict[str, Any]) -> str:
    """Classify a ``post_release_validation`` gate failure.

    Returns
    -------
    ``"external_tv_drift"``
        Every failure code in the gate is attributable to external
        TradingView UI/auth drift, not a code or data problem.
    ``"code_or_data"``
        At least one failure code indicates a code or data problem.
    ``"mixed"``
        The gate contains both drift and code/data failure codes.
    ``"unknown"``
        The gate has failures with unrecognized codes.
    """
    details = gate.get("details", {})
    failure_codes: list[str] = []
    for item in details.get("failures", []):
        code = str(item.get("code", "")).strip()
        if code:
            failure_codes.append(code)

    if not failure_codes:
        return "unknown"

    has_drift = any(c in _TV_EXTERNAL_DRIFT_CODES for c in failure_codes)
    has_code = any(c in _TV_CODE_OR_DATA_CODES for c in failure_codes)

    if has_drift and has_code:
        return "mixed"
    if has_drift:
        return "external_tv_drift"
    if has_code:
        return "code_or_data"
    return "unknown"


# ---------------------------------------------------------------------------
# TV validation stage classification (WS1-FT-04)
# ---------------------------------------------------------------------------
# WS1-FT-04 normalises the post-release TV validation onto the real runtime
# pipeline (compile / add-to-chart / runtime) and explicitly carves out the
# input-tab visibility check as a *non-blocking* concern. This complements
# the WP-R11 ``tv_failure_class`` vocabulary above with an orthogonal stage
# vocabulary so reports can name the stage that drifted, and so the
# release-gate runner can stop treating input-tab failures as hard release
# preconditions.

# Auth / session rotation — TV web auth, not a code or runtime problem.
_TV_STAGE_AUTH_CODES: frozenset[str] = frozenset({
    "AUTH_FAILED",
    "AUTH_NOT_REUSED",
})

# Post-release validation input is absent or unreadable — the normalizer can
# only emit a synthetic failure report because it lacks a usable raw TV
# validation artifact, manifest, or target set.
_TV_STAGE_VALIDATION_INPUT_ABSENT_CODES: frozenset[str] = frozenset({
    "POST_RELEASE_VALIDATION_FAILED",
    "NO_TARGETS",
})

# Manifest / publish-state checks — happen before TV is even touched.
_TV_STAGE_MANIFEST_CODES: frozenset[str] = frozenset({
    "PUBLISH_STATUS_NOT_PUBLISHED",
    "VERSION_MISMATCH",
    "MANIFEST_STALE",
    "MANIFEST_MISSING_TIMESTAMP",
    "READONLY_MODE_REQUIRED",
})

# Input-tab visibility — preflight discovers visible Pine inputs. WS1-FT-04
# explicitly carves this stage out: a missing visible Settings input tab
# must not block the release, only the real runtime path (compile, add to
# chart, runtime check) should. ``TARGET_PREFLIGHT_FAILED`` is the
# per-target surface flake (script loaded on the chart but its Settings/
# Inputs surface could not be opened) and shares this soft stage.
_TV_STAGE_INPUT_VISIBILITY_CODES: frozenset[str] = frozenset({
    "PREFLIGHT_FAILED",
    "TARGET_PREFLIGHT_FAILED",
})

# Compile / add-to-chart / runtime — the actual runtime pipeline. A failure
# here is a real release blocker.
_TV_STAGE_COMPILE_ADD_RUNTIME_CODES: frozenset[str] = frozenset({
    "TARGET_FAILED",
})


def _classify_tv_failure_stage(code: str) -> str:
    """Map a single failure code to a TV validation stage."""
    if code in _TV_STAGE_AUTH_CODES:
        return "auth"
    if code in _TV_STAGE_VALIDATION_INPUT_ABSENT_CODES:
        return "validation_input_absent"
    if code in _TV_STAGE_MANIFEST_CODES:
        return "manifest_or_publish"
    if code in _TV_STAGE_INPUT_VISIBILITY_CODES:
        return "input_visibility"
    if code in _TV_STAGE_COMPILE_ADD_RUNTIME_CODES:
        return "compile_add_runtime"
    return "unknown"


def classify_tv_validation_stage(gate: dict[str, Any]) -> dict[str, Any]:
    """Classify the TV validation stage(s) involved in a gate's failures.

    Returns a dict with three stable keys:

    ``stage``
        ``"ok"`` when the gate has no failure codes; otherwise the single
        stage label when all failures share one stage, or ``"mixed"`` when
        more than one stage is involved.
    ``per_code``
        Ordered list of ``{"code", "stage"}`` entries, one per failure code,
        so reports can show *what kind* of TV check drifted.
    ``release_blocking``
        ``True`` when at least one failure is in a stage that should block a
        release (compile/add/runtime, manifest/publish). ``False`` when every
        failure is in a soft-only stage (auth, validation_input_absent,
        input_visibility) that should not block a live release per WS1-FT-04.
    """
    details = gate.get("details", {})
    failure_codes: list[str] = [
        str(item.get("code", "")).strip()
        for item in details.get("failures", [])
        if str(item.get("code", "")).strip()
    ]
    if not failure_codes:
        return {"stage": "ok", "per_code": [], "release_blocking": False}

    per_code = [
        {"code": code, "stage": _classify_tv_failure_stage(code)}
        for code in failure_codes
    ]
    distinct = {entry["stage"] for entry in per_code}
    stage = next(iter(distinct)) if len(distinct) == 1 else "mixed"
    blocking_stages = {"compile_add_runtime", "manifest_or_publish", "unknown"}
    release_blocking = any(entry["stage"] in blocking_stages for entry in per_code)
    return {
        "stage": stage,
        "per_code": per_code,
        "release_blocking": release_blocking,
    }


def _tv_gate_is_soft_only(gate: dict[str, Any]) -> bool:
    """Return True when the gate's failures are all in soft-only TV stages.

    WS1-FT-04 mandates that a missing input tab must not block a live
    release; combined with the existing ``external_tv_drift`` carve-out for
    pure auth and missing-input failures this collapses to "no failure code
    is in a release-blocking stage".
    """
    classification = classify_tv_validation_stage(gate)
    if classification["stage"] == "ok":
        return False
    return not classification["release_blocking"]


# ---------------------------------------------------------------------------
# Hero State Contract — product-state classification (PR 4 of 2026-04-20
# Hero Surface deep-review).
# ---------------------------------------------------------------------------
# Failure-code vocabulary that maps a release-gate failure to a *visible
# product state* of the Hero Surface, parallel to the TV-drift vocabulary
# above. We do NOT introduce new hard validations here: the readonly TV
# validation does not yet emit hero-specific codes. The classifier reuses
# already-emitted codes so report consumers can read a hero-shaped product
# state without touching upstream contracts.

_HERO_DATA_ABSENT_CODES: frozenset[str] = frozenset({
    # Hero state cannot be computed because its source data is absent.
    "MISSING_ARTIFACT",
    "STRUCTURE_INPUT_LOAD_FAILED",
    "META_INPUT_LOAD_FAILED",
    "SOURCE_PLAN_RESOLUTION_FAILED",
    "MISSING_MANIFEST",
})

_HERO_DATA_STALE_CODES: frozenset[str] = frozenset({
    # Hero state would be misleading because its inputs are stale.
    "STALE_MANIFEST_GENERATED_AT",
    "STALE_MANIFEST_FILE_MTIME",
    "STALE_META_ASOF_TS",
    "STALE_META_VOLUME_DOMAIN",
    "STALE_META_TECHNICAL_DOMAIN",
    "STALE_META_NEWS_DOMAIN",
})

_HERO_TRUST_DEGRADED_CODES: frozenset[str] = frozenset({
    # Hero state is computable but trust is reduced — operator should see
    # a degraded trust label rather than an action.
    "DOMAIN_DROPPED_NEWS",
    "DOMAIN_DROPPED_TECHNICAL",
    "DOMAIN_DROP_DURING_BUILD",
    "FALLBACK_META_VOLUME_DOMAIN",
    "FALLBACK_META_TECHNICAL_DOMAIN",
    "FALLBACK_META_NEWS_DOMAIN",
    "SILENT_DOMAIN_DROP_NEWS",
    "SILENT_DOMAIN_DROP_TECHNICAL",
    "META_VOLUME_DOMAIN_STATUS",
    "META_TECHNICAL_DOMAIN_STATUS",
    "META_NEWS_DOMAIN_STATUS",
})


def classify_hero_product_state(gate: dict[str, Any]) -> str:
    """Map a gate failure to a Hero Surface product state.

    Returns one of:

    ``"hero_ok"``
        No failure codes — Hero state is valid for the gate.
    ``"hero_data_absent"``
        Every failure code is in :data:`_HERO_DATA_ABSENT_CODES` — the Hero
        Surface should render the ``DATA_STALE`` / unavailable risk row.
    ``"hero_data_stale"``
        Every failure code is in :data:`_HERO_DATA_STALE_CODES` — the Hero
        Surface should render a stale/aging trust label.
    ``"hero_trust_degraded"``
        Every failure code is in :data:`_HERO_TRUST_DEGRADED_CODES` — the
        Hero Surface should render a degraded trust label.
    ``"hero_external_tv_drift"``
        Every failure code is in :data:`_TV_EXTERNAL_DRIFT_CODES` — Hero
        Surface state is *not* affected; this is a TradingView-only issue.
    ``"hero_mixed"``
        The gate has codes from more than one of the categories above (e.g.
        a real data-stale failure plus a TV-drift failure). Operators should
        treat the data signal first.
    ``"hero_unclassified"``
        At least one failure code is not in any documented Hero category.
        Reported as-is so we can grow the vocabulary intentionally rather
        than silently swallow an unknown.
    """
    details = gate.get("details", {})
    failure_codes: list[str] = [
        str(item.get("code", "")).strip()
        for item in details.get("failures", [])
        if str(item.get("code", "")).strip()
    ]
    if not failure_codes:
        return "hero_ok"

    categories: list[str] = []
    unknown: list[str] = []
    for code in failure_codes:
        if code in _HERO_DATA_ABSENT_CODES:
            categories.append("hero_data_absent")
        elif code in _HERO_DATA_STALE_CODES:
            categories.append("hero_data_stale")
        elif code in _HERO_TRUST_DEGRADED_CODES:
            categories.append("hero_trust_degraded")
        elif code in _TV_EXTERNAL_DRIFT_CODES:
            categories.append("hero_external_tv_drift")
        else:
            unknown.append(code)

    if unknown and not categories:
        return "hero_unclassified"
    if unknown:
        return "hero_mixed"
    distinct = set(categories)
    if len(distinct) == 1:
        return next(iter(distinct))
    return "hero_mixed"


def _gate_failure_is_data_absent(gate: dict[str, Any]) -> bool:
    """Return True if *every* failure signal in this gate is caused by absent data files.

    If the gate has no detail signals at all but every pair result shows
    ``quality_guardrail == "data insufficient"``, we still classify it as
    data-absent (typical for reference_bundle in CI without production data).
    Otherwise, with no signals we conservatively return False.
    """
    details = gate.get("details", {})

    # Collect all failure/alert codes from the gate details.
    signals: list[str] = []
    for key in ("failures", "warnings", "domain_alerts", "missing_smoke_failures"):
        for item in details.get(key, []):
            code = item.get("code") or item.get("status") or ""
            signals.append(str(code))

    # Also check nested domain_drop_reasons in pair_results.
    for pr in details.get("pair_results", []):
        for reason in (pr.get("domain_drop_reasons") or {}).values():
            if isinstance(reason, str):
                signals.append(reason)
            elif isinstance(reason, dict):
                signals.extend(str(v) for v in reason.values())

    if not signals:
        # No explicit failure signals.  Check if all pair_results are
        # "data insufficient" or None — this is a CI data-absence pattern.
        pair_results = details.get("pair_results", [])
        return bool(pair_results and all(pr.get("quality_guardrail") in (None, "data insufficient") for pr in pair_results))

    return all(s in _DATA_ABSENT_CODES for s in signals if s)


def _summarize_stratification(benchmark_result: Any) -> dict[str, Any]:
    bucket_event_counts: dict[str, int] = {}
    dimensions_present: set[str] = set()
    populated_bucket_count = 0

    stratified = getattr(benchmark_result, "stratified", {}) or {}
    for bucket_key, bucket_kpis in sorted(stratified.items()):
        dimension = str(bucket_key).split(":", 1)[0]
        dimensions_present.add(dimension)
        event_count = sum(int(getattr(kpi, "n_events", 0) or 0) for kpi in bucket_kpis)
        bucket_event_counts[str(bucket_key)] = event_count
        if event_count > 0:
            populated_bucket_count += 1

    return {
        "bucket_count": len(bucket_event_counts),
        "populated_bucket_count": populated_bucket_count,
        "dimensions_present": sorted(dimensions_present),
        "bucket_event_counts": bucket_event_counts,
    }


def _load_measurement_history_rows(
    baseline_summary_path: str | None,
    *,
    symbol: str,
    timeframe: str,
) -> tuple[list[dict[str, Any]], str | None]:
    if not baseline_summary_path:
        return [], None

    path = Path(baseline_summary_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [], f"measurement baseline summary could not be loaded: {exc}"

    if not isinstance(payload, dict):
        return [], "measurement baseline summary root must be a JSON object"

    measurement_history = payload.get("measurement_history")
    if not isinstance(measurement_history, dict):
        return [], "measurement baseline summary missing measurement_history"

    history_by_pair = measurement_history.get("history_by_pair")
    if not isinstance(history_by_pair, dict):
        return [], "measurement baseline summary missing measurement_history.history_by_pair"

    pair = f"{symbol}/{timeframe}"
    rows = history_by_pair.get(pair, [])
    if not isinstance(rows, list):
        return [], f"measurement baseline history for {pair} must be a list"

    history_rows = [row for row in rows if isinstance(row, dict)]
    return history_rows, None


def _serialize_family_metrics(scoring_result: Any | None) -> dict[str, dict[str, Any]]:
    raw_metrics = getattr(scoring_result, "family_metrics", None)
    if not isinstance(raw_metrics, dict):
        return {}

    serialized: dict[str, dict[str, Any]] = {}
    for family, metrics in raw_metrics.items():
        n_ev = int(getattr(metrics, "n_events", 0) or 0)
        hr = _finite_metric(getattr(metrics, "hit_rate", None))
        serialized[str(family)] = {
            "n_events": n_ev,
            "brier_score": _finite_metric(getattr(metrics, "brier_score", None)),
            "log_score": _finite_metric(getattr(metrics, "log_score", None)),
            "hit_rate": hr,
            # Option A (W11-1): explicit skip_reason so downstream reporters
            # can show "Family BOS: 0 Trades, nicht bewertet" instead of
            # silently omitting the family from the FDR advisory report.
            "skip_reason": (
                None
                if hr is not None
                else ("no_trades" if n_ev == 0 else "non_finite")
            ),
        }
    return serialized


def _write_measurement_manifest(
    *,
    output_dir: Path,
    symbol: str,
    timeframe: str,
    benchmark_artifact_path: Path,
    benchmark_manifest_path: Path,
    benchmark_artifact_present: bool,
    scoring_artifact_path: Path,
    scoring_artifact_present: bool,
    measurement_evidence_present: bool,
    evaluated_event_counts: dict[str, Any],
    bars_source_mode: str | None,
    warnings: list[str],
    benchmark_event_counts: dict[str, int],
    stratification_coverage: dict[str, Any],
    scoring_result: Any | None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "measurement_manifest.json"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": float(time.time()),
        "symbol": symbol,
        "timeframe": timeframe,
        "measurement_evidence_present": bool(measurement_evidence_present),
        "evaluated_event_counts": dict(evaluated_event_counts),
        "bars_source_mode": bars_source_mode,
        "artifacts": {
            "benchmark": {
                "present": bool(benchmark_artifact_present),
                "artifact_path": benchmark_artifact_path.name,
                "manifest_path": benchmark_manifest_path.name,
            },
            "scoring": {
                "present": bool(scoring_artifact_present),
                "artifact_path": scoring_artifact_path.name,
            },
        },
        "quality_summary": {
            "benchmark_event_counts": dict(benchmark_event_counts),
            "stratification_coverage": dict(stratification_coverage),
            "n_events": int(getattr(scoring_result, "n_events", 0) or 0),
            "brier_score": _finite_metric(getattr(scoring_result, "brier_score", None)),
            "log_score": _finite_metric(getattr(scoring_result, "log_score", None)),
            "hit_rate": _finite_metric(getattr(scoring_result, "hit_rate", None)),
            "calibration": serialize_calibration_summary(getattr(scoring_result, "calibration", None)),
            "stratified_calibration": summarize_stratified_calibration(
                getattr(scoring_result, "stratified_calibration", {}) or {}
            ),
            "contextual_calibration": summarize_contextual_calibration(
                getattr(scoring_result, "contextual_calibration", {}) or {}
            ),
            "family_metrics": _serialize_family_metrics(scoring_result),
        },
        "warnings": list(warnings),
    }
    atomic_write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", manifest_path)
    return manifest_path


def _missing_smoke_pairs(provider_report: dict[str, Any], *, symbols: list[str], timeframes: list[str]) -> list[dict[str, str]]:
    rows = provider_report.get("smoke_test_results", []) if isinstance(provider_report, dict) else []
    seen: set[tuple[str, str]] = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol", "")).strip().upper()
        timeframe = str(item.get("timeframe", "")).strip()
        if symbol and timeframe:
            seen.add((symbol, timeframe))

    missing: list[dict[str, str]] = []
    for symbol in symbols:
        for timeframe in timeframes:
            if (symbol, timeframe) not in seen:
                missing.append({"symbol": symbol, "timeframe": timeframe})
    return missing


def _status_ok_or_warn(status: str, *, fail_on_warn: bool) -> bool:
    if status == "ok":
        return True
    return bool(status == "warn" and not fail_on_warn)


def _run_publish_contract_gate(args: argparse.Namespace) -> dict[str, Any]:
    try:
        verify_publish_contract(
            manifest_path=Path(args.manifest),
            core_path=Path(args.core_engine),
        )
        return {
            "name": "publish_contract",
            "status": "ok",
            "details": {
                "manifest": args.manifest,
                "core_engine": args.core_engine,
            },
        }
    except Exception as exc:
        return {
            "name": "publish_contract",
            "status": "fail",
            "details": {
                "message": str(exc),
                "manifest": args.manifest,
                "core_engine": args.core_engine,
            },
        }


def _run_reference_bundle_gate(
    symbol: str,
    timeframe: str,
    generated_at: float,
    *,
    cached_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        bundle = cached_bundle or build_snapshot_bundle_for_symbol_timeframe(
            symbol,
            timeframe,
            source="auto",
            generated_at=generated_at,
            allow_release_reference_meta_fallback=True,
        )
    except Exception as exc:
        return {
            "name": "reference_bundle",
            "status": "fail",
            "details": {
                "symbol": symbol,
                "timeframe": timeframe,
                "message": str(exc),
            },
        }

    snapshot = bundle.get("snapshot")
    if not isinstance(snapshot, dict):
        return {
            "name": "reference_bundle",
            "status": "fail",
            "details": {
                "symbol": symbol,
                "timeframe": timeframe,
                "message": "bundle has no dict snapshot payload",
            },
        }

    if "structure_context" in snapshot:
        return {
            "name": "reference_bundle",
            "status": "fail",
            "details": {
                "symbol": symbol,
                "timeframe": timeframe,
                "message": "structure_context must be additive and may not exist inside snapshot",
            },
        }

    trust_summary = bundle.get("trust_summary") or {}
    return {
        "name": "reference_bundle",
        "status": "ok",
        "details": {
            "symbol": symbol,
            "timeframe": timeframe,
            "snapshot_keys": sorted(snapshot.keys()),
            "quality_recommendation": trust_summary.get("quality_recommendation"),
            "quality_guardrail": trust_summary.get("quality_guardrail"),
            "quality_recommendation_reason": trust_summary.get("quality_recommendation_reason"),
        },
    }


def _run_measurement_gate(
    symbol: str,
    timeframe: str,
    *,
    output_root: Path,
    report_output: str = "-",
    baseline_summary_path: str | None = None,
    strict_measurement_shadow: bool = False,
) -> dict[str, Any]:
    """Generate benchmark + scoring artifacts and validate their structure.

    This gate is *soft* — it reports warnings but never blocks the release.
    It validates:
      - benchmark artifact can be produced and has valid structure
      - scoring artifact can be produced and has valid structure
      - brier_score is finite and in [0, 1] (if present)
      - log_score is finite and >= 0 (if present)
    """
    warnings: list[str] = []
    output_dir = _measurement_output_dir(output_root, symbol=symbol, timeframe=timeframe)
    benchmark_artifact_path = output_dir / f"benchmark_{symbol}_{timeframe}.json"
    benchmark_manifest_path = output_dir / "manifest.json"
    scoring_artifact_path = output_dir / f"scoring_{symbol}_{timeframe}.json"
    measurement_manifest_path = output_dir / "measurement_manifest.json"
    empty_events: dict[EventFamily, list[dict[str, Any]]] = {
        "BOS": [],
        "OB": [],
        "FVG": [],
        "SWEEP": [],
    }
    benchmark_event_counts: dict[str, int] = {}
    stratification_coverage = {
        "bucket_count": 0,
        "populated_bucket_count": 0,
        "dimensions_present": [],
        "bucket_event_counts": {},
    }
    scoring_result = None

    details: dict[str, Any] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "measurement_artifacts_present": False,
        "scoring_artifacts_present": False,
        "measurement_evidence_present": False,
        "measurement_manifest_present": False,
        "benchmark_event_counts": {},
        "stratification_coverage": stratification_coverage,
        "measurement_output_dir": _path_for_report(output_dir, report_output=report_output),
        "benchmark_artifact_path": _path_for_report(benchmark_artifact_path, report_output=report_output),
        "benchmark_manifest_path": _path_for_report(benchmark_manifest_path, report_output=report_output),
        "scoring_artifact_path": _path_for_report(scoring_artifact_path, report_output=report_output),
        "measurement_manifest_path": _path_for_report(measurement_manifest_path, report_output=report_output),
        "measurement_shadow_thresholds": serialize_measurement_shadow_thresholds(get_measurement_shadow_thresholds()),
        "measurement_shadow_baseline": {
            "available": False,
            "history_runs": 0,
            "required_history_runs": get_measurement_shadow_thresholds().min_history_runs,
            "brier_score": None,
            "log_score": None,
            "calibrated_brier_score": None,
            "calibrated_ece": None,
            "n_events": None,
            "populated_bucket_count": None,
            "effective_thresholds": serialize_measurement_shadow_thresholds(get_measurement_shadow_thresholds()),
            "history_tightened_metrics": [],
            "calibrated_thresholds_eligible": False,
            "calibrated_thresholds_floor": (
                get_measurement_shadow_thresholds().min_events_for_calibrated_thresholds
            ),
        },
        "measurement_shadow_effective_thresholds": serialize_measurement_shadow_thresholds(get_measurement_shadow_thresholds()),
        "measurement_shadow_strict": bool(strict_measurement_shadow),
        "measurement_baseline_summary_path": baseline_summary_path,
        "measurement_degradations_detected": [],
        "degradations_detected": [],
    }

    try:
        evidence = build_measurement_evidence(symbol, timeframe)
        details.update(evidence.details)
        warnings.extend(evidence.warnings)
    except Exception as exc:
        evidence = None
        warnings.append(f"measurement evidence generation failed: {exc}")

    # -- Evidence ID (F-02) -------------------------------------------------
    gate_timestamp = float(time.time())
    evidence_id = build_evidence_id(
        symbol=symbol,
        timeframe=timeframe,
        run_timestamp=gate_timestamp,
    )
    details["evidence_id"] = evidence_id
    details["evidence_timestamp"] = gate_timestamp
    details["evidence_path"] = _path_for_report(output_dir, report_output=report_output)

    # -- Benchmark artifact -------------------------------------------------
    try:
        benchmark_result = build_benchmark(
            symbol,
            timeframe,
            events_by_family=evidence.events_by_family if evidence is not None else empty_events,
            stratified_events=evidence.stratified_events if evidence is not None and evidence.stratified_events else None,
        )
        export_benchmark_artifacts(benchmark_result, output_dir)
        details["measurement_artifacts_present"] = True
        details["benchmark_families"] = len(benchmark_result.kpis)
        details["benchmark_schema_version"] = benchmark_result.schema_version
        benchmark_event_counts = {
            kpi.family: int(kpi.n_events)
            for kpi in benchmark_result.kpis
        }
        stratification_coverage = _summarize_stratification(benchmark_result)
        details["benchmark_event_counts"] = benchmark_event_counts
        details["stratification_coverage"] = stratification_coverage
    except Exception as exc:
        warnings.append(f"benchmark artifact generation failed: {exc}")

    # -- Scoring artifact ---------------------------------------------------
    try:
        scoring_result = score_events(evidence.scored_events if evidence is not None else [])
        export_scoring_artifact(
            scoring_result,
            symbol=symbol,
            timeframe=timeframe,
            output_dir=output_dir,
            schema_version=SCHEMA_VERSION,
        )
        details["scoring_artifacts_present"] = True
        details["scoring_event_count"] = int(scoring_result.n_events)
        details["scoring_family_metrics"] = _serialize_family_metrics(scoring_result)
        details["scoring_families_present"] = sorted(details["scoring_family_metrics"].keys())
        details["calibration"] = serialize_calibration_summary(getattr(scoring_result, "calibration", None))
        details["stratified_calibration"] = summarize_stratified_calibration(
            getattr(scoring_result, "stratified_calibration", {}) or {}
        )
        details["contextual_calibration"] = summarize_contextual_calibration(
            getattr(scoring_result, "contextual_calibration", {}) or {}
        )
        details["calibration_method"] = details["calibration"].get("method")
        details["calibrated_brier_score"] = details["calibration"].get("calibrated_brier_score")
        details["calibrated_log_score"] = details["calibration"].get("calibrated_log_score")
        details["raw_ece"] = details["calibration"].get("raw_ece")
        details["calibrated_ece"] = details["calibration"].get("calibrated_ece")

        bs = scoring_result.brier_score
        ls = scoring_result.log_score
        if math.isfinite(bs) and not (0.0 <= bs <= 1.0):
            warnings.append(f"brier_score {bs:.6f} outside expected range [0, 1]")
        if math.isfinite(ls) and ls < 0:
            warnings.append(f"log_score {ls:.6f} is negative (expected >= 0)")
        details["brier_score"] = _finite_metric(bs)
        details["log_score"] = _finite_metric(ls)
        details["scoring_hit_rate"] = _finite_metric(scoring_result.hit_rate)
        details["brier_finite"] = math.isfinite(bs) if not math.isnan(bs) else "nan_empty"
        details["log_finite"] = math.isfinite(ls) if not math.isnan(ls) else "nan_empty"
    except Exception as exc:
        warnings.append(f"scoring artifact generation failed: {exc}")

    # -- Phase-1 soft-warn checks (WP-A8) ----------------------------------
    _soft_thresholds = get_measurement_shadow_thresholds()
    if scoring_result is not None:
        _bs = scoring_result.brier_score
        if math.isfinite(_bs) and _bs > _soft_thresholds.soft_warn_max_brier_score:
            warnings.append(
                f"Brier score {_bs:.4f} exceeds soft threshold ({_soft_thresholds.soft_warn_max_brier_score})"
            )
        _evt_count = int(scoring_result.n_events)
        _fam_count = len(scoring_result.family_metrics)
        _total_families = 4  # BOS, OB, FVG, SWEEP
        _coverage_ratio = _fam_count / _total_families if _total_families > 0 else 0.0
        if _coverage_ratio < _soft_thresholds.soft_warn_min_event_coverage_ratio:
            warnings.append(
                f"Event coverage {_coverage_ratio:.0%} below soft threshold ({_soft_thresholds.soft_warn_min_event_coverage_ratio:.0%})"
            )

    try:
        _write_measurement_manifest(
            output_dir=output_dir,
            symbol=symbol,
            timeframe=timeframe,
            benchmark_artifact_path=benchmark_artifact_path,
            benchmark_manifest_path=benchmark_manifest_path,
            benchmark_artifact_present=bool(details["measurement_artifacts_present"]),
            scoring_artifact_path=scoring_artifact_path,
            scoring_artifact_present=bool(details["scoring_artifacts_present"]),
            measurement_evidence_present=bool(details.get("measurement_evidence_present")),
            evaluated_event_counts=details.get("evaluated_event_counts", {}) or {},
            bars_source_mode=str(details.get("bars_source_mode", "") or "") or None,
            warnings=warnings,
            benchmark_event_counts=benchmark_event_counts,
            stratification_coverage=stratification_coverage,
            scoring_result=scoring_result,
        )
        details["measurement_manifest_present"] = True
    except Exception as exc:
        warnings.append(f"measurement manifest export failed: {exc}")

    history_rows, history_error = _load_measurement_history_rows(
        baseline_summary_path,
        symbol=symbol,
        timeframe=timeframe,
    )
    if history_error:
        warnings.append(history_error)

    current_entry = {
        "pair": f"{symbol}/{timeframe}",
        "symbol": symbol,
        "timeframe": timeframe,
        "brier_score": details.get("brier_score"),
        "log_score": details.get("log_score"),
        "calibrated_brier_score": details.get("calibrated_brier_score"),
        "calibrated_ece": details.get("calibrated_ece"),
        "n_events": details.get("scoring_event_count", 0),
        "stratification_coverage": details.get("stratification_coverage", {}),
    }
    measurement_degradations, shadow_baseline = assess_measurement_shadow_degradations(
        current_entry,
        history_rows,
        thresholds=get_measurement_shadow_thresholds(),
    )
    details["measurement_shadow_baseline"] = shadow_baseline
    raw_effective_thresholds = shadow_baseline.get("effective_thresholds")
    details["measurement_shadow_effective_thresholds"] = (
        dict(raw_effective_thresholds)
        if isinstance(raw_effective_thresholds, dict)
        else serialize_measurement_shadow_thresholds(get_measurement_shadow_thresholds())
    )
    details["measurement_degradations_detected"] = measurement_degradations
    details["degradations_detected"] = measurement_degradations
    hard_blocking, advisory = classify_measurement_degradation_severity(measurement_degradations)
    details["hard_blocking_degradations"] = hard_blocking
    details["advisory_degradations"] = advisory

    # Derive measurement-scoped quality recommendation.
    _scoring_events = int(details.get("scoring_event_count") or 0)
    _m_quality_tier = str(details.get("calibration", {}).get("method", "") or "").strip()
    if _scoring_events == 0:
        _gate_trust = "insufficient"
        _gate_provider = "unavailable"
        _gate_quality = "unknown"
    elif hard_blocking:
        _gate_trust = "degraded"
        _gate_provider = "degraded"
        _gate_quality = "low"
    else:
        _gate_trust = "guarded"
        _gate_provider = "available"
        _gate_quality = "ok" if _m_quality_tier else "unknown"
    _quality_rec = derive_quality_recommendation(
        trust_state=_gate_trust,
        measurement_quality_tier=_gate_quality,
        measurement_events=_scoring_events,
        provider_state=_gate_provider,
    )
    details["quality_recommendation"] = _quality_rec["recommendation"]
    details["quality_guardrail"] = _quality_rec["guardrail"]
    details["quality_recommendation_reason"] = _quality_rec["reason"]

    for degradation in measurement_degradations:
        detail = str(degradation.get("detail", degradation.get("code", "measurement degradation"))).strip()
        warnings.append(detail)

    details["warnings"] = warnings
    has_hard_block = bool(hard_blocking)
    if (strict_measurement_shadow and measurement_degradations) or has_hard_block:
        status = "fail"
    else:
        # Measurement gate is soft by default — "ok" or "warn" unless explicitly promoted.
        status = "warn" if warnings or measurement_degradations else "ok"
    is_blocking = has_hard_block or bool(strict_measurement_shadow and measurement_degradations)
    return {
        "name": "measurement_lane",
        "status": status,
        "blocking": is_blocking,
        "details": details,
    }


def _run_post_release_validation_gate(report_path: str) -> dict[str, Any]:
    path = Path(report_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "name": "post_release_validation",
            "status": "fail",
            "details": {
                "report_path": path.as_posix(),
                "message": "post-release validation report not found",
            },
        }
    except Exception as exc:
        return {
            "name": "post_release_validation",
            "status": "fail",
            "details": {
                "report_path": path.as_posix(),
                "message": f"post-release validation report unreadable: {exc}",
            },
        }

    if not isinstance(payload, dict):
        return {
            "name": "post_release_validation",
            "status": "fail",
            "details": {
                "report_path": path.as_posix(),
                "message": "post-release validation report root must be a JSON object",
            },
        }

    overall_status = str(payload.get("overall_status", "unknown")).strip().lower()
    gate_status = "ok" if overall_status == "ok" else "fail"
    gate = {
        "name": "post_release_validation",
        "status": gate_status,
        "details": {
            "report_path": path.as_posix(),
            "overall_status": overall_status,
            "validated_target_count": int(payload.get("validated_target_count", 0) or 0),
            "failures": payload.get("failures", []),
        },
    }
    if gate_status == "fail":
        gate["tv_failure_class"] = classify_tv_gate_failure(gate)
        gate["hero_product_state"] = classify_hero_product_state(gate)
        gate["tv_validation_stage"] = classify_tv_validation_stage(gate)
    return gate


def _render(report: dict[str, Any], output: str) -> None:
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if output == "-":
        print(rendered)
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(rendered + "\n", path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run strict SMC release gates.")
    parser.add_argument(
        "--symbols",
        default=csv_from_values(RELEASE_REFERENCE_SYMBOLS),
        help="Comma-separated reference symbols used for strict release checks.",
    )
    parser.add_argument(
        "--timeframes",
        default=csv_from_values(RELEASE_REFERENCE_TIMEFRAMES),
        help="Comma-separated reference timeframes used for strict release checks.",
    )
    parser.add_argument(
        "--stale-after-seconds",
        type=int,
        default=RELEASE_STALE_AFTER_SECONDS,
        help="Staleness threshold used by strict release provider health checks.",
    )
    parser.add_argument(
        "--fail-on-warn",
        action="store_true",
        help="Also fail strict release gates on non-core warnings.",
    )
    parser.add_argument(
        "--allow-warn",
        action="store_true",
        help="Deprecated compatibility flag. When provided, non-core warnings are not blocking.",
    )
    parser.add_argument(
        "--skip-publish-contract",
        action="store_true",
        help="Skip publish contract verification gate.",
    )
    parser.add_argument(
        "--manifest",
        default="pine/generated/smc_micro_profiles_generated.json",
        help="Path to micro publish manifest used by publish contract gate.",
    )
    parser.add_argument(
        "--core-engine",
        default="SMC_Core_Engine.pine",
        help="Path to core engine pine file used by publish contract gate.",
    )
    parser.add_argument(
        "--measurement-output-root",
        default=None,
        help="Directory where measurement artifacts are written. Defaults to <output-dir>/measurement or artifacts/ci/measurement when output is stdout.",
    )
    parser.add_argument(
        "--measurement-baseline-summary",
        default=None,
        help="Optional evidence summary JSON used as historical baseline for measurement shadow comparisons.",
    )
    parser.add_argument(
        "--post-release-validation-report",
        default=None,
        help="Optional path to a normalized post-release validation report to evaluate as a blocking gate.",
    )
    parser.add_argument(
        "--ci-mode",
        action="store_true",
        help=(
            "Run in CI-safe mode: gates that fail purely due to absent "
            "production data (source files, workbook) are downgraded to "
            "non-blocking so the workflow exits 0.  Gate status is still "
            "reported transparently."
        ),
    )
    parser.add_argument("--output", default="-", help="Output path for JSON report, or '-' for stdout.")
    return parser


def main() -> int:
    init_cli_logging()  # F-V5-A1-2 (2026-05-01)
    args = build_parser().parse_args()
    checked_at = float(time.time())

    # Resolve effective policy: CLI args > env vars > defaults.
    policy = resolve_release_policy(
        symbols=args.symbols if args.symbols != csv_from_values(RELEASE_REFERENCE_SYMBOLS) else None,
        timeframes=args.timeframes if args.timeframes != csv_from_values(RELEASE_REFERENCE_TIMEFRAMES) else None,
        stale_after_seconds=args.stale_after_seconds if args.stale_after_seconds != RELEASE_STALE_AFTER_SECONDS else None,
    )
    symbols = policy["symbols"] or list(RELEASE_REFERENCE_SYMBOLS)
    timeframes = policy["timeframes"] or list(RELEASE_REFERENCE_TIMEFRAMES)
    stale_seconds = int(policy["stale_after_seconds"])
    fail_on_warn = bool(args.fail_on_warn) and not bool(args.allow_warn)
    measurement_output_root = _resolve_measurement_output_root(
        report_output=args.output,
        explicit_root=args.measurement_output_root,
    )

    provider_report = run_provider_health_check(
        symbols=symbols,
        timeframes=timeframes,
        stale_after_seconds=stale_seconds,
        checked_at=checked_at,
        strict_release_policy=True,
        include_smoke_bundles=True,
    )

    provider_status = str(provider_report.get("overall_status", "fail")).lower()
    missing_smoke_pairs = _missing_smoke_pairs(provider_report, symbols=symbols, timeframes=timeframes)
    missing_smoke_failures = [
        {
            "code": "MISSING_SMOKE_RESULT",
            "symbol": row["symbol"],
            "timeframe": row["timeframe"],
            "message": f"No smoke test result for {row['symbol']}/{row['timeframe']}; pair expected but absent in provider health report.",
        }
        for row in missing_smoke_pairs
    ]

    # Extract smoke-check bundles so reference_bundle gate can reuse them
    # instead of rebuilding from scratch (WP-R12).
    _smoke_bundles: dict[tuple[str, str], dict[str, Any]] = provider_report.pop("smoke_bundles", {})

    gates: list[dict[str, Any]] = [
        {
            "name": "provider_health",
            "status": "ok" if _status_ok_or_warn(provider_status, fail_on_warn=fail_on_warn) and not missing_smoke_failures else "fail",
            "blocking": True,
            "details": {
                "overall_status": provider_status,
                "domain_alerts": provider_report.get("domain_alerts", []),
                "failures": provider_report.get("failures", []),
                "warnings": provider_report.get("warnings", []),
                "degradations_detected": provider_report.get("degradations_detected", []),
                "missing_smoke_failures": missing_smoke_failures,
            },
        }
    ]

    # Reference bundle gate — evaluate all symbol/timeframe pairs.
    _ref_pair_results = [
        _run_reference_bundle_gate(
            sym, tf, checked_at,
            cached_bundle=_smoke_bundles.get((sym, tf)),
        )
        for sym in symbols for tf in timeframes
    ]
    del _smoke_bundles
    _ref_any_fail = any(r.get("status") == "fail" for r in _ref_pair_results)
    gates.append({
        "name": "reference_bundle",
        "status": "fail" if _ref_any_fail else "ok",
        "details": {
            "pairs_checked": len(_ref_pair_results),
            "pair_results": [r.get("details", {}) for r in _ref_pair_results],
        },
    })

    # Pine evidence lane gate (WS1-FT-03) — read-only round-trip of the
    # canonical Pine scenario catalog through the Hero State Contract using
    # deterministic in-process fixtures. Blocks the structural pass when a
    # canonical decision-case drifts from its expected Hero State.
    gates.append(build_evidence_lane_gate())

    if not args.skip_publish_contract:
        gates.append(_run_publish_contract_gate(args))

    post_release_validation_report = getattr(args, "post_release_validation_report", None)
    release_phase = "post_publish" if post_release_validation_report else "pre_publish"
    if post_release_validation_report:
        gates.append(_run_post_release_validation_gate(str(post_release_validation_report)))

    # Measurement gate — soft, non-blocking.  Evaluate all pairs.
    _m_pair_results = [
        _run_measurement_gate(
            sym,
            tf,
            output_root=measurement_output_root,
            report_output=args.output,
            baseline_summary_path=args.measurement_baseline_summary,
        )
        for sym in symbols for tf in timeframes
    ]
    _m_any_fail = any(r.get("status") == "fail" for r in _m_pair_results)
    _m_any_blocking = any(r.get("blocking") for r in _m_pair_results)
    _m_any_warn = any(r.get("status") == "warn" for r in _m_pair_results)
    gates.append({
        "name": "measurement_lane",
        "status": "fail" if _m_any_fail else ("warn" if _m_any_warn else "ok"),
        "blocking": _m_any_blocking,
        "details": {
            "pairs_checked": len(_m_pair_results),
            "pair_results": [r.get("details", {}) for r in _m_pair_results],
        },
    })

    # WS1-FT-04: input-tab visibility (preflight) and pure auth failures
    # are not real release blockers. They are stage-soft TV-validation
    # failures that should not stop a live publish. We always downgrade
    # such gates regardless of --ci-mode so the operational release pass
    # is not gated on the input-tab being present in TV's Settings panel.
    tv_soft_downgrades: list[str] = []
    for gate in gates:
        if gate.get("status") != "fail" or not gate.get("blocking", True):
            continue
        if gate.get("name") != "post_release_validation":
            continue
        if _tv_gate_is_soft_only(gate):
            gate["blocking"] = False
            gate["tv_soft_only_downgraded"] = True
            tv_soft_downgrades.append(gate["name"])

    # --ci-mode: downgrade data-absent blocking gates to non-blocking.
    # Also downgrade TV-validation gates whose failures are purely external
    # UI/auth drift (WP-R11).
    ci_mode = getattr(args, "ci_mode", False)
    ci_mode_downgrades: list[str] = []
    if ci_mode:
        for gate in gates:
            if gate.get("status") != "fail" or not gate.get("blocking", True):
                continue
            if _gate_failure_is_data_absent(gate):
                gate["blocking"] = False
                gate["ci_mode_downgraded"] = True
                ci_mode_downgrades.append(gate["name"])
            elif gate.get("tv_failure_class") == "external_tv_drift":
                gate["blocking"] = False
                gate["ci_mode_downgraded"] = True
                gate["ci_mode_downgrade_reason"] = "external_tv_drift"
                ci_mode_downgrades.append(gate["name"])

    has_fail = any(gate.get("status") == "fail" for gate in gates if gate.get("blocking", True))
    overall_status = "fail" if has_fail else "ok"
    exit_code = 1 if has_fail else 0

    # ── Gate classification (F-09) ─────────────────────────────
    # Two explicit pass classes so operators never confuse CI green with
    # full operational clearance.
    #   ci_structural_pass:       all CI-validatable gates are green
    #   operational_release_pass: all gates including live-only are green
    ci_validatable_gates = [
        g for g in gates
        if g.get("name") in {"publish_contract", "reference_bundle", "measurement_lane", "provider_health", "evidence_lane"}
    ]
    _live_only_gates = [
        g for g in gates
        if g.get("name") in {"post_release_validation"}
    ]
    ci_structural_pass = not any(
        g.get("status") == "fail" for g in ci_validatable_gates
        if g.get("blocking", True) and not g.get("ci_mode_downgraded")
    )
    operational_release_pass = not any(
        g.get("status") == "fail" for g in gates if g.get("blocking", True)
    )

    # Gates that are currently not hard but have a re-evaluation path.
    soft_gates_for_review = [
        {
            "name": g["name"],
            "current_status": g.get("status"),
            "blocking": g.get("blocking", True),
            "review_reason": (
                "ci_mode_downgraded" if g.get("ci_mode_downgraded")
                else "tv_soft_only_downgraded" if g.get("tv_soft_only_downgraded")
                else "soft_by_design"
            ),
        }
        for g in gates
        if not g.get("blocking", True) or g.get("ci_mode_downgraded")
    ]

    report = {
        "report_kind": "release_gates",
        "release_phase": release_phase,
        "checked_at": checked_at,
        "checked_at_iso": _iso_utc(checked_at),
        "overall_status": overall_status,
        "ci_structural_pass": ci_structural_pass,
        "operational_release_pass": operational_release_pass,
        "reference_symbols": symbols,
        "reference_timeframes": timeframes,
        "stale_after_seconds": stale_seconds,
        "fail_on_warn": fail_on_warn,
        "gates": gates,
        "soft_gates_for_review": soft_gates_for_review,
        "runner": {
            "script": "scripts/run_smc_release_gates.py",
            "mode": "strict_release_gates",
            "skip_publish_contract": bool(args.skip_publish_contract),
            "post_release_validation_report": post_release_validation_report,
            "measurement_output_root": measurement_output_root.as_posix(),
            "measurement_baseline_summary": args.measurement_baseline_summary,
            "ci_mode": ci_mode,
            "ci_mode_downgrades": ci_mode_downgrades,
            "tv_soft_downgrades": tv_soft_downgrades,
            "exit_code": int(exit_code),
        },
        "runtime_metadata": runtime_metadata(),
    }

    # Attach structured failure diagnostics so operators see *why* a gate failed.
    if overall_status == "fail":
        report["failure_reasons"] = diagnose_gate_failure(report)

    _render(report, args.output)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
