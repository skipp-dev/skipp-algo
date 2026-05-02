"""Rotate / trim a Plan 2.8 history JSONL.

The daily archiver (``scripts/plan_2_8_history_archive.py``) appends
one snapshot per day. Over months, this file grows without bound —
harmless today but noisy in artifact bundles and slow to parse for
the weekly digest. This helper rotates the file to a size-bounded
form using any combination of:

  * ``--max-age-days N``: drop snapshots older than N days from the
    latest captured_at.
  * ``--max-rows N``: keep at most the most-recent N rows.

The original file is moved to ``<path>.bak`` before the trimmed
version is written (atomic via ``os.replace``), so a botched rotation
can be undone manually. Corrupt lines are preserved by default — set
``--drop-corrupt`` to remove them.

Pure stdlib. No mutation of the caller's rollup artifacts.

Exit codes
----------
  0 = file rotated (or no-op when nothing to trim)
  1 = unreadable / unwritable file
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


def _parse_iso(ts: str) -> _dt.datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return _dt.datetime.fromisoformat(ts)


def _split_lines(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Return ``(snapshots, corrupt_lines)``. Preserves original order."""
    snapshots: list[dict[str, Any]] = []
    corrupt: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            snapshots.append(json.loads(line))
        except json.JSONDecodeError:
            corrupt.append(raw)
    return snapshots, corrupt


def rotate(
    *,
    history_path: Path,
    max_age_days: int | None = None,
    max_rows: int | None = None,
    drop_corrupt: bool = False,
) -> dict[str, Any]:
    """Trim ``history_path`` in-place; return a summary dict.

    Returns ``{before, after, dropped_age, dropped_cap, corrupt_kept,
    corrupt_dropped, backup}``.
    """
    if not history_path.exists():
        raise ValueError(f"history not found: {history_path}")
    if max_age_days is not None and max_age_days < 0:
        raise ValueError("max_age_days must be >= 0")
    if max_rows is not None and max_rows < 0:
        raise ValueError("max_rows must be >= 0")

    snapshots, corrupt = _split_lines(history_path)
    before = len(snapshots) + len(corrupt)
    kept = list(snapshots)
    dropped_age = 0
    dropped_cap = 0

    if max_age_days is not None and kept:
        # Sort by captured_at ascending; pick latest timestamp as anchor.
        def _ts(s: dict[str, Any]) -> str:
            return s.get("captured_at") or ""
        kept.sort(key=_ts)
        try:
            anchor = _parse_iso(kept[-1]["captured_at"])
        except (KeyError, ValueError):
            anchor = _dt.datetime.now(_dt.UTC)
        cutoff = anchor - _dt.timedelta(days=max_age_days)
        new_kept: list[dict[str, Any]] = []
        for s in kept:
            try:
                ts = _parse_iso(s["captured_at"])
            except (KeyError, ValueError):
                # Keep snapshots with unparseable timestamps: they're not
                # what the age gate is about.
                new_kept.append(s)
                continue
            if ts >= cutoff:
                new_kept.append(s)
            else:
                dropped_age += 1
        kept = new_kept

    if max_rows is not None and len(kept) > max_rows:
        dropped_cap = len(kept) - max_rows
        kept = kept[-max_rows:]  # keep newest

    corrupt_kept = [] if drop_corrupt else corrupt
    corrupt_dropped = len(corrupt) if drop_corrupt else 0
    after = len(kept) + len(corrupt_kept)

    # No-op guard: if nothing changed, skip the rewrite + backup.
    if after == before and corrupt_dropped == 0:
        return {
            "before": before,
            "after": after,
            "dropped_age": 0,
            "dropped_cap": 0,
            "corrupt_kept": len(corrupt_kept),
            "corrupt_dropped": corrupt_dropped,
            "backup": None,
        }

    # Write atomically: write to <path>.tmp, then replace; save <path>.bak.
    backup_path = history_path.with_suffix(history_path.suffix + ".bak")
    # Preserve original as .bak (overwrite any previous backup).
    os.replace(history_path, backup_path)
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", delete=False,
            dir=str(history_path.parent),
            suffix=".tmp",
        ) as fh:
            # Keep corrupt lines at the top so they are visible next rotation.
            for line in corrupt_kept:
                fh.write(line.rstrip() + "\n")
            for snap in kept:
                fh.write(json.dumps(snap) + "\n")
            tmp_name = fh.name
        os.replace(tmp_name, history_path)
    except OSError:
        # Rollback: restore the original from backup before re-raising.
        if backup_path.exists():
            os.replace(backup_path, history_path)
        raise

    return {
        "before": before,
        "after": after,
        "dropped_age": dropped_age,
        "dropped_cap": dropped_cap,
        "corrupt_kept": len(corrupt_kept),
        "corrupt_dropped": corrupt_dropped,
        "backup": str(backup_path),
    }

# F-V6-A1.1 (2026-05-02): bootstrap root logging so the logger.info(...)
# progress messages this entry point emits actually surface in CI logs
# (default WARNING-only handler would drop them). Extends F-V5-A1-2 / #2012
# from the priority entry-point set to plan_2_8 aggregators + showcase.
try:
    from scripts._logging_init import init_cli_logging
except ImportError:  # script-style invocation: `python scripts/X.py`
    import sys as _v6a11_sys
    from pathlib import Path as _v6a11_Path

    _v6a11_sys.path.insert(0, str(_v6a11_Path(__file__).resolve().parents[1]))
    from scripts._logging_init import init_cli_logging  # type: ignore[no-redef]




def main(argv: list[str] | None = None) -> int:
    init_cli_logging()  # F-V6-A1.1 (2026-05-02)
    parser = argparse.ArgumentParser(description="Rotate / trim a Plan 2.8 history JSONL.")
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--max-age-days", type=int, default=None)
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--drop-corrupt", action="store_true")
    args = parser.parse_args(argv)

    if args.max_age_days is None and args.max_rows is None and not args.drop_corrupt:
        print("ERROR: at least one of --max-age-days / --max-rows / "
              "--drop-corrupt is required", file=sys.stderr)
        return 1

    try:
        summary = rotate(
            history_path=args.history,
            max_age_days=args.max_age_days,
            max_rows=args.max_rows,
            drop_corrupt=args.drop_corrupt,
        )
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
