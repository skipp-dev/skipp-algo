"""Plan 2.8 longest status run.

Reports, per status (green/amber/red/unknown), the longest
consecutive run observed in the ledger along with its
start/end captured_at timestamps. Statuses that never appear
get ``{"length": 0, "start_at": None, "end_at": None}``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

VALID_STATUSES = ("green", "amber", "red", "unknown")


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
    best: dict[str, dict[str, Any]] = {
        s: {"length": 0, "start_at": None, "end_at": None}
        for s in VALID_STATUSES
    }
    cur_status: str | None = None
    cur_len = 0
    cur_start: str | None = None
    cur_end: str | None = None

    def _commit() -> None:
        if cur_status is None:
            return
        if cur_len > best[cur_status]["length"]:
            best[cur_status] = {
                "length":   cur_len,
                "start_at": cur_start,
                "end_at":   cur_end,
            }

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
        if s != cur_status:
            _commit()
            cur_status = s
            cur_len = 1
            cur_start = ts
            cur_end = ts
        else:
            cur_len += 1
            cur_end = ts
    _commit()

    return {
        "schema_version": 1,
        "per_status":     best,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 longest status run",
        "",
        "| status | length | start_at | end_at |",
        "|---|---:|---|---|",
    ]
    for s in VALID_STATUSES:
        e = report["per_status"][s]
        start = e["start_at"] if e["start_at"] is not None else "-"
        end = e["end_at"] if e["end_at"] is not None else "-"
        lines.append(
            f"| `{s}` | {e['length']} | `{start}` | `{end}` |",
        )
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
        description="Report longest consecutive run per status.",
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
