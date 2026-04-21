"""Prune stale entries from the F2 contextual_calibration.archive.

Each auto-revert (``scripts/f2_revert_contextual_weights.py``) and manual
promotion (``scripts/f2_promote_contextual_weights.py``) writes a
timestamped copy of the previous artifact into
``<spec-dir>/contextual_calibration.archive/``. That directory grows
monotonically. The daily workflow uploads it as part of the F2 bundle;
without retention it bloats every release over time.

This helper deletes archive JSONs whose embedded timestamp is older than
``--max-age-days`` (default 90). Non-archive files are ignored. Files
without a parseable ``YYYY-MM-DDTHH-MM-SSZ`` suffix are kept.

Writes a structured record to
``artifacts/ci/f2/cleanup_archives_journal.jsonl`` with the list of
deleted paths + retention policy, for audit.

Exit codes
----------
  0 = success (even if no files were deleted)
  1 = I/O or config error
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CLEANUP_SCHEMA_VERSION = 1
DEFAULT_MAX_AGE_DAYS = 90
JOURNAL_DEFAULT = Path("artifacts/ci/f2/cleanup_archives_journal.jsonl")

# Matches the timestamp suffix produced by the revert/promote helpers.
# Example: treatment_calibration.2026-01-15T10-00-00Z.json
_TS_RE = re.compile(r"\.(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z)\.json$")


def _parse_ts(name: str) -> datetime | None:
    m = _TS_RE.search(name)
    if m is None:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%dT%H-%M-%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def _append_journal(journal_path: Path, record: dict[str, Any]) -> None:
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", delete=False, dir=str(journal_path.parent), encoding="utf-8"
    ) as tmp:
        if journal_path.exists():
            tmp.write(journal_path.read_text(encoding="utf-8"))
        tmp.write(line)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = tmp.name
    os.replace(tmp_path, journal_path)


def cleanup_archives(
    *,
    archive_dir: Path,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    now: datetime | None = None,
    dry_run: bool = False,
    journal_path: Path | None = None,
) -> dict[str, Any]:
    """Delete archive entries older than ``max_age_days``.

    Returns a manifest describing the run (schema_version=1).
    """
    if max_age_days < 0:
        raise ValueError("max_age_days must be >= 0")
    archive_dir = Path(archive_dir)
    now = now or datetime.now(tz=timezone.utc)
    cutoff = now.timestamp() - (max_age_days * 86400)

    deleted: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    skipped: list[str] = []

    if archive_dir.exists():
        for entry in sorted(archive_dir.iterdir()):
            if not entry.is_file() or not entry.name.endswith(".json"):
                continue
            ts = _parse_ts(entry.name)
            if ts is None:
                skipped.append(entry.name)
                continue
            if ts.timestamp() < cutoff:
                if not dry_run:
                    entry.unlink()
                deleted.append({"name": entry.name, "ts": ts.isoformat()})
            else:
                kept.append({"name": entry.name, "ts": ts.isoformat()})

    manifest = {
        "schema_version": CLEANUP_SCHEMA_VERSION,
        "archive_dir": str(archive_dir),
        "max_age_days": max_age_days,
        "now": now.isoformat(),
        "dry_run": bool(dry_run),
        "deleted": deleted,
        "kept": kept,
        "skipped_unparseable": skipped,
    }

    if journal_path is not None and not dry_run:
        _append_journal(Path(journal_path), manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prune stale entries from the F2 contextual_calibration.archive.",
    )
    parser.add_argument("--archive-dir", type=Path, required=True,
                        help="Path to the contextual_calibration.archive directory.")
    parser.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS,
                        help=f"Retention in days (default: {DEFAULT_MAX_AGE_DAYS}).")
    parser.add_argument("--dry-run", action="store_true",
                        help="List what would be deleted without unlinking.")
    parser.add_argument("--journal", type=Path, default=JOURNAL_DEFAULT,
                        help="Path to the cleanup journal JSONL.")
    parser.add_argument("--output", type=Path, default=None,
                        help="Optional path to write the manifest JSON.")
    parser.add_argument("--quiet", action="store_true",
                        help="Print only a one-line summary.")
    args = parser.parse_args(argv)

    try:
        manifest = cleanup_archives(
            archive_dir=args.archive_dir,
            max_age_days=args.max_age_days,
            dry_run=args.dry_run,
            journal_path=args.journal,
        )
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    n_del = len(manifest["deleted"])
    n_keep = len(manifest["kept"])
    n_skip = len(manifest["skipped_unparseable"])
    suffix = " (dry-run)" if args.dry_run else ""
    if args.quiet:
        print(f"cleanup: deleted={n_del} kept={n_keep} skipped={n_skip}{suffix}")
    else:
        print(f"# F2 archive cleanup{suffix}")
        print(f"archive_dir: {manifest['archive_dir']}")
        print(f"max_age_days: {manifest['max_age_days']}")
        print(f"deleted: {n_del}")
        print(f"kept: {n_keep}")
        print(f"skipped_unparseable: {n_skip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
