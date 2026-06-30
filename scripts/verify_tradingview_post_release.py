from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

_POST_RELEASE_MANIFEST_STALE_AFTER_SECONDS = 2 * 60 * 60

POST_RELEASE_FAILURE_CODES = (
    "PUBLISH_STATUS_NOT_PUBLISHED",
    "VERSION_MISMATCH",
    "MANIFEST_STALE",
    "MANIFEST_MISSING_TIMESTAMP",
    "READONLY_MODE_REQUIRED",
    "AUTH_NOT_REUSED",
    "AUTH_FAILED",
    "PREFLIGHT_FAILED",
    "TARGET_FAILED",
    "TARGET_PREFLIGHT_FAILED",
    "NO_TARGETS",
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON payload must be an object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(json.dumps(payload, indent=2) + "\n", path)


def _relative_report_path(release_manifest_path: Path, validation_report_path: Path) -> str:
    return os.path.relpath(validation_report_path, release_manifest_path.parent).replace("\\", "/")


def _parse_timestamp(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return None


def _manifest_generated_timestamp(manifest: dict[str, Any]) -> tuple[float | None, str | None]:
    candidates: list[tuple[str, Any]] = [
        ("generated_at", manifest.get("generated_at")),
        ("generatedAt", manifest.get("generatedAt")),
    ]
    library = manifest.get("library")
    if isinstance(library, dict):
        candidates.extend(
            [
                ("library.generated_at", library.get("generated_at")),
                ("library.generatedAt", library.get("generatedAt")),
            ]
        )

    for field_name, raw_value in candidates:
        parsed = _parse_timestamp(raw_value)
        if parsed is not None:
            return parsed, field_name
    return None, None


def _iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), tz=UTC).isoformat()


def verify_post_release_validation(
    release_manifest_path: Path,
    validation_report_path: Path,
) -> dict[str, Any]:
    validation_timestamp = float(time.time())
    manifest = _read_json(release_manifest_path)
    report = _read_json(validation_report_path)

    library = manifest.get("library")
    if not isinstance(library, dict):
        raise RuntimeError("Library release manifest is missing the library object")

    failures: list[str] = []
    failure_codes: list[str] = []
    publish_status = str(library.get("publishStatus") or "").strip()
    expected_version = library.get("expectedVersion")
    published_version = library.get("publishedVersion")
    manifest_generated_at, manifest_generated_field = _manifest_generated_timestamp(manifest)
    manifest_age_seconds = None

    if publish_status != "published":
        failures.append(f"library.publishStatus must be 'published' (got {publish_status or 'missing'})")
        failure_codes.append("PUBLISH_STATUS_NOT_PUBLISHED")

    if expected_version is not None and published_version != expected_version:
        failures.append(
            f"library.publishedVersion must match expectedVersion ({published_version!r} != {expected_version!r})"
        )
        failure_codes.append("VERSION_MISMATCH")

    if manifest_generated_at is None:
        failures.append("library release manifest must contain generatedAt/generated_at for staleness validation")
        failure_codes.append("MANIFEST_MISSING_TIMESTAMP")
    else:
        manifest_age_seconds = max(0.0, validation_timestamp - float(manifest_generated_at))
        if manifest_age_seconds > float(_POST_RELEASE_MANIFEST_STALE_AFTER_SECONDS):
            failures.append(
                "library release manifest is stale for post-release validation "
                f"({int(manifest_age_seconds)}s > {_POST_RELEASE_MANIFEST_STALE_AFTER_SECONDS}s)"
            )
            failure_codes.append("MANIFEST_STALE")

    if str(report.get("execution_mode") or "").strip() != "readonly":
        failures.append("post-release TradingView validation must run in readonly mode")
        failure_codes.append("READONLY_MODE_REQUIRED")
    if report.get("auth_reused_ok") is not True:
        failures.append("post-release TradingView validation must reuse authenticated state")
        failure_codes.append("AUTH_NOT_REUSED")
    if report.get("auth_ok") is not True:
        failures.append("post-release TradingView validation must pass auth_ok")
        failure_codes.append("AUTH_FAILED")
    if report.get("overall_preflight_ok") is not True:
        failures.append("post-release TradingView validation must pass overall_preflight_ok")
        failure_codes.append("PREFLIGHT_FAILED")

    raw_targets = report.get("targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        failures.append("post-release TradingView validation must contain at least one target result")
        failure_codes.append("NO_TARGETS")
        targets: list[dict[str, Any]] = []
    else:
        targets = [target for target in raw_targets if isinstance(target, dict)]
        for target in targets:
            if target.get("overall_preflight_ok") is True:
                continue
            label = str(target.get("scriptName") or target.get("file") or "unknown_target")
            target_error = str(target.get("error") or "overall_preflight_ok=false")
            failures.append(f"target {label} failed post-release validation: {target_error}")
            # WS1-FT-04 stage split: a target that loaded on the chart but whose
            # Settings/Inputs surface could not be opened is a UI-interaction
            # (surface) flake, not semantic drift. Emit the soft
            # TARGET_PREFLIGHT_FAILED so the release gate downgrades it instead of
            # hard-blocking. Reserve the blocking TARGET_FAILED for real
            # load/compile/runtime failures: the script never became visible on
            # the chart, or its input contract drifted after the surface opened.
            # Regression: smc-library-refresh run 628 (2026-06-30,
            # "Could not open script menu for settings: SMC Decision Board").
            surface_only = (
                target.get("script_found_on_chart_ok") is True
                and target.get("settings_open_ok") is not True
            )
            code = "TARGET_PREFLIGHT_FAILED" if surface_only else "TARGET_FAILED"
            if code not in failure_codes:
                failure_codes.append(code)

    if failures:
        exc = RuntimeError("; ".join(failures))
        exc.failure_codes = failure_codes  # type: ignore[attr-defined]
        raise exc

    relative_report_path = _relative_report_path(release_manifest_path, validation_report_path)
    manifest_updated = False
    if manifest.get("lastPreflightReport") != relative_report_path:
        manifest["lastPreflightReport"] = relative_report_path
        _write_json(release_manifest_path, manifest)
        manifest_updated = True

    return {
        "ok": True,
        "validation_timestamp": validation_timestamp,
        "validation_timestamp_iso": _iso_utc(validation_timestamp),
        "manifest_generated_at": manifest_generated_at,
        "manifest_generated_at_iso": _iso_utc(manifest_generated_at) if manifest_generated_at is not None else None,
        "manifest_generated_field": manifest_generated_field,
        "manifest_age_seconds": manifest_age_seconds,
        "staleness_check": {
            "ok": manifest_age_seconds is not None and manifest_age_seconds <= float(_POST_RELEASE_MANIFEST_STALE_AFTER_SECONDS),
            "stale_after_seconds": _POST_RELEASE_MANIFEST_STALE_AFTER_SECONDS,
            "manifest_generated_field": manifest_generated_field,
            "manifest_age_seconds": manifest_age_seconds,
        },
        "release_manifest_path": release_manifest_path.as_posix(),
        "validation_report_path": validation_report_path.as_posix(),
        "last_preflight_report": relative_report_path,
        "validated_target_count": len(targets),
        "manifest_updated": manifest_updated,
    }


def _render(report: dict[str, Any], output: str) -> None:
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if output == "-":
        print(rendered)
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(rendered + "\n", path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify TradingView post-release readonly validation output.")
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
    report = verify_post_release_validation(args.release_manifest, args.validation_report)
    _render(report, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
