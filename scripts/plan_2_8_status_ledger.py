"""Plan 2.8 status ledger — append a status observation.

Appends a single JSONL record describing the current rollup status
to a ledger file. The ledger accumulates weekly observations so that
long-term trends can be summarised.

Record shape::

    {"captured_at": "<iso8601>", "status": "green"|"amber"|"red"|"unknown",
     "run_url": "<optional string>"}

Input may be a status snapshot JSON (``{"status": ...}``) or a bare
rollout-health JSON (``{"rollup": ...}``). The resolved ``status``
is normalised to lowercase; unknown/missing values become
``"unknown"``.

Appends are atomic-ish: we write a whole new trailing line with a
single ``Path.open("a", encoding="utf-8")`` call. Creates parent
directories if needed. Pure stdlib.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

VALID_STATUSES: frozenset[str] = frozenset({"green", "amber", "red", "unknown"})


def resolve_status(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "unknown"
    status = payload.get("status")
    if isinstance(status, str) and status:
        low = status.lower()
        return low if low in VALID_STATUSES else "unknown"
    rollup = payload.get("rollup")
    if isinstance(rollup, str) and rollup:
        low = rollup.lower()
        return low if low in VALID_STATUSES else "unknown"
    return "unknown"


def build_record(
    payload: Any,
    *,
    run_url: str | None = None,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    now_ = now or _dt.datetime.now(tz=_dt.UTC)
    record: dict[str, Any] = {
        "captured_at": now_.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "status":      resolve_status(payload),
    }
    if run_url:
        record["run_url"] = run_url
    return record


def append(ledger: Path, record: dict[str, Any]) -> None:
    ledger.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True) + "\n"
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(line)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Append a Plan 2.8 status observation to a JSONL ledger.",
    )
    parser.add_argument("--input", type=Path, required=True,
                        help="status-snapshot or rollout-health JSON")
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--run-url", default=None)
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        return 1
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: input is not valid JSON: {exc}", file=sys.stderr)
        return 1

    record = build_record(payload, run_url=args.run_url)
    append(args.ledger, record)
    print(json.dumps(record, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
