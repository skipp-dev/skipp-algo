from __future__ import annotations

import argparse
import glob
import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from smc_integration.release_policy import (
    EVIDENCE_LOOKBACK_DAYS,
    EVIDENCE_MIN_DEEPER_OK_RUNS,
    EVIDENCE_MIN_RELEASE_OK_RUNS,
    EVIDENCE_MIN_SYMBOL_COVERAGE,
    EVIDENCE_MIN_TIMEFRAME_COVERAGE,
    REASON_INSUFFICIENT_RUNS,
    REASON_INSUFFICIENT_SYMBOLS,
    REASON_INSUFFICIENT_TIMEFRAMES,
    REASON_STALE_DATA,
)


def _iso_utc(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), tz=UTC).isoformat()


def _parse_report_timestamp(report: dict[str, Any], path: Path) -> float | None:
    checked = report.get("checked_at")
    if isinstance(checked, (int, float)):
        return float(checked)

    refreshed = report.get("generated_at")
    if isinstance(refreshed, (int, float)):
        return float(refreshed)

    try:
        return float(path.stat().st_mtime)
    except Exception:
        return None


def _infer_report_kind(report: dict[str, Any]) -> str:
    explicit = str(report.get("report_kind", "")).strip()
    if explicit:
        return explicit
    if isinstance(report.get("refresh_manifests"), list):
        return "pre_release_refresh"
    if isinstance(report.get("gates"), list):
        return "release_gates"
    if isinstance(report.get("provider_domain_results"), list):
        return "ci_health"
    return "unknown"


