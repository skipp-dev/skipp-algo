from __future__ import annotations

import os
import subprocess
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Operational release baseline: representative liquid US equities across
# sectors (Tech, Healthcare, Finance, Energy, Consumer, Industrials,
# Communication, Materials, Real-Estate, Utilities).  The set is intentionally
# broad so release gates exercise the full provider/artifact/smoke stack
# across realistic market-structure conditions.
# ---------------------------------------------------------------------------
RELEASE_REFERENCE_SYMBOLS: tuple[str, ...] = (
    "AAPL",   # Tech / mega-cap
    "MSFT",   # Tech / mega-cap
    "AMZN",   # Consumer / Tech
    "JPM",    # Financials
    "JNJ",    # Healthcare
    "XOM",    # Energy
    "CAT",    # Industrials
    "PG",     # Consumer Staples
    "NEE",    # Utilities
    "AMT",    # Real-Estate / REIT
    "META",   # Communication
    "LIN",    # Materials
)
RELEASE_REFERENCE_TIMEFRAMES: tuple[str, ...] = ("5m", "15m", "1H", "4H")

# 7-day freshness: artifacts older than one trading week are considered stale
# for active signal release purposes.
RELEASE_STALE_AFTER_SECONDS: int = 7 * 24 * 60 * 60

# Evidence policy used for GELB->GRUEN release decisions.
EVIDENCE_LOOKBACK_DAYS: int = 14
EVIDENCE_MIN_DEEPER_OK_RUNS: int = 3
EVIDENCE_MIN_RELEASE_OK_RUNS: int = 2

# Minimum coverage thresholds for release evidence.
EVIDENCE_MIN_SYMBOL_COVERAGE: int = 5
EVIDENCE_MIN_TIMEFRAME_COVERAGE: int = 2

# ---------------------------------------------------------------------------
# Environment variable names for config-driven overrides.
# ---------------------------------------------------------------------------
_ENV_SYMBOLS = "SMC_RELEASE_SYMBOLS"
_ENV_TIMEFRAMES = "SMC_RELEASE_TIMEFRAMES"
_ENV_STALE_SECONDS = "SMC_RELEASE_STALE_SECONDS"

# ---------------------------------------------------------------------------
# Structured failure-reason codes emitted by release gates.
# ---------------------------------------------------------------------------
REASON_STALE_DATA = "STALE_DATA"
REASON_INSUFFICIENT_SYMBOLS = "INSUFFICIENT_SYMBOL_BREADTH"
REASON_INSUFFICIENT_TIMEFRAMES = "INSUFFICIENT_TIMEFRAME_BREADTH"
REASON_INSUFFICIENT_RUNS = "INSUFFICIENT_SUCCESSFUL_RUNS"
REASON_PROVIDER_FAILURE = "PROVIDER_FAILURE"
REASON_SMOKE_FAILURE = "SMOKE_FAILURE"
REASON_MISSING_ARTIFACT = "MISSING_ARTIFACT"


def csv_from_values(values: Iterable[str]) -> str:
    items: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw).strip()
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        items.append(value)
    return ",".join(items)


def parse_csv(raw: str, *, normalize_upper: bool = False) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for token in str(raw).split(","):
        value = token.strip()
        if normalize_upper:
            value = value.upper()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def resolve_git_commit() -> str | None:
    env_sha = str(os.environ.get("GITHUB_SHA", "")).strip()
    if env_sha:
        return env_sha
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    value = str(result.stdout).strip()
    return value or None


def runtime_metadata() -> dict[str, object]:
    return {
        "git_commit": resolve_git_commit(),
        "github_workflow": str(os.environ.get("GITHUB_WORKFLOW", "")).strip() or None,
        "github_run_id": str(os.environ.get("GITHUB_RUN_ID", "")).strip() or None,
        "github_run_number": str(os.environ.get("GITHUB_RUN_NUMBER", "")).strip() or None,
        "github_event_name": str(os.environ.get("GITHUB_EVENT_NAME", "")).strip() or None,
        "github_ref": str(os.environ.get("GITHUB_REF", "")).strip() or None,
        "github_ref_name": str(os.environ.get("GITHUB_REF_NAME", "")).strip() or None,
    }


# ---------------------------------------------------------------------------
# Config-driven policy resolution
# ---------------------------------------------------------------------------

