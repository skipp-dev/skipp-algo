from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON payload must be an object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _relative_report_path(release_manifest_path: Path, validation_report_path: Path) -> str:
    return os.path.relpath(validation_report_path, release_manifest_path.parent).replace("\\", "/")


def verify_post_release_validation(
    release_manifest_path: Path,
    validation_report_path: Path,
) -> dict[str, Any]:
    manifest = _read_json(release_manifest_path)
    report = _read_json(validation_report_path)

    library = manifest.get("library")
    if not isinstance(library, dict):
        raise RuntimeError("Library release manifest is missing the library object")

    failures: list[str] = []
    publish_status = str(library.get("publishStatus") or "").strip()
    expected_version = library.get("expectedVersion")
    published_version = library.get("publishedVersion")

    if publish_status != "published":
        failures.append(f"library.publishStatus must be 'published' (got {publish_status or 'missing'})")

    if expected_version is not None and published_version != expected_version:
        failures.append(
            f"library.publishedVersion must match expectedVersion ({published_version!r} != {expected_version!r})"
        )

    if str(report.get("execution_mode") or "").strip() != "readonly":
        failures.append("post-release TradingView validation must run in readonly mode")
    if report.get("auth_reused_ok") is not True:
        failures.append("post-release TradingView validation must reuse authenticated state")
    if report.get("auth_ok") is not True:
        failures.append("post-release TradingView validation must pass auth_ok")
    if report.get("overall_preflight_ok") is not True:
        failures.append("post-release TradingView validation must pass overall_preflight_ok")

    raw_targets = report.get("targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        failures.append("post-release TradingView validation must contain at least one target result")
        targets: list[dict[str, Any]] = []
    else:
        targets = [target for target in raw_targets if isinstance(target, dict)]
        for target in targets:
            if target.get("overall_preflight_ok") is True:
                continue
            label = str(target.get("scriptName") or target.get("file") or "unknown_target")
            target_error = str(target.get("error") or "overall_preflight_ok=false")
            failures.append(f"target {label} failed post-release validation: {target_error}")

    if failures:
        raise RuntimeError("; ".join(failures))

    relative_report_path = _relative_report_path(release_manifest_path, validation_report_path)
    manifest_updated = False
    if manifest.get("lastPreflightReport") != relative_report_path:
        manifest["lastPreflightReport"] = relative_report_path
        _write_json(release_manifest_path, manifest)
        manifest_updated = True

    return {
        "ok": True,
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
    path.write_text(rendered + "\n", encoding="utf-8")


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