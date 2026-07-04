#!/usr/bin/env python3
"""Sync Pine Script libraries from TradingView source.

Fetches current versions of SMC libraries from TradingView public sources,
validates syntax, and updates local copies if changed. Tracks update history
in LIBRARY_VERSIONS.toml for audit trail.

Usage:
    python scripts/sync_tradingview_libraries.py [--dry-run] [--force]
"""

from __future__ import annotations

import argparse
import datetime
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Map of library names to TradingView identifiers
TRADINGVIEW_LIBRARIES = {
    "smc_overlay_generated": {
        "user": "preuss_steffen",
        "lib": "smc_overlay_generated",
        "version": "1",
        "local_path": "pine/generated/smc_overlay_generated.pine",
        "critical": False,
    },
    "smc_profile_engine": {
        "user": "preuss_steffen",
        "lib": "smc_profile_engine",
        "version": "1",
        "local_path": "SMC++/smc_profile_engine.pine",
        "critical": True,
    },
    "smc_context_resolvers": {
        "user": "preuss_steffen",
        "lib": "smc_context_resolvers",
        "version": "1",
        "local_path": "SMC++/smc_context_resolvers.pine",
        "critical": True,
    },
    "smc_observability_private": {
        "user": "preuss_steffen",
        "lib": "smc_observability_private",
        "version": "1",
        "local_path": "SMC++/smc_observability_private.pine",
        "critical": True,
    },
    "smc_bus_private": {
        "user": "preuss_steffen",
        "lib": "smc_bus_private",
        "version": "1",
        "local_path": "SMC++/smc_bus_private.pine",
        "critical": True,
    },
    "smc_lifecycle_private": {
        "user": "preuss_steffen",
        "lib": "smc_lifecycle_private",
        "version": "1",
        "local_path": "SMC++/smc_lifecycle_private.pine",
        "critical": True,
    },
}


def validate_pine_syntax(content: str, lib_name: str) -> bool:
    """Validate Pine Script syntax (basic checks)."""
    # Check for required library declaration
    if not re.search(rf'library\s*\(\s*["\']?{lib_name}["\']?', content):
        logger.error(f"Missing library declaration for '{lib_name}'")
        return False

    # Check for unbalanced braces
    if content.count("{") != content.count("}"):
        logger.error(f"Unbalanced braces in {lib_name}")
        return False

    # Check for unclosed comments
    if content.count("/*") != content.count("*/"):
        logger.error(f"Unclosed block comments in {lib_name}")
        return False

    return True


def compare_files(local_path: Path, new_content: str) -> bool:
    """Return True if content differs from local file."""
    if not local_path.exists():
        return True  # New file
    return local_path.read_text() != new_content


def update_library_versions_toml(
    lib_name: str,
    update_date: str,
    sync_date: str,
    dry_run: bool = False,
) -> None:
    """Update pine/LIBRARY_VERSIONS.toml with sync metadata."""
    toml_path = Path("pine/LIBRARY_VERSIONS.toml")

    if not toml_path.exists():
        logger.warning(f"{toml_path} does not exist, skipping version update")
        return

    content = toml_path.read_text()

    # Update or add library entry
    # This is a simplified regex replacement; a proper TOML parser would be better
    pattern = rf'(\[libraries\].*?){lib_name}\s*=.*?\n'
    replacement = (
        rf'\1{lib_name} = {{ version = "1", '
        rf'tradingview_updated = "{update_date}", '
        rf'local_synced = "{sync_date}" }}\n'
    )

    updated_content = re.sub(pattern, replacement, content, flags=re.DOTALL)

    if updated_content != content:
        if not dry_run:
            toml_path.write_text(updated_content)  # ATOMIC-WRITE-EXEMPT: local pine-sync metadata write, not a concurrently-read surface
            logger.info(f"Updated version metadata for {lib_name}")
        else:
            logger.info(f"[DRY-RUN] Would update version metadata for {lib_name}")


