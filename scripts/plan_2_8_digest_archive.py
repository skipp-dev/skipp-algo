"""Plan 2.8 digest archive.

Copies a freshly-rendered ``digest.json`` into a rotating archive
directory keyed by ``captured_at`` (ISO date), so future runs can
diff against last week's baseline via ``plan_2_8_digest_compare.py``.

If the digest has no ``captured_at`` field, ``--fallback-date`` (or
today's date) is used. Rotation: when the archive exceeds ``keep``
entries, the oldest files (by filename-sorted order) are deleted.

Pure stdlib. File names: ``YYYY-MM-DD.json``. Same-date writes
overwrite in place.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import shutil
import sys
from pathlib import Path
from typing import Any


def _derive_date(digest_path: Path, fallback: str | None) -> str:
    try:
        data = json.loads(digest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = {}
    cap = data.get("captured_at") if isinstance(data, dict) else None
    if isinstance(cap, str) and cap:
        # Accept ISO with or without time; take the YYYY-MM-DD prefix.
        head = cap[:10]
        try:
            _dt.date.fromisoformat(head)
            return head
        except ValueError:
            pass
    if fallback:
        try:
            _dt.date.fromisoformat(fallback)
            return fallback
        except ValueError:
            pass
    return _dt.date.today().isoformat()


def archive(
    digest_path: Path,
    archive_dir: Path,
    *,
    fallback_date: str | None = None,
    keep: int = 26,
) -> dict[str, Any]:
    archive_dir.mkdir(parents=True, exist_ok=True)
    date_key = _derive_date(digest_path, fallback_date)
    target = archive_dir / f"{date_key}.json"
    shutil.copy2(digest_path, target)

    files = sorted(archive_dir.glob("*.json"))
    removed: list[str] = []
    if keep >= 0 and len(files) > keep:
        # Oldest-first by sorted filename; remove the leading excess.
        excess = len(files) - keep
        for p in files[:excess]:
            try:
                p.unlink()
                removed.append(p.name)
            except OSError:
                continue
    return {
        "schema_version": 1,
        "archive_dir":    str(archive_dir),
        "target":         target.name,
        "kept":           max(0, min(keep, len(sorted(archive_dir.glob("*.json"))))),
        "removed":        removed,
    }


def latest_two(archive_dir: Path) -> list[Path]:
    files = sorted(archive_dir.glob("*.json"))
    return files[-2:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Archive a Plan 2.8 digest.json snapshot "
                    "and rotate by count.",
    )
    parser.add_argument("--digest", type=Path, required=True)
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--fallback-date", default=None)
    parser.add_argument("--keep", type=int, default=26)
    parser.add_argument("--emit-latest-two", action="store_true",
                        help="Also print the two most-recent archive paths "
                             "on stdout, newline-separated.")
    args = parser.parse_args(argv)

    if not args.digest.exists():
        print(f"ERROR: digest not found: {args.digest}", file=sys.stderr)
        return 1

    report = archive(
        args.digest, args.archive_dir,
        fallback_date=args.fallback_date, keep=args.keep,
    )
    print(json.dumps(report, indent=2))
    if args.emit_latest_two:
        for p in latest_two(args.archive_dir):
            print(str(p))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
