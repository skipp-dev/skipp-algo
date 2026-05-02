"""Plan 2.8 latest-flip extractor.

Scans the status ledger for the most recent status transition
(from -> to) and reports its captured_at timestamp. Returns
``{"found": false}`` when there is no transition in the
ledger.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

VALID_STATUSES = frozenset({"green", "amber", "red", "unknown"})


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


def compute(records: list[dict[str, Any]]) -> dict[str, Any]:
    last_status: str | None = None
    _last_ts: str | None = None
    latest: dict[str, Any] | None = None
    for rec in records:
        raw = rec.get("status")
        if not isinstance(raw, str):
            continue
        s = raw.strip().lower()
        if s not in VALID_STATUSES:
            continue
        ts = rec.get("captured_at") if isinstance(
            rec.get("captured_at"), str,
        ) else None
        if last_status is not None and s != last_status:
            latest = {
                "from": last_status,
                "to":   s,
                "at":   ts,
            }
        last_status = s
        _last_ts = ts
    if latest is None:
        return {"schema_version": 1, "found": False}
    return {
        "schema_version": 1,
        "found":          True,
        "from":           latest["from"],
        "to":             latest["to"],
        "at":             latest["at"],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Plan 2.8 latest flip", ""]
    if not report.get("found"):
        lines.append("_(no flip in ledger)_")
    else:
        lines.append(f"- from: `{report['from']}`")
        lines.append(f"- to: `{report['to']}`")
        lines.append(f"- at: `{report['at']}`")
    lines.append("")
    return "\n".join(lines) + "\n"

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
        description="Report the most-recent status flip in the ledger.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.ledger.exists():
        print(f"ERROR: ledger not found: {args.ledger}", file=sys.stderr)
        return 1

    report = compute(_iter_records(args.ledger))
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
