from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from smc_integration.batch import load_symbols_from_source
from smc_integration.provider_health import (
    provider_health_exit_code,
    run_provider_health_check,
    write_provider_health_report,
)
from smc_integration.release_policy import runtime_metadata


def _parse_csv(raw: str) -> list[str]:
    out: list[str] = []
    for token in str(raw).split(","):
        value = token.strip()
        if value:
            out.append(value)
    return out


def _resolve_symbols(explicit_symbols: list[str] | None) -> list[str]:
    if explicit_symbols:
        return explicit_symbols
    try:
        rows = load_symbols_from_source(source="auto")
    except Exception:
        rows = []
    if rows:
        return [str(rows[0]).strip().upper()]
    return ["IBG"]


def _resolve_output(raw: str) -> Path | None:
    if raw == "-":
        return None
    return Path(raw)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run SMC provider/artifact/smoke health checks for CI gates.")
    parser.add_argument("--symbols", default="", help="Comma-separated symbols. Empty uses one auto-discovered symbol.")
    parser.add_argument("--timeframes", default="15m", help="Comma-separated timeframes.")
    parser.add_argument(
        "--stale-after-seconds",
        type=int,
        default=None,
        help="Optional staleness threshold. If omitted, timestamps are observed but not hard-gated by age.",
    )
    parser.add_argument(
        "--fail-on-warn",
        action="store_true",
        help="Return a non-zero exit code for warn state in addition to fail.",
    )
    parser.add_argument(
        "--output",
        default="-",
        help="Output path for JSON report, or '-' for stdout.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    symbols = _resolve_symbols(_parse_csv(args.symbols))
    timeframes = _parse_csv(args.timeframes) or ["15m"]

    report = run_provider_health_check(
        symbols=symbols,
        timeframes=timeframes,
        stale_after_seconds=args.stale_after_seconds,
    )
    exit_code = provider_health_exit_code(report, fail_on_warn=bool(args.fail_on_warn))
    report["report_kind"] = "ci_health"
    report["runner"] = {
        "script": "scripts/run_smc_ci_health_checks.py",
        "mode": "ci_health",
        "fail_on_warn": bool(args.fail_on_warn),
        "exit_code": int(exit_code),
    }
    report["runtime_metadata"] = runtime_metadata()
    write_provider_health_report(report, _resolve_output(args.output))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
