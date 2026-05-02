"""Plan 2.8 CHANGELOG slice.

Scrapes ``CHANGELOG.md`` for entries of the form::

    ### Added (YYYY-MM-DD) - <title>

Emits the most recent N entries within an optional lookback window
as either markdown (default) or JSON. Intended for status sidebars
that want "what shipped in the last 14 days" at a glance.

Pure stdlib, read-only.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

HEADING_RE = re.compile(
    r"^### (Added|Changed|Fixed|Removed) \((\d{4}-\d{2}-\d{2})\) [-\u2014] (.+)$"
)


def parse_changelog(text: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    buf: list[str] = []
    for raw in text.splitlines():
        m = HEADING_RE.match(raw.strip())
        if m:
            if current is not None:
                current["body"] = "\n".join(buf).strip()
                entries.append(current)
            current = {
                "kind":  m.group(1),
                "date":  m.group(2),
                "title": m.group(3).strip(),
            }
            buf = []
        elif raw.startswith("### ") or raw.startswith("## "):
            if current is not None:
                current["body"] = "\n".join(buf).strip()
                entries.append(current)
                current = None
                buf = []
        elif current is not None:
            buf.append(raw)
    if current is not None:
        current["body"] = "\n".join(buf).strip()
        entries.append(current)
    return entries


def _parse_date(s: str) -> _dt.date | None:
    try:
        return _dt.date.fromisoformat(s)
    except ValueError:
        return None


def filter_entries(
    entries: list[dict[str, Any]],
    *,
    lookback_days: int | None = None,
    now: _dt.date | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    if lookback_days is not None:
        today = now or _dt.date.today()
        floor = today - _dt.timedelta(days=lookback_days)
        kept = [e for e in entries
                if (d := _parse_date(e["date"])) is not None and d >= floor]
    else:
        kept = list(entries)

    def _key(e: dict[str, Any]) -> tuple[_dt.date, str]:
        d = _parse_date(e["date"]) or _dt.date.min
        return (d, e["title"])

    kept.sort(key=_key, reverse=True)
    if limit is not None:
        kept = kept[:limit]
    return kept


def render_markdown(
    entries: list[dict[str, Any]], *, window_label: str | None = None,
) -> str:
    head = "# Recent CHANGELOG entries"
    if window_label:
        head += f" ({window_label})"
    lines = [head, ""]
    if not entries:
        lines.append("_No matching CHANGELOG entries._")
        return "\n".join(lines) + "\n"
    for e in entries:
        lines.append(f"## {e['date']} - {e['title']}")
        lines.append(f"_{e['kind']}_")
        lines.append("")
        if e["body"]:
            lines.append(e["body"])
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"

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
        description="Emit recent CHANGELOG entries as md or json.",
    )
    parser.add_argument("--changelog", type=Path, required=True)
    parser.add_argument("--lookback-days", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.changelog.exists():
        print(f"ERROR: changelog not found: {args.changelog}",
              file=sys.stderr)
        return 1
    text = args.changelog.read_text(encoding="utf-8")
    entries = parse_changelog(text)
    kept = filter_entries(
        entries,
        lookback_days=args.lookback_days,
        limit=args.limit,
    )

    if args.format == "json":
        payload = {
            "schema_version": 1,
            "filter": {
                "lookback_days": args.lookback_days,
                "limit":         args.limit,
            },
            "entries": kept,
        }
        body = json.dumps(payload, indent=2) + "\n"
    else:
        label = None
        if args.lookback_days is not None:
            label = f"last {args.lookback_days} days"
        body = render_markdown(kept, window_label=label)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