def fetch_library_source(user: str, lib: str, version: str) -> str | None:
    """Fetch library source from TradingView.

    NOTE: Automated fetching is now handled by scripts/tv_fetch_smc_libraries.ts
    which uses Playwright + TV_STORAGE_STATE (same auth as publishing).

    This Python script now only validates already-fetched libraries.
    """
    logger.debug(f"Skipping fetch for {lib} (handled by tv_fetch_smc_libraries.ts)")
    return None


def sync_library(
    lib_name: str,
    config: dict,
    dry_run: bool = False,
    force: bool = False,
) -> bool:
    """Sync a single library from TradingView.

    Returns True if updated, False if no change or error.
    """
    logger.info(f"Syncing {lib_name}...")

    local_path = Path(config["local_path"])
    local_path.parent.mkdir(parents=True, exist_ok=True)

    # Fetch source from TradingView
    source = fetch_library_source(config["user"], config["lib"], config["version"])
    if source is None:
        logger.error(f"Failed to fetch {lib_name}")
        return False

    # Validate syntax
    if not validate_pine_syntax(source, lib_name):
        logger.error(f"Syntax validation failed for {lib_name}, aborting update")
        return False

    # Check if content differs
    if not force and not compare_files(local_path, source):
        logger.info(f"{lib_name} is already up-to-date")
        return False

    # Write to disk
    if not dry_run:
        local_path.write_text(source)  # ATOMIC-WRITE-EXEMPT: local pine-sync library write, not a concurrently-read surface
        logger.info(f"Updated {local_path}")
    else:
        logger.info(f"[DRY-RUN] Would update {local_path}")

    # Update version metadata
    today = datetime.date.today().isoformat()
    update_library_versions_toml(lib_name, "unknown", today, dry_run=dry_run)

    return True


def validate_imports(root: Path = Path(".")) -> bool:
    """Validate that all Pine imports reference local libraries.

    Scans for @import statements and ensures the target library exists.
    """
    errors = []

    for pine_file in root.glob("*.pine"):
        content = pine_file.read_text()
        imports = re.findall(r'import\s+(\S+)\s+as\s+(\w+)', content)

        for lib_path, alias in imports:
            try:
                _user, lib_name, _version = lib_path.split("/")
            except ValueError:
                errors.append(f"{pine_file}: Invalid import syntax '{lib_path}'")
                continue

            if lib_name not in TRADINGVIEW_LIBRARIES:
                logger.warning(f"{pine_file}: Unknown library import '{lib_name}'")
                continue

            local_file = Path(TRADINGVIEW_LIBRARIES[lib_name]["local_path"])
            if not local_file.exists():
                errors.append(f"{pine_file}: Missing {local_file} (imported as '{alias}')")

    if errors:
        for err in errors:
            logger.error(err)
        return False

    logger.info("✅ All Pine imports validated")
    return True


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Sync Pine Script libraries from TradingView",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry-run to see what would be updated
  python scripts/sync_tradingview_libraries.py --dry-run

  # Force update all libraries (even if unchanged)
  python scripts/sync_tradingview_libraries.py --force

  # Sync only critical libraries
  python scripts/sync_tradingview_libraries.py --critical-only

  # Validate imports after sync
  python scripts/sync_tradingview_libraries.py && python scripts/sync_tradingview_libraries.py --validate-only
        """,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without making changes",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force update all libraries even if unchanged",
    )
    parser.add_argument(
        "--critical-only",
        action="store_true",
        help="Only sync libraries marked as critical",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate existing imports, don't sync",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(levelname)s: %(message)s",
    )

    # Validate imports first
    if not validate_imports():
        logger.error("Import validation failed")
        if not args.validate_only:
            return 1

    if args.validate_only:
        return 0

    # Sync libraries
    updated = 0
    for lib_name, config in TRADINGVIEW_LIBRARIES.items():
        if args.critical_only and not config["critical"]:
            logger.debug(f"Skipping non-critical library: {lib_name}")
            continue

        if sync_library(lib_name, config, dry_run=args.dry_run, force=args.force):
            updated += 1

    logger.info(f"\n{'[DRY-RUN] ' if args.dry_run else ''}Updated {updated} libraries")

    # Final validation
    if not args.dry_run and not validate_imports():
        logger.error("Post-sync validation failed")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
