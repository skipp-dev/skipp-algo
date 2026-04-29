"""Plan 2.8 status-ledger JSONL \u2192 CSV export.

Mirrors the shape of ``scripts/plan_2_8_history_export.py`` \u2014
emits ``captured_at,status,run_url`` by default. Pure stdlib.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

DEFAULT_FIELDS: tuple[str, ...] = ("captured_at", "status", "run_url")


def _iter_records(ledger: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not ledger.exists():
        return out
    for line in ledger.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            rec = json.loads(s)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def render_csv(
    records: list[dict[str, Any]], *,
    fields: tuple[str, ...] = DEFAULT_FIELDS,
) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(fields), extrasaction="ignore")
    writer.writeheader()
    for rec in records:
        row = {f: rec.get(f, "") for f in fields}
        # normalise None -> ""
        for k, v in list(row.items()):
            if v is None:
                row[k] = ""
        writer.writerow(row)
    return buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export a Plan 2.8 status ledger (JSONL) to CSV.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--fields", default=",".join(DEFAULT_FIELDS),
        help="comma-separated list of fields (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    if not args.ledger.exists():
        print(f"ERROR: ledger not found: {args.ledger}", file=sys.stderr)
        return 1

    fields = tuple(f.strip() for f in args.fields.split(",") if f.strip())
    if not fields:
        print("ERROR: --fields must name at least one field",
              file=sys.stderr)
        return 1

    records = _iter_records(args.ledger)
    body = render_csv(records, fields=fields)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    else:
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
