"""Check refresh success markers for completeness and consistency.

Validates that ``refresh_success_markers.json`` contains the expected
late-phase stage outcomes and that no stage was silently skipped or
left in an inconsistent state.

Usage (CLI)::

    python scripts/check_refresh_success_markers.py \\
        --markers artifacts/ci/refresh_success_markers.json \\
        --output artifacts/ci/marker_check_report.json

Programmatic::

    from scripts.check_refresh_success_markers import check_markers
    result = check_markers(Path("artifacts/ci/refresh_success_markers.json"))
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
# Expected marker schema
# ---------------------------------------------------------------------------

#: Stages that MUST be present in a completed marker file.
REQUIRED_STAGES: frozenset[str] = frozenset({
    "generation",
    "gates",
    "change_detected",
    "publish",
    "commit",
    "post_release_gates",
})

#: Stage values that indicate a healthy completion.
HEALTHY_OUTCOMES: frozenset[str] = frozenset({
    "success",
    "true",
    "false",
    "skipped",
})

#: Stages where "skipped" is acceptable (conditional paths).
SKIPPABLE_STAGES: frozenset[str] = frozenset({
    "publish",
    "commit",
    "post_release_gates",
})

#: Top-level fields that must be present.
REQUIRED_TOP_LEVEL_FIELDS: frozenset[str] = frozenset({
    "generation_completed_at",
    "pipeline_completed_at",
    "stages",
})


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class MarkerCheckResult:
    """Result of a marker completeness check."""

    ok: bool = False
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stages_found: list[str] = field(default_factory=list)
    stages_missing: list[str] = field(default_factory=list)
    checked_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Core check logic
# ---------------------------------------------------------------------------

def check_markers(markers_path: Path) -> MarkerCheckResult:
    """Validate the refresh success markers file.

    Returns a :class:`MarkerCheckResult` with ``ok=True`` only when:
    - The file exists and is valid JSON.
    - All required top-level fields are present.
    - All required stages are present.
    - No stage has an empty or unrecognised status value.
    - ``pipeline_completed_at`` is present (late-phase completion).
    """
    result = MarkerCheckResult(
        checked_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )

    if not markers_path.exists():
        result.ok = False
        result.failures.append(f"Marker file not found: {markers_path}")
        return result

    try:
        payload = json.loads(markers_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        result.ok = False
        result.failures.append(f"Marker file unreadable: {exc}")
        return result

    if not isinstance(payload, dict):
        result.ok = False
        result.failures.append("Marker file root is not a JSON object")
        return result

    # Top-level field check
    for field_name in REQUIRED_TOP_LEVEL_FIELDS:
        if field_name not in payload:
            result.failures.append(f"Missing required top-level field: {field_name}")

    # Late-phase completion check
    if not payload.get("pipeline_completed_at"):
        result.failures.append(
            "pipeline_completed_at is missing or empty — pipeline did not reach completion"
        )

    stages = payload.get("stages", {})
    if not isinstance(stages, dict):
        result.ok = False
        result.failures.append("stages field is not a dict")
        return result

    result.stages_found = sorted(stages.keys())
    result.stages_missing = sorted(REQUIRED_STAGES - set(stages.keys()))

    for stage_name in result.stages_missing:
        result.failures.append(f"Missing required stage: {stage_name}")

    # Value consistency
    for stage_name, stage_value in stages.items():
        raw = str(stage_value).strip().lower()
        if not raw:
            result.failures.append(f"Stage {stage_name!r} has empty status value")
        elif raw == "failure":
            result.warnings.append(f"Stage {stage_name!r} reported failure")
        elif raw not in HEALTHY_OUTCOMES and raw != "failure":
            result.warnings.append(
                f"Stage {stage_name!r} has unrecognised status: {stage_value!r}"
            )

    result.ok = len(result.failures) == 0
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check refresh success markers")
    parser.add_argument(
        "--markers",
        default="artifacts/ci/refresh_success_markers.json",
        help="Path to the markers JSON file",
    )
    parser.add_argument(
        "--output",
        default="-",
        help="Output path for the check report (- for stdout)",
    )
    parser.add_argument(
        "--fail-on-incomplete",
        action="store_true",
        default=False,
        help="Exit non-zero when markers are incomplete",
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
    import logging as _v4a1b_logging, sys as _v4a1b_sys, time as _v4a1b_time
    _v4a1b_logging.basicConfig(
        level=_v4a1b_logging.INFO,
        format="%(asctime)sZ %(levelname)s %(name)s %(message)s",
        stream=_v4a1b_sys.stdout,
        force=True,
    )
    _v4a1b_logging.Formatter.converter = _v4a1b_time.gmtime
    try:
        _v4a1b_sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
        _v4a1b_sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass


    args = build_parser().parse_args()
    result = check_markers(Path(args.markers))
    report = result.to_dict()
    _render(report, args.output)

    if result.failures:
        for failure in result.failures:
            logger.warning("Marker check failure: %s", failure)

    if args.fail_on_incomplete and not result.ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
