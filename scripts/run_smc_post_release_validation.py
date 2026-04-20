from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.verify_tradingview_post_release import (
    POST_RELEASE_FAILURE_CODES,
    verify_post_release_validation,
)

# Hero State Contract block keys (PR 4 of 2026-04-20 deep-review).
# These keys are emitted on every report so downstream consumers can read a
# stable shape even before the readonly TradingView validation begins to
# emit hero-specific signals. Values are populated from the existing
# validation payload when available; otherwise they remain ``None`` (with
# ``hero_state.ready == False``) rather than being absent.
HERO_STATE_FIELDS: tuple[str, ...] = (
    "market_mode",
    "bias",
    "trust",
    "setup_quality",
    "why_now",
    "risk",
    "action",
)


def _build_hero_state_block(
    *,
    overall_status: str,
    failure_codes: list[str],
    validation: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return the Hero State block for a post-release validation report.

    The block is intentionally read-only: it summarises the *visible* product
    state implied by the validation result without introducing a new hard
    validation. Empty/None values mean "the readonly validation does not yet
    expose this signal" rather than "the signal failed".
    """
    payload = (validation or {}).get("hero_state") if isinstance(validation, dict) else None
    fields: dict[str, Any] = {key: None for key in HERO_STATE_FIELDS}
    if isinstance(payload, dict):
        for key in HERO_STATE_FIELDS:
            value = payload.get(key)
            if isinstance(value, str) and value:
                fields[key] = value

    ready = overall_status == "ok" and any(v is not None for v in fields.values())
    return {
        "ready": bool(ready),
        "source": "validation_report" if isinstance(payload, dict) else "absent",
        "fields": fields,
        "failure_codes": list(failure_codes),
    }


def _iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), tz=UTC).isoformat()


def _render(report: dict[str, Any], output: str) -> None:
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if output == "-":
        print(rendered)
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered + "\n", encoding="utf-8")


def run_post_release_validation(
    release_manifest_path: Path,
    validation_report_path: Path,
    *,
    ci_mode: bool = False,
) -> dict[str, Any]:
    checked_at = float(time.time())
    release_manifest_present = release_manifest_path.exists()
    validation_report_present = validation_report_path.exists()
    base_report: dict[str, Any] = {
        "report_kind": "post_release_validation",
        "ci_mode": bool(ci_mode),
        "checked_at": checked_at,
        "checked_at_iso": _iso_utc(checked_at),
        "release_manifest_path": release_manifest_path.as_posix(),
        "validation_report_path": validation_report_path.as_posix(),
        "release_manifest_present": release_manifest_present,
        "validation_report_present": validation_report_present,
    }

    try:
        validation = verify_post_release_validation(release_manifest_path, validation_report_path)
    except Exception as exc:
        failure_codes = getattr(exc, "failure_codes", None)
        if not failure_codes:
            failure_codes = ["POST_RELEASE_VALIDATION_FAILED"]
        failures = [
            {
                "code": code,
                "exception_type": type(exc).__name__,
                "message": str(exc),
            }
            for code in failure_codes
        ]
        return {
            **base_report,
            "overall_status": "fail",
            "validation": {
                "ok": False,
                "validation_timestamp": checked_at,
                "validation_timestamp_iso": _iso_utc(checked_at),
                "release_manifest_present": release_manifest_present,
                "validation_report_present": validation_report_present,
            },
            "validated_target_count": 0,
            "failures": failures,
            "hero_state": _build_hero_state_block(
                overall_status="fail",
                failure_codes=list(failure_codes),
                validation=None,
            ),
        }

    return {
        **base_report,
        "overall_status": "ok",
        "validation": validation,
        "validation_timestamp": validation.get("validation_timestamp", checked_at),
        "validation_timestamp_iso": validation.get("validation_timestamp_iso", _iso_utc(checked_at)),
        "validated_target_count": int(validation.get("validated_target_count", 0) or 0),
        "failures": [],
        "hero_state": _build_hero_state_block(
            overall_status="ok",
            failure_codes=[],
            validation=validation,
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run and normalize SMC post-release validation.")
    parser.add_argument(
        "--release-manifest",
        type=Path,
        default=Path("artifacts/tradingview/library_release_manifest.json"),
        help="Path to the checked-in TradingView library release manifest.",
    )
    parser.add_argument(
        "--validation-report",
        type=Path,
        default=Path("artifacts/tradingview/tv_post_release_validation.json"),
        help="Path to the readonly TradingView post-release validation report.",
    )
    parser.add_argument(
        "--ci-mode",
        action="store_true",
        help="Emit explicit machine-readable normalization fields for CI consumers.",
    )
    parser.add_argument("--output", default="-", help="Output path for JSON report, or '-' for stdout.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = run_post_release_validation(args.release_manifest, args.validation_report, ci_mode=bool(args.ci_mode))
    _render(report, args.output)
    return 0 if report.get("overall_status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())