def _iter_code_rows(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _extract_codes(report: dict[str, Any]) -> list[str]:
    codes: list[str] = []

    for key in ("failures", "warnings", "degradations_detected", "degradations"):
        for row in _iter_code_rows(report.get(key)):
            code = str(row.get("code", "")).strip()
            if code:
                codes.append(code)

    gates = report.get("gates")
    if isinstance(gates, list):
        for gate in gates:
            if not isinstance(gate, dict):
                continue
            details = gate.get("details")
            if not isinstance(details, dict):
                continue
            for key in ("failures", "warnings", "degradations_detected", "missing_smoke_failures"):
                for row in _iter_code_rows(details.get(key)):
                    code = str(row.get("code", "")).strip()
                    if code:
                        codes.append(code)

    deduped: list[str] = []
    seen: set[str] = set()
    for code in codes:
        if code in seen:
            continue
        seen.add(code)
        deduped.append(code)
    return deduped


def _status_value(report: dict[str, Any]) -> str:
    raw = str(report.get("overall_status", "unknown")).strip().lower()
    if raw in {"ok", "warn", "fail"}:
        return raw
    return "unknown"


def _is_deeper_candidate(kind: str) -> bool:
    return kind == "ci_health"


def _is_release_candidate(kind: str) -> bool:
    return kind == "release_gates"


_STALE_DOMAIN_CODES = {
    "STALE_META_VOLUME_DOMAIN",
    "STALE_META_TECHNICAL_DOMAIN",
    "STALE_META_NEWS_DOMAIN",
}


def _is_core_failure_code(code: str) -> bool:
    upper = str(code).upper()
    if "MISSING" in upper:
        return True
    if "STALE" in upper:
        return True
    if "SMOKE" in upper:
        return True
    if upper in {
        "BUNDLE_BUILD_FAILED",
        "REFRESH_EXECUTION_FAILED",
        "REFRESH_INCOMPLETE_REFERENCE_SET",
        "REFRESH_MANIFEST_ERRORS",
    }:
        return True
    return False


def _render(report: dict[str, Any], output: str) -> None:
    text = json.dumps(report, indent=2, sort_keys=True)
    if output == "-":
        print(text)
        return
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aggregate SMC gate JSON reports into compact operational evidence.")
    parser.add_argument(
        "--input-glob",
        default="artifacts/ci/smc*_report.json",
        help="Glob pattern for gate report JSON files.",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=EVIDENCE_LOOKBACK_DAYS,
        help="Lookback window used for GRUEN evidence readiness evaluation.",
    )
    parser.add_argument(
        "--min-deeper-ok-runs",
        type=int,
        default=EVIDENCE_MIN_DEEPER_OK_RUNS,
        help="Minimum number of successful deeper/nightly health runs in lookback window.",
    )
    parser.add_argument(
        "--min-release-ok-runs",
        type=int,
        default=EVIDENCE_MIN_RELEASE_OK_RUNS,
        help="Minimum number of successful strict release-gate runs in lookback window.",
    )
    parser.add_argument(
        "--fail-on-not-ready",
        action="store_true",
        help="Return exit code 1 when evidence is not green-ready.",
    )
    parser.add_argument("--output", default="-", help="Output path for JSON summary, or '-' for stdout.")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    file_paths = sorted(Path(p) for p in glob.glob(str(args.input_glob)))
    now_ts = float(time.time())
    lookback_seconds = max(0, int(args.lookback_days)) * 24 * 60 * 60
    window_start_ts = now_ts - float(lookback_seconds)

    runs: list[dict[str, Any]] = []
    parse_failures: list[dict[str, Any]] = []
    # Track the most recent meta_domain_diagnostics per symbol/timeframe pair.
    latest_domain_diag: dict[str, dict[str, Any]] = {}  # key: "SYMBOL/TF"
    for path in file_paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            parse_failures.append(
                {
                    "path": str(path),
                    "message": str(exc),
                }
            )
            continue

        if not isinstance(payload, dict):
            parse_failures.append(
                {
                    "path": str(path),
                    "message": "report root must be a JSON object",
                }
            )
            continue

        kind = _infer_report_kind(payload)
        status = _status_value(payload)
        checked_at = _parse_report_timestamp(payload, path)
        runtime_meta = payload.get("runtime_metadata")
        commit = None
        if isinstance(runtime_meta, dict):
            raw_commit = runtime_meta.get("git_commit")
            if isinstance(raw_commit, str) and raw_commit.strip():
                commit = raw_commit.strip()

        codes = _extract_codes(payload)
        runs.append(
            {
                "path": str(path),
                "kind": kind,
                "status": status,
                "checked_at": checked_at,
                "checked_at_iso": _iso_utc(checked_at),
                "in_lookback_window": bool(checked_at is not None and checked_at >= window_start_ts),
                "git_commit": commit,
                "reference_symbols": payload.get("reference_symbols", []),
                "reference_timeframes": payload.get("reference_timeframes", []),
                "codes": codes,
            }
        )

        # Collect meta_domain_diagnostics from smoke_test_results, keyed by
        # symbol/timeframe.  Only the most recent (highest checked_at) wins.
        smoke_results = payload.get("smoke_test_results")
        if isinstance(smoke_results, list):
            for sr in smoke_results:
                if not isinstance(sr, dict):
                    continue
                diag = sr.get("meta_domain_diagnostics")
                if not isinstance(diag, dict):
                    continue
                sym = str(sr.get("symbol", "")).strip().upper()
                tf = str(sr.get("timeframe", "")).strip()
                if not sym or not tf:
                    continue
                key = f"{sym}/{tf}"
                existing_ts = latest_domain_diag.get(key, {}).get("_checked_at")
                if existing_ts is None or (checked_at is not None and checked_at > existing_ts):
                    latest_domain_diag[key] = {**diag, "_checked_at": checked_at}

    runs.sort(key=lambda row: float(row.get("checked_at") or 0.0), reverse=True)

    status_counter: Counter[str] = Counter(str(row.get("status", "unknown")) for row in runs)
    kind_counter: Counter[str] = Counter(str(row.get("kind", "unknown")) for row in runs)

    runs_in_window = [row for row in runs if bool(row.get("in_lookback_window"))]
    deeper_ok_in_window = [row for row in runs_in_window if _is_deeper_candidate(str(row.get("kind", ""))) and row.get("status") == "ok"]
    release_ok_in_window = [row for row in runs_in_window if _is_release_candidate(str(row.get("kind", ""))) and row.get("status") == "ok"]

    recurring_failures: Counter[str] = Counter()
    stale_trend: Counter[str] = Counter()
    missing_trend: Counter[str] = Counter()
    smoke_trend: Counter[str] = Counter()
    stale_domain_trend: Counter[str] = Counter()
    stale_domain_runs: dict[str, list[dict[str, Any]]] = {code: [] for code in sorted(_STALE_DOMAIN_CODES)}

    for row in runs_in_window:
        codes = [str(code) for code in row.get("codes", [])]
        if str(row.get("status")) == "fail":
            recurring_failures.update(codes)
        for code in codes:
            upper = code.upper()
            if "STALE" in upper:
                stale_trend[code] += 1
            if "MISSING" in upper:
                missing_trend[code] += 1
            if "SMOKE" in upper:
                smoke_trend[code] += 1
            if code in _STALE_DOMAIN_CODES:
                stale_domain_trend[code] += 1
                stale_domain_runs[code].append({
                    "path": str(row.get("path", "")),
                    "checked_at_iso": row.get("checked_at_iso"),
                })

    unresolved_core_failures = [
        row
        for row in runs_in_window
        if row.get("status") != "ok" and any(_is_core_failure_code(str(code)) for code in row.get("codes", []))
    ]

    last_ok_at = next((row.get("checked_at") for row in runs if row.get("status") == "ok"), None)
    last_fail_at = next((row.get("checked_at") for row in runs if row.get("status") == "fail"), None)

    # Coverage analysis: which symbols and timeframes appeared in successful runs?
    covered_symbols: set[str] = set()
    covered_timeframes: set[str] = set()
    for row in runs_in_window:
        if row.get("status") == "ok":
            for sym in row.get("reference_symbols", []):
                covered_symbols.add(str(sym).upper())
            for tf in row.get("reference_timeframes", []):
                covered_timeframes.add(str(tf).strip())

    symbol_breadth_ok = len(covered_symbols) >= EVIDENCE_MIN_SYMBOL_COVERAGE
    timeframe_breadth_ok = len(covered_timeframes) >= EVIDENCE_MIN_TIMEFRAME_COVERAGE

    criteria = {
        "lookback_days": int(args.lookback_days),
        "min_deeper_ok_runs": int(args.min_deeper_ok_runs),
        "min_release_ok_runs": int(args.min_release_ok_runs),
        "min_symbol_coverage": EVIDENCE_MIN_SYMBOL_COVERAGE,
        "min_timeframe_coverage": EVIDENCE_MIN_TIMEFRAME_COVERAGE,
    }

    green_ready = (
        len(deeper_ok_in_window) >= int(args.min_deeper_ok_runs)
        and len(release_ok_in_window) >= int(args.min_release_ok_runs)
        and len(unresolved_core_failures) == 0
        and symbol_breadth_ok
        and timeframe_breadth_ok
    )

    # Build structured not-ready reasons for operator clarity.
    not_ready_reasons: list[dict[str, str]] = []
    if len(deeper_ok_in_window) < int(args.min_deeper_ok_runs):
        not_ready_reasons.append({
            "reason": REASON_INSUFFICIENT_RUNS,
            "detail": f"deeper OK runs: {len(deeper_ok_in_window)}/{args.min_deeper_ok_runs}",
        })
    if len(release_ok_in_window) < int(args.min_release_ok_runs):
        not_ready_reasons.append({
            "reason": REASON_INSUFFICIENT_RUNS,
            "detail": f"release OK runs: {len(release_ok_in_window)}/{args.min_release_ok_runs}",
        })
    if not symbol_breadth_ok:
        not_ready_reasons.append({
            "reason": REASON_INSUFFICIENT_SYMBOLS,
            "detail": f"covered {len(covered_symbols)} symbol(s), need >= {EVIDENCE_MIN_SYMBOL_COVERAGE}",
        })
    if not timeframe_breadth_ok:
        not_ready_reasons.append({
            "reason": REASON_INSUFFICIENT_TIMEFRAMES,
            "detail": f"covered {len(covered_timeframes)} timeframe(s), need >= {EVIDENCE_MIN_TIMEFRAME_COVERAGE}",
        })
    if unresolved_core_failures:
        not_ready_reasons.append({
            "reason": REASON_STALE_DATA,
            "detail": f"{len(unresolved_core_failures)} unresolved core failure(s)",
        })

    summary = {
        "generated_at": now_ts,
        "generated_at_iso": _iso_utc(now_ts),
        "report_kind": "gate_evidence_summary",
        "criteria": criteria,
        "runs_total": len(runs),
        "runs_ok": int(status_counter.get("ok", 0)),
        "runs_warn": int(status_counter.get("warn", 0)),
        "runs_fail": int(status_counter.get("fail", 0)),
        "runs_unknown": int(status_counter.get("unknown", 0)),
        "runs_by_kind": dict(kind_counter),
        "last_ok_at": last_ok_at,
        "last_ok_at_iso": _iso_utc(last_ok_at),
        "last_fail_at": last_fail_at,
        "last_fail_at_iso": _iso_utc(last_fail_at),
        "lookback_window_start": window_start_ts,
        "lookback_window_start_iso": _iso_utc(window_start_ts),
        "deeper_ok_runs_in_window": len(deeper_ok_in_window),
        "release_ok_runs_in_window": len(release_ok_in_window),
        "unresolved_core_failures_in_window": len(unresolved_core_failures),
        "covered_symbols": sorted(covered_symbols),
        "covered_timeframes": sorted(covered_timeframes),
        "symbol_breadth_ok": symbol_breadth_ok,
        "timeframe_breadth_ok": timeframe_breadth_ok,
        "recurring_failure_codes": dict(recurring_failures.most_common()),
        "stale_trend": dict(stale_trend),
        "stale_domain_trend": dict(stale_domain_trend),
        "stale_domain_runs": {code: runs_list for code, runs_list in stale_domain_runs.items() if runs_list},
        "missing_trend": dict(missing_trend),
        "smoke_trend": dict(smoke_trend),
        "green_ready": bool(green_ready),
        "not_ready_reasons": not_ready_reasons,
        "latest_domain_diagnostics": {
            key: {k: v for k, v in diag.items() if k != "_checked_at"}
            for key, diag in sorted(latest_domain_diag.items())
        } if latest_domain_diag else {},
        "parse_failures": parse_failures,
        "runs": runs,
    }

    _render(summary, str(args.output))

    if args.fail_on_not_ready and not green_ready:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
