"""Surface Plan 2.8 ADR entries from ``docs/DECISIONS.md``.

Parses the append-only decision log and lists entries with their
slug, date, status, and first-line summary. Supports filtering by
status (``accepted``, ``deferred``, ``superseded``) and rendering as
md, json, or plain text.

Use case: weekly digest sidebar + rollout review ("are there any
deferred decisions due for re-evaluation?").

Pure stdlib, read-only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

ENTRY_RE = re.compile(r"^### (\d{4}-\d{2}-\d{2}) - (.+)$")


def parse_decisions(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    entries: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        match = ENTRY_RE.match(lines[i])
        if not match:
            i += 1
            continue
        date, slug = match.group(1), match.group(2).strip()
        # Collect the body up to the next '### ' or end.
        j = i + 1
        body: list[str] = []
        while j < len(lines) and not ENTRY_RE.match(lines[j]):
            body.append(lines[j])
            j += 1
        body_text = "\n".join(body)
        status = _extract_status(body_text)
        summary = _extract_decision_summary(body_text)
        entries.append({
            "date": date,
            "slug": slug,
            "status": status,
            "summary": summary,
        })
        i = j
    return entries


def _extract_status(body: str) -> str:
    m = re.search(r"\*\*Status\.\*\*\s*([^\n]+)", body)
    if not m:
        return "unknown"
    return m.group(1).strip().rstrip(".").lower()


def _extract_decision_summary(body: str) -> str:
    m = re.search(r"\*\*Decision\.\*\*\s*([^\n]+)", body)
    if not m:
        return ""
    return m.group(1).strip()


def filter_entries(
    entries: list[dict[str, Any]],
    *,
    status: str | None = None,
) -> list[dict[str, Any]]:
    if status is None:
        return list(entries)
    s = status.lower()
    if s == "superseded":
        return [e for e in entries if e["status"].startswith("superseded")]
    return [e for e in entries if e["status"] == s]


def render_markdown(entries: list[dict[str, Any]]) -> str:
    lines = ["# ADR queue", ""]
    if not entries:
        lines.append("No matching ADR entries.")
        return "\n".join(lines) + "\n"
    lines.append(f"{len(entries)} entr{'y' if len(entries) == 1 else 'ies'} matching:")
    lines.append("")
    lines.append("| date | slug | status |")
    lines.append("|------|------|--------|")
    for e in entries:
        slug = e["slug"].replace("|", "\\|")
        status = e["status"].replace("|", "\\|")
        lines.append(f"| {e['date']} | {slug} | {status} |")
    lines.append("")
    for e in entries:
        lines.append(f"### {e['date']} - {e['slug']}")
        lines.append("")
        lines.append(f"_status:_ **{e['status']}**")
        if e["summary"]:
            lines.append("")
            lines.append(f"_decision:_ {e['summary']}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Surface ADR entries from docs/DECISIONS.md.",
    )
    parser.add_argument("--decisions", type=Path,
                        default=Path("docs/DECISIONS.md"))
    parser.add_argument("--status", default=None,
                        choices=("accepted", "deferred", "superseded"))
    parser.add_argument("--format", choices=("md", "json", "text"),
                        default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.decisions.exists():
        print(f"ERROR: decisions log not found: {args.decisions}",
              file=sys.stderr)
        return 1
    entries = parse_decisions(args.decisions.read_text(encoding="utf-8"))
    filtered = filter_entries(entries, status=args.status)

    if args.format == "md":
        body = render_markdown(filtered)
    elif args.format == "json":
        body = json.dumps({"total": len(entries),
                           "filter": args.status,
                           "entries": filtered}, indent=2) + "\n"
    else:
        body = "\n".join(
            f"{e['date']} | {e['status']:40s} | {e['slug']}"
            for e in filtered
        ) + ("\n" if filtered else "")
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
