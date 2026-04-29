"""Plan 2.8 status-ledger validator.

Reports the count of valid/invalid JSONL records and the reason
for each invalid one. A valid record is:

- parseable JSON object (``dict``)
- has ``captured_at`` (non-empty string, ISO-parseable)
- has ``status`` (string in ``VALID_STATUSES``)

Designed for CI checks; exit code ``1`` with ``--fail-on-invalid``
when any invalid record is present.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

VALID_STATUSES = frozenset({"green", "amber", "red", "unknown"})


def _parse_ts(raw: Any) -> bool:
    if not isinstance(raw, str) or not raw:
        return False
    try:
        _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def validate(lines: list[str]) -> dict[str, Any]:
    valid = 0
    invalid: list[dict[str, Any]] = []
    for lineno, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            rec = json.loads(stripped)
        except json.JSONDecodeError as exc:
            invalid.append({
                "lineno": lineno, "reason": f"json_error: {exc.msg}",
            })
            continue
        if not isinstance(rec, dict):
            invalid.append({
                "lineno": lineno, "reason": "not_object",
            })
            continue
        if not _parse_ts(rec.get("captured_at")):
            invalid.append({
                "lineno": lineno, "reason": "bad_captured_at",
            })
            continue
        status = rec.get("status")
        if not isinstance(status, str) \
                or status.strip().lower() not in VALID_STATUSES:
            invalid.append({
                "lineno": lineno, "reason": "bad_status",
            })
            continue
        valid += 1
    return {
        "schema_version": 1,
        "counts": {"valid": valid, "invalid": len(invalid)},
        "invalid": invalid,
    }


def render_markdown(report: dict[str, Any]) -> str:
    c = report["counts"]
    lines = [
        "# Plan 2.8 status ledger validation",
        "",
        f"- valid:   {c['valid']}",
        f"- invalid: {c['invalid']}",
        "",
    ]
    if not report["invalid"]:
        lines.append("_All records valid._")
        return "\n".join(lines) + "\n"
    lines.append("| line | reason |")
    lines.append("| --- | --- |")
    for row in report["invalid"]:
        lines.append(f"| {row['lineno']} | {row['reason']} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a Plan 2.8 status ledger (JSONL).",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-invalid", action="store_true")
    args = parser.parse_args(argv)

    if not args.ledger.exists():
        print(f"ERROR: ledger not found: {args.ledger}", file=sys.stderr)
        return 1

    lines = args.ledger.read_text(encoding="utf-8").splitlines()
    report = validate(lines)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_invalid and report["counts"]["invalid"] > 0:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
