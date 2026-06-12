"""Merge two Plan 2.8 history JSONLs into one de-duped log.

Use case: an operator recovered a partial history file from an older
artifact and wants to reconcile it with the live running log without
losing any snapshots. Key is ``(captured_at, scoring_root)`` \u2014 the
same key ``plan_2_8_history_archive.py`` uses for idempotent append.

Pure stdlib. Atomic write via tempfile + os.replace. Non-destructive:
inputs are never modified; ``--dry-run`` only reports what would
happen.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _parse_iso(ts: str) -> _dt.datetime | None:
    try:
        return _dt.datetime.fromisoformat(
            ts[:-1] + "+00:00" if ts.endswith("Z") else ts,
        )
    except (ValueError, TypeError):
        return None


def _read(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def merge(
    base: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> dict[str, Any]:
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []

    def _ingest(records: list[dict[str, Any]]) -> dict[str, int]:
        added = malformed = dups = 0
        for rec in records:
            ca = rec.get("captured_at")
            sr = rec.get("scoring_root")
            if not isinstance(ca, str) or not isinstance(sr, str):
                malformed += 1
                continue
            key = (ca, sr)
            if key in seen:
                dups += 1
                continue
            seen[key] = rec
            order.append(key)
            added += 1
        return {"added": added, "dups": dups, "malformed": malformed}

    base_stats = _ingest(base)
    incoming_stats = _ingest(incoming)

    def _sort_key(k: tuple[str, str]) -> tuple[_dt.datetime, str]:
        ts = _parse_iso(k[0]) or _dt.datetime.min.replace(tzinfo=_dt.UTC)
        return (ts, k[1])

    order.sort(key=_sort_key)
    merged = [seen[k] for k in order]
    return {
        "schema_version": 1,
        "merged": merged,
        "counts": {
            "base_records":       len(base),
            "incoming_records":   len(incoming),
            "base_kept":          base_stats["added"],
            "base_malformed":     base_stats["malformed"],
            "incoming_new":       incoming_stats["added"],
            "incoming_duplicate": incoming_stats["dups"],
            "incoming_malformed": incoming_stats["malformed"],
            "final":              len(merged),
        },
    }


def _write(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=path.parent, prefix=".history.", suffix=".jsonl",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise

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
    parser = argparse.ArgumentParser(
        description="Merge two Plan 2.8 history JSONL files.",
    )
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--incoming", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    base = _read(args.base)
    incoming = _read(args.incoming)
    result = merge(base, incoming)
    if not args.dry_run:
        _write(args.output, result["merged"])
    if not args.quiet:
        print(json.dumps({
            "dry_run": args.dry_run,
            "output":  str(args.output),
            "counts":  result["counts"],
        }, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
