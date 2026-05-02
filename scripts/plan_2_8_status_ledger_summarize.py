"""Plan 2.8 status ledger summariser.

Reads a JSONL ledger produced by
``scripts/plan_2_8_status_ledger.py`` and emits a compact summary:

  - counts per status (``green``, ``amber``, ``red``, ``unknown``)
  - total observations
  - ``pct_green`` (0..100)
  - ``current_streak``: length of the trailing run of identical
    statuses + the status itself
  - ``last_flip``:   captured_at of the most recent boundary
    between different statuses (or ``null`` if only one unique
    status is seen)

Tolerant of malformed/blank lines. Pure stdlib.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

VALID = ("green", "amber", "red", "unknown")


def _iter_records(ledger: Path) -> list[dict[str, Any]]:
    if not ledger.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in ledger.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def summarise(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {s: 0 for s in VALID}
    total = 0
    for rec in records:
        status = rec.get("status")
        if not isinstance(status, str):
            continue
        key = status.lower()
        if key not in counts:
            key = "unknown"
        counts[key] += 1
        total += 1

    pct_green = (100.0 * counts["green"] / total) if total else 0.0

    current_status: str | None = None
    current_streak = 0
    last_flip: str | None = None
    if records:
        last = records[-1]
        last_status = last.get("status")
        current_status = last_status if isinstance(last_status, str) else None
        # Walk backwards while the status matches the most recent one.
        for rec in reversed(records):
            status = rec.get("status")
            if status == current_status:
                current_streak += 1
            else:
                captured = rec.get("captured_at")
                if isinstance(captured, str):
                    last_flip = captured
                break

    return {
        "schema_version": 1,
        "counts":         counts,
        "total":          total,
        "pct_green":      round(pct_green, 2),
        "current_status": current_status,
        "current_streak": current_streak,
        "last_flip":      last_flip,
    }


def render_markdown(report: dict[str, Any]) -> str:
    c = report["counts"]
    lines = [
        "# Plan 2.8 status ledger summary",
        "",
        f"- total:           {report['total']}",
        f"- green / amber / red / unknown: "
        f"{c['green']} / {c['amber']} / {c['red']} / {c['unknown']}",
        f"- % green:         {report['pct_green']}",
        f"- current status:  {report['current_status'] or '-'}",
        f"- current streak:  {report['current_streak']}",
        f"- last flip:       {report['last_flip'] or '-'}",
    ]
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
        description="Summarise a Plan 2.8 status ledger.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.ledger.exists():
        print(f"ERROR: ledger not found: {args.ledger}", file=sys.stderr)
        return 1

    records = _iter_records(args.ledger)
    report = summarise(records)

    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