def resolve_release_policy(
    *,
    symbols: str | None = None,
    timeframes: str | None = None,
    stale_after_seconds: int | None = None,
) -> dict[str, Any]:
    """Resolve the effective release policy by merging explicit values > env vars > defaults."""
    # Symbols: explicit arg > env > default
    if symbols:
        resolved_symbols = parse_csv(symbols, normalize_upper=True)
    else:
        env_sym = os.environ.get(_ENV_SYMBOLS, "").strip()
        resolved_symbols = parse_csv(env_sym, normalize_upper=True) if env_sym else list(RELEASE_REFERENCE_SYMBOLS)

    # Timeframes: explicit arg > env > default
    if timeframes:
        resolved_timeframes = parse_csv(timeframes, normalize_upper=False)
    else:
        env_tf = os.environ.get(_ENV_TIMEFRAMES, "").strip()
        resolved_timeframes = parse_csv(env_tf, normalize_upper=False) if env_tf else list(RELEASE_REFERENCE_TIMEFRAMES)

    # Stale threshold: explicit arg > env > default
    if stale_after_seconds is not None:
        resolved_stale = int(stale_after_seconds)
    else:
        env_stale = os.environ.get(_ENV_STALE_SECONDS, "").strip()
        resolved_stale = int(env_stale) if env_stale else RELEASE_STALE_AFTER_SECONDS

    return {
        "symbols": resolved_symbols,
        "timeframes": resolved_timeframes,
        "stale_after_seconds": resolved_stale,
    }


# ---------------------------------------------------------------------------
# Failure diagnosis helpers
# ---------------------------------------------------------------------------

def diagnose_gate_failure(report: dict[str, Any]) -> list[dict[str, str]]:
    """Extract structured failure reasons from a release-gate or provider-health report.

    Returns a list of ``{"reason": REASON_*, "detail": "..."}`` dicts so operators
    can immediately see *why* a gate failed without parsing raw failure codes.
    """
    reasons: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(reason: str, detail: str) -> None:
        key = f"{reason}:{detail}"
        if key not in seen:
            seen.add(key)
            reasons.append({"reason": reason, "detail": detail})

    # Scan top-level failures/warnings/degradations.
    for row in _iter_code_rows(report.get("failures")):
        code = str(row.get("code", ""))
        _classify_code(code, row, _add)

    for row in _iter_code_rows(report.get("degradations_detected")):
        code = str(row.get("code", ""))
        _classify_code(code, row, _add)

    # Scan gates list (release-gate reports).
    for gate in _iter_code_rows(report.get("gates")):
        details = gate.get("details")
        if not isinstance(details, dict):
            continue
        for key in ("failures", "warnings", "degradations_detected", "missing_smoke_failures"):
            for row in _iter_code_rows(details.get(key)):
                code = str(row.get("code", ""))
                _classify_code(code, row, _add)

    # Coverage breadth checks.
    ref_symbols = report.get("reference_symbols", [])
    ref_timeframes = report.get("reference_timeframes", [])
    if isinstance(ref_symbols, list) and len(ref_symbols) < EVIDENCE_MIN_SYMBOL_COVERAGE:
        _add(REASON_INSUFFICIENT_SYMBOLS, f"only {len(ref_symbols)} symbol(s), need >= {EVIDENCE_MIN_SYMBOL_COVERAGE}")
    if isinstance(ref_timeframes, list) and len(ref_timeframes) < EVIDENCE_MIN_TIMEFRAME_COVERAGE:
        _add(REASON_INSUFFICIENT_TIMEFRAMES, f"only {len(ref_timeframes)} timeframe(s), need >= {EVIDENCE_MIN_TIMEFRAME_COVERAGE}")

    return reasons


def _iter_code_rows(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _classify_code(code: str, row: dict[str, Any], add_fn: Any) -> None:
    upper = code.upper()
    if not upper:
        return
    if "STALE" in upper:
        detail = code
        symbol = row.get("symbol", "")
        if symbol:
            detail = f"{code} ({symbol})"
        add_fn(REASON_STALE_DATA, detail)
    elif "MISSING_ARTIFACT" in upper:
        add_fn(REASON_MISSING_ARTIFACT, code)
    elif "MISSING_SMOKE" in upper or "SMOKE" in upper:
        detail = code
        symbol = row.get("symbol", "")
        tf = row.get("timeframe", "")
        if symbol and tf:
            detail = f"{code} ({symbol}/{tf})"
        add_fn(REASON_SMOKE_FAILURE, detail)
    elif "MISSING" in upper:
        add_fn(REASON_MISSING_ARTIFACT, code)
    elif "PROVIDER" in upper or "BUNDLE" in upper or "REFRESH" in upper:
        add_fn(REASON_PROVIDER_FAILURE, code)
