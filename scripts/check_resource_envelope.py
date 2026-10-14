"""Check resource envelope for validity and threshold violations.

Validates that ``resource_envelope.json`` exists, contains the expected
fields, and reports any values that exceed the documented warning thresholds
from ``docs/engineering-program/step12_resource_envelope.md``.

Usage (CLI)::

    python scripts/check_resource_envelope.py \\
        --envelope artifacts/smc_microstructure_exports/resource_envelope.json \\
        --output artifacts/ci/envelope_check_report.json

Programmatic::

    from scripts.check_resource_envelope import check_envelope
    result = check_envelope(Path("..."))
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Warning thresholds from step12_resource_envelope.md
# ---------------------------------------------------------------------------

ENVELOPE_WARN_THRESHOLDS: dict[str, float] = {
    "session_minute_rows": 3_000_000,
    "symbol_day_features_mib": 50.0,
    "step_12_elapsed_s": 180.0,
    "pipeline_elapsed_s": 3600.0,
    "universe_symbols": 100,
    "trade_days_covered": 30,
}

ENVELOPE_HARD_LIMITS: dict[str, float] = {
    "session_minute_rows": 5_000_000,
    "symbol_day_features_mib": 200.0,
    "step_12_elapsed_s": 600.0,
    "pipeline_elapsed_s": 6000.0,
    "universe_symbols": 200,
    "trade_days_covered": 60,
}

#: Fields that must be present in a valid envelope.
REQUIRED_FIELDS: frozenset[str] = frozenset({
    "pipeline_elapsed_s",
    "step_12_elapsed_s",
    "symbol_day_features_rows",
    "symbol_day_features_mib",
    "base_snapshot_rows",
    "session_minute_rows",
    "trade_days_covered",
    "universe_symbols",
})


#: Fraction of warning threshold that triggers a drift advisory.
DRIFT_ADVISORY_FRACTION: float = 0.60


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class EnvelopeCheckResult:
    """Result of a resource envelope check."""

    ok: bool = True
    envelope_found: bool = False
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    hard_limit_violations: list[str] = field(default_factory=list)
    drift_advisories: list[str] = field(default_factory=list)
    envelope: dict[str, Any] = field(default_factory=dict)
    checked_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Core check logic
# ---------------------------------------------------------------------------

def check_envelope(envelope_path: Path) -> EnvelopeCheckResult:
    """Validate the resource envelope and check thresholds."""
    result = EnvelopeCheckResult(
        checked_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )

    if not envelope_path.exists():
        result.ok = False
        result.failures.append(f"Envelope file not found: {envelope_path}")
        return result

    try:
        payload = json.loads(envelope_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        result.ok = False
        result.failures.append(f"Envelope file unreadable: {exc}")
        return result

    if not isinstance(payload, dict):
        result.ok = False
        result.failures.append("Envelope root is not a JSON object")
        return result

    result.envelope_found = True
    result.envelope = payload

    # Required field check
    for field_name in REQUIRED_FIELDS:
        if field_name not in payload:
            result.failures.append(f"Missing required envelope field: {field_name}")

    # Threshold checks
    for metric, warn_threshold in ENVELOPE_WARN_THRESHOLDS.items():
        value = payload.get(metric)
        if value is None:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            result.warnings.append(f"{metric} is not numeric: {value!r}")
            continue

        hard_limit = ENVELOPE_HARD_LIMITS.get(metric)
        if hard_limit is not None and numeric >= hard_limit:
            result.hard_limit_violations.append(
                f"{metric}={numeric:.1f} exceeds hard limit {hard_limit:.1f}"
            )
        elif numeric >= warn_threshold:
            result.warnings.append(
                f"{metric}={numeric:.1f} exceeds warning threshold {warn_threshold:.1f}"
            )
        elif numeric >= warn_threshold * DRIFT_ADVISORY_FRACTION:
            result.drift_advisories.append(
                f"{metric}={numeric:.1f} at {numeric / warn_threshold * 100:.0f}% of warning threshold {warn_threshold:.1f}"
            )

    if result.failures or result.hard_limit_violations:
        result.ok = False

    return result


def format_summary_lines(envelope: dict[str, Any]) -> list[str]:
    """Return compact summary lines suitable for GITHUB_STEP_SUMMARY."""
    lines = [
        "### Resource Envelope",
        "",
        "| Metric | Value |",
        "|--------|-------|",
    ]
    display_fields = [
        ("session_minute_rows", "Session minute rows"),
        ("symbol_day_features_rows", "Symbol-day feature rows"),
        ("symbol_day_features_mib", "Symbol-day features MiB"),
        ("base_snapshot_rows", "Base snapshot rows"),
        ("step_12_elapsed_s", "Step 12 elapsed (s)"),
        ("pipeline_elapsed_s", "Pipeline elapsed (s)"),
        ("universe_symbols", "Universe symbols"),
        ("trade_days_covered", "Trade days covered"),
        ("batch_row_threshold", "Batch row threshold"),
        ("runner_label", "Runner label"),
    ]
    for key, label in display_fields:
        value = envelope.get(key)
        if value is not None:
            lines.append(f"| {label} | {value} |")
    return lines


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check resource envelope")
    parser.add_argument(
        "--envelope",
        default="artifacts/smc_microstructure_exports/resource_envelope.json",
        help="Path to the resource envelope JSON file",
    )
    parser.add_argument(
        "--output",
        default="-",
        help="Output path for the check report (- for stdout)",
    )
    parser.add_argument(
        "--fail-on-hard-limit",
        action="store_true",
        default=False,
        help="Exit non-zero when hard limits are exceeded",
    )
    return parser


def _render(report: dict[str, Any], output: str) -> None:
    text = json.dumps(report, indent=2) + "\n"
    if output == "-":
        sys.stdout.write(text)
    else:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(text, Path(output))


def main() -> int:
    # F-V4-A1b: configure root logging so logger.info / logging.* calls actually
    # surface on stdout when this script is invoked from a GitHub Actions workflow.
    # Without this, the pipeline runs silently and runner-side eviction or
    # mid-pipeline errors are impossible to triage. Also flush eagerly so partial
    # logs survive runner shutdown signals. Self-contained imports to avoid
    # disturbing module-level import order.
    import logging as _v4a1b_logging
    import sys as _v4a1b_sys
    import time as _v4a1b_time
    _v4a1b_logging.basicConfig(
        level=_v4a1b_logging.INFO,
        format="%(asctime)sZ %(levelname)s %(name)s %(message)s",
        stream=_v4a1b_sys.stderr,
        force=True,
    )
    _v4a1b_logging.Formatter.converter = _v4a1b_time.gmtime
    try:
        _v4a1b_sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
        _v4a1b_sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass


    args = build_parser().parse_args()
    result = check_envelope(Path(args.envelope))
    report = result.to_dict()
    _render(report, args.output)

    for w in result.warnings:
        logger.warning("Envelope warning: %s", w)
    for v in result.hard_limit_violations:
        logger.warning("Envelope HARD LIMIT: %s", v)
    for d in result.drift_advisories:
        logger.info("Envelope drift advisory: %s", d)

    if args.fail_on_hard_limit and result.hard_limit_violations:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
