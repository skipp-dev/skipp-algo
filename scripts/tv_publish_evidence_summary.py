"""Generate a consolidated TradingView publish evidence summary.

Scans automation/tradingview/reports/ for the latest publish and preflight
reports per library, then writes a single JSON summary with staleness flags.

Usage:
    python scripts/tv_publish_evidence_summary.py [--out PATH]
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT / "automation" / "tradingview" / "reports"
SCREENSHOTS_DIR = REPORTS_DIR / "screenshots"

LIBRARIES = [
    "smc_core_types",
    "smc_draw",
    "smc_bus_private",
    "smc_lifecycle_private",
    "smc_utils",
    "smc_observability_private",
    "smc_profile_engine",
    "smc_context_resolvers",
    "smc_micro_profiles_generated",
]

PUBLISH_EVIDENCE_STALE_DAYS = 7
PREFLIGHT_EVIDENCE_STALE_DAYS = 14


def _find_latest_report(pattern: str) -> tuple[Path | None, dict[str, Any] | None]:
    """Find the most recent JSON report matching a glob pattern."""
    from scripts.smc_artifact_resolver import latest_by_filename_iso
    path = latest_by_filename_iso(REPORTS_DIR.glob(pattern))
    if path is None:
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return path, data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return path, None


def _find_latest_screenshot(library: str) -> Path | None:
    """Find the most recent screenshot for a library."""
    if not SCREENSHOTS_DIR.exists():
        return None
    from scripts.smc_artifact_resolver import latest_by_filename_iso
    return latest_by_filename_iso(
        p for p in SCREENSHOTS_DIR.iterdir()
        if p.suffix == ".png" and (library.replace("_", "-") in p.name.lower()
                                   or library in p.name.lower())
    )


def _is_stale(path: Path | None, max_days: int) -> bool:
    """Check if a file is older than max_days."""
    if path is None:
        return True
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return (datetime.now(UTC) - mtime) > timedelta(days=max_days)


def _extract_publish_status(report: dict[str, Any] | None) -> dict[str, Any]:
    """Extract publish status fields from a report."""
    if report is None:
        return {"publish_ok": None, "compile_ok": None}
    return {
        "publish_ok": report.get("publish_ok") or report.get("publishOk"),
        "compile_ok": report.get("compile_ok") or report.get("compileOk"),
    }


def generate_summary() -> dict[str, Any]:
    """Generate a consolidated evidence summary."""
    now = datetime.now(UTC)
    library_evidence: list[dict[str, Any]] = []

    for lib in LIBRARIES:
        # Find publish report
        lib_slug = lib.replace("_", "-")
        publish_path, publish_data = _find_latest_report(f"publish-{lib_slug}*")
        if publish_path is None:
            publish_path, publish_data = _find_latest_report(f"publish-*{lib_slug}*")

        # Find screenshot
        screenshot = _find_latest_screenshot(lib)

        # Build entry
        publish_status = _extract_publish_status(publish_data)
        publish_stale = _is_stale(publish_path, PUBLISH_EVIDENCE_STALE_DAYS)

        entry: dict[str, Any] = {
            "library": lib,
            "import_path": f"preuss_steffen/{lib}/1",
            "publish_report": str(publish_path.relative_to(ROOT)) if publish_path else None,
            "publish_ok": publish_status["publish_ok"],
            "compile_ok": publish_status["compile_ok"],
            "publish_evidence_stale": publish_stale,
            "screenshot": str(screenshot.relative_to(ROOT)) if screenshot else None,
        }
        library_evidence.append(entry)

    # Find latest mainline preflight
    preflight_path, preflight_data = _find_latest_report("preflight-*.json")
    preflight_stale = _is_stale(preflight_path, PREFLIGHT_EVIDENCE_STALE_DAYS)
    preflight_status: dict[str, Any] = {}
    if preflight_data:
        preflight_status = {
            "auth_ok": preflight_data.get("auth_ok"),
            "compile_green": preflight_data.get("compile_green"),
            "binding_green": preflight_data.get("binding_green"),
            "runtime_green": preflight_data.get("runtime_green"),
            "overall_preflight_ok": preflight_data.get("overall_preflight_ok"),
        }

    # Overall verdict
    all_published = all(e.get("publish_ok") is True for e in library_evidence)
    no_stale = not any(e["publish_evidence_stale"] for e in library_evidence)
    preflight_green = preflight_status.get("overall_preflight_ok") is True

    return {
        "generated_at": now.isoformat(),
        "evidence_summary": {
            "total_libraries": len(LIBRARIES),
            "all_published": all_published,
            "no_stale_evidence": no_stale,
            "preflight_green": preflight_green,
            "preflight_stale": preflight_stale,
            "overall_operational_status": "GREEN" if (all_published and preflight_green and not preflight_stale) else "YELLOW" if all_published else "RED",
        },
        "preflight": {
            "report": str(preflight_path.relative_to(ROOT)) if preflight_path else None,
            "stale": preflight_stale,
            **preflight_status,
        },
        "libraries": library_evidence,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="TradingView publish evidence summary")
    parser.add_argument("--out", type=Path, default=None, help="Output JSON path")
    args = parser.parse_args()

    summary = generate_summary()

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(json.dumps(summary, indent=2) + "\n", args.out)
        print(f"Evidence summary written to {args.out}")
    else:
        print(json.dumps(summary, indent=2))

    # Print human-readable verdict
    status = summary["evidence_summary"]["overall_operational_status"]
    total = summary["evidence_summary"]["total_libraries"]
    published = sum(1 for lib in summary["libraries"] if lib.get("publish_ok") is True)
    stale = sum(1 for lib in summary["libraries"] if lib["publish_evidence_stale"])
    print(f"\n{'─' * 60}")
    print(f"Status: {status}")
    print(f"Libraries: {published}/{total} publish-verified, {stale} with stale evidence")
    print(f"Preflight: {'green' if summary['preflight'].get('overall_preflight_ok') else 'not green'}"
          f" ({'stale' if summary['preflight']['stale'] else 'fresh'})")
    print(f"{'─' * 60}")


if __name__ == "__main__":
    main()
