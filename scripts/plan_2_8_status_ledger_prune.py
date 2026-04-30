"""Plan 2.8 status ledger pruner.

Keeps only the last ``--keep`` records of a JSONL ledger, writing
atomically via ``tempfile`` + ``os.replace``. Blank and malformed
lines are dropped silently. Pure stdlib.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
import contextlib


def prune(lines: list[str], *, keep: int) -> list[str]:
    if keep < 0:
        raise ValueError("keep must be non-negative")
    valid: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            rec = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        valid.append(stripped)
    if keep == 0:
        return []
    return valid[-keep:]


def _rewrite(ledger: Path, kept: list[str]) -> None:
    ledger.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".ledger-", suffix=".jsonl", dir=str(ledger.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for line in kept:
                fh.write(line + "\n")
        os.replace(tmp_path, ledger)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prune a Plan 2.8 status ledger to its last N records.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--keep", type=int, default=104,
                        help="number of trailing records to retain")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if not args.ledger.exists():
        print(f"ERROR: ledger not found: {args.ledger}", file=sys.stderr)
        return 1
    if args.keep < 0:
        print("ERROR: --keep must be non-negative", file=sys.stderr)
        return 1

    lines = args.ledger.read_text(encoding="utf-8").splitlines()
    kept = prune(lines, keep=args.keep)
    _rewrite(args.ledger, kept)
    if not args.quiet:
        before = len(lines)
        print(json.dumps({
            "before": before,
            "after":  len(kept),
            "keep":   args.keep,
        }))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
