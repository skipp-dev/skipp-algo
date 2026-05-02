"""Plan 2.8 history prune.

Reads ``plan_2_8_history.jsonl`` line-by-line and writes a pruned
copy keeping only records whose ``captured_at`` is within the last
``--keep-days`` days (default 365). Malformed JSON lines are dropped
with a ``malformed`` counter. Records missing ``captured_at`` or
with an unparseable value are preserved by default (set
``--drop-undated`` to remove them).

Atomic rewrite via tempfile + ``os.replace``. Pure stdlib.
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


def _parse_ts(s: Any) -> _dt.datetime | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        return _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def prune_lines(
    lines: list[str],
    *,
    keep_days: int,
    now: _dt.datetime | None = None,
    drop_undated: bool = False,
) -> dict[str, Any]:
    now_ = now or _dt.datetime.now(tz=_dt.UTC)
    floor = now_ - _dt.timedelta(days=keep_days)
    kept: list[str] = []
    malformed = 0
    dropped_stale = 0
    dropped_undated = 0
    kept_count = 0
    for raw in lines:
        raw = raw.rstrip("\n")
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(obj, dict):
            malformed += 1
            continue
        ts = _parse_ts(obj.get("captured_at"))
        if ts is None:
            if drop_undated:
                dropped_undated += 1
                continue
            kept.append(raw)
            kept_count += 1
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=_dt.UTC)
        if ts < floor:
            dropped_stale += 1
            continue
        kept.append(raw)
        kept_count += 1
    return {
        "schema_version": 1,
        "keep_days":       keep_days,
        "counts": {
            "kept":            kept_count,
            "dropped_stale":   dropped_stale,
            "dropped_undated": dropped_undated,
            "malformed":       malformed,
        },
        "kept_lines": kept,
    }


def atomic_write(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", delete=False, dir=str(path.parent), encoding="utf-8",
        suffix=".tmp",
    ) as tmp:
        for line in lines:
            tmp.write(line + "\n")
        tmp_path = tmp.name
    os.replace(tmp_path, path)

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
        description="Prune a Plan 2.8 history JSONL to a recent window.",
    )
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--keep-days", type=int, default=365)
    parser.add_argument("--drop-undated", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.history.exists():
        print(f"ERROR: history not found: {args.history}", file=sys.stderr)
        return 1

    lines = args.history.read_text(encoding="utf-8").splitlines()
    report = prune_lines(
        lines,
        keep_days=args.keep_days,
        drop_undated=args.drop_undated,
    )
    target = args.output or args.history
    if not args.dry_run:
        atomic_write(target, report["kept_lines"])
    if not args.quiet:
        print(json.dumps({
            "schema_version": report["schema_version"],
            "keep_days":       report["keep_days"],
            "counts":          report["counts"],
            "path":            str(target),
            "dry_run":         bool(args.dry_run),
        }, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
