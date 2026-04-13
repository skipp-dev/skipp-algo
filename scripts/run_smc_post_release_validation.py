from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.verify_tradingview_post_release import verify_post_release_validation


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
) -> dict[str, Any]:
    checked_at = float(time.time())
    base_report: dict[str, Any] = {
        "report_kind": "post_release_validation",
        "checked_at": checked_at,
        "checked_at_iso": _iso_utc(checked_at),
        "release_manifest_path": release_manifest_path.as_posix(),
        "validation_report_path": validation_report_path.as_posix(),
    }

    try:
        validation = verify_post_release_validation(release_manifest_path, validation_report_path)
    except Exception as exc:
        return {
            **base_report,
            "overall_status": "fail",
            "failures": [
                {
                    "code": "POST_RELEASE_VALIDATION_FAILED",
                    "message": str(exc),
                }
            ],
        }

    return {
        **base_report,
        "overall_status": "ok",
        "validation": validation,
        "validated_target_count": int(validation.get("validated_target_count", 0) or 0),
        "failures": [],
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
    parser.add_argument("--output", default="-", help="Output path for JSON report, or '-' for stdout.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = run_post_release_validation(args.release_manifest, args.validation_report)
    _render(report, args.output)
    return 0 if report.get("overall_status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())