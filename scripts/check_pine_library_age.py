#!/usr/bin/env python3
"""Check Pine library age against SLA.

Validates that all Pine libraries are within acceptable age threshold.
Used by smc-fast-pr-gates.yml to fail CI if libraries fall behind SLA.

Exit codes:
  0: All libraries within SLA
  1: One or more libraries exceed SLA or metadata missing
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def parse_toml_library_entries(toml_path: Path) -> dict[str, dict[str, str]]:
    """Parse pine/LIBRARY_VERSIONS.toml for library metadata.

    Returns dict mapping library_name -> {version, tradingview_updated, local_synced}
    """
    import re

    if not toml_path.exists():
        logger.error(f"Missing {toml_path}")
        return {}

    content = toml_path.read_text()
    entries = {}

    # Simple regex-based TOML parsing for [libraries] section
    # Format: lib_name = { version = "1", tradingview_updated = "2026-06-09", local_synced = "2026-06-10" }
    pattern = r'(\w+)\s*=\s*\{\s*version\s*=\s*"([^"]+)"\s*,\s*tradingview_updated\s*=\s*"([^"]+)"\s*,\s*local_synced\s*=\s*"([^"]+)"\s*\}'

    for match in re.finditer(pattern, content):
        lib_name, version, tv_updated, local_synced = match.groups()
        entries[lib_name] = {
            "version": version,
            "tradingview_updated": tv_updated,
            "local_synced": local_synced,
        }

    return entries


def check_library_age(
    library_versions_toml: Path,
    max_days: int = 7,
) -> bool:
    """Check if all libraries are within SLA age.

    Returns True if all libraries pass, False if any exceed threshold.
    """
    entries = parse_toml_library_entries(library_versions_toml)

    if not entries:
        logger.error("No library entries found in LIBRARY_VERSIONS.toml")
        return False

    today = datetime.now(timezone.utc).date()
    threshold_date = today - timedelta(days=max_days)
    failed = False

    for lib_name, metadata in sorted(entries.items()):
        local_synced_str = metadata.get("local_synced", "unknown")

        if local_synced_str == "unknown":
            logger.error(f"[{lib_name}] ❌ Missing local_synced date")
            failed = True
            continue

        try:
            local_synced = datetime.strptime(local_synced_str, "%Y-%m-%d").date()
        except ValueError:
            logger.error(f"[{lib_name}] ❌ Invalid date format: {local_synced_str}")
            failed = True
            continue

        age_days = (today - local_synced).days

        if age_days > max_days:
            logger.error(
                f"[{lib_name}] ❌ BREACHED SLA: {age_days} days old (max {max_days}). "
                f"Last synced: {local_synced_str}"
            )
            failed = True
        else:
            logger.info(f"[{lib_name}] ✓ {age_days} days old (SLA: {max_days} days)")

    return not failed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check Pine library age against SLA threshold",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check libraries with default 7-day SLA
  python scripts/check_pine_library_age.py

  # Check with custom threshold
  python scripts/check_pine_library_age.py --max-days 14

  # Set log level
  python scripts/check_pine_library_age.py --log-level DEBUG
        """,
    )
    parser.add_argument(
        "--library-versions",
        type=Path,
        default=Path("pine/LIBRARY_VERSIONS.toml"),
        help="Path to LIBRARY_VERSIONS.toml (default: pine/LIBRARY_VERSIONS.toml)",
    )
    parser.add_argument(
        "--max-days",
        type=int,
        default=7,
        help="Maximum library age in days (default: 7)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    parser.add_argument(
        "--fail-on-breach",
        action="store_true",
        default=True,
        help="Fail (exit 1) if any library exceeds SLA (default: true)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(levelname)s: %(message)s",
    )

    logger.info(f"Checking Pine library age (SLA: {args.max_days} days)\n")

    passed = check_library_age(
        library_versions_toml=args.library_versions,
        max_days=args.max_days,
    )

    if passed:
        logger.info("\n✓ All Pine libraries within SLA")
        return 0
    else:
        logger.error("\n❌ One or more Pine libraries exceed SLA")
        return 1 if args.fail_on_breach else 0


if __name__ == "__main__":
    sys.exit(main())
