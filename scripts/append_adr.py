"""Append a new ADR entry to ``docs/DECISIONS.md``.

The canonical ADR shape is defined in the file's header. This helper
enforces the required subsections (Context / Decision / Alternatives
considered / Consequences / Evidence / Status) and inserts the new
entry after the last existing ADR, keeping the log append-only and
structurally consistent.

Typical use (e.g. at W13 recording a Q4-gate reject reason):

    python scripts/append_adr.py \
        --slug "reject 2H 4th HTF layer" \
        --date 2026-07-14 \
        --context-file /tmp/context.md \
        --decision "Keep 3-layer HTF stack; reject 2H promotion." \
        --alternatives-file /tmp/alts.md \
        --consequences "Backlog remains; re-evaluate W52." \
        --evidence "artifacts/q4_gate/plan_2_8_q4_gate_verdict.json (overall: fail)" \
        --status accepted
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
from pathlib import Path


ENTRIES_HEADER = "## Entries"
REQUIRED_SUBSECTIONS = (
    "Context", "Decision", "Alternatives considered",
    "Consequences", "Evidence", "Status",
)


def _read_optional(path: Path | None) -> str:
    if path is None:
        return ""
    return Path(path).read_text(encoding="utf-8").rstrip()


def render_entry(
    *,
    date: str,
    slug: str,
    context: str,
    decision: str,
    alternatives: str,
    consequences: str,
    evidence: str,
    status: str,
) -> str:
    """Render a single ADR entry as markdown. All body params are free text."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError(f"date must be YYYY-MM-DD, got {date!r}")
    if not slug.strip():
        raise ValueError("slug must be non-empty")
    if not decision.strip():
        raise ValueError("decision must be non-empty")
    if status not in ("accepted", "deferred") \
            and not status.startswith("superseded by "):
        raise ValueError(
            "status must be 'accepted', 'deferred', or 'superseded by <slug>'")

    parts: list[str] = []
    parts.append(f"### {date} - {slug.strip()}")
    parts.append("")
    parts.append(f"**Context.** {context.strip() or 'TBD.'}")
    parts.append("")
    parts.append(f"**Decision.** {decision.strip()}")
    parts.append("")
    parts.append("**Alternatives considered.**")
    parts.append("")
    parts.append(alternatives.strip() or "- _none recorded_")
    parts.append("")
    parts.append(f"**Consequences.** {consequences.strip() or 'TBD.'}")
    parts.append("")
    parts.append(f"**Evidence.** {evidence.strip() or 'TBD.'}")
    parts.append("")
    parts.append(f"**Status.** {status}.")
    parts.append("")
    return "\n".join(parts)


def append_entry(decisions_path: Path, entry: str) -> None:
    """Append the entry at the very end of the file, preserving trailing newline."""
    text = decisions_path.read_text(encoding="utf-8")
    if ENTRIES_HEADER not in text:
        raise ValueError(
            f"{decisions_path} has no '{ENTRIES_HEADER}' section; refusing to append")
    text = text.rstrip() + "\n\n" + entry.rstrip() + "\n"
    decisions_path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Append a new ADR to docs/DECISIONS.md")
    parser.add_argument("--decisions", type=Path,
                        default=Path("docs/DECISIONS.md"))
    parser.add_argument("--slug", required=True)
    parser.add_argument("--date", default=_dt.date.today().isoformat())
    parser.add_argument("--context", default="")
    parser.add_argument("--context-file", type=Path, default=None)
    parser.add_argument("--decision", required=True)
    parser.add_argument("--alternatives", default="")
    parser.add_argument("--alternatives-file", type=Path, default=None)
    parser.add_argument("--consequences", default="")
    parser.add_argument("--evidence", default="")
    parser.add_argument("--status", default="accepted")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the rendered entry, do not modify the file.")
    args = parser.parse_args(argv)

    try:
        entry = render_entry(
            date=args.date,
            slug=args.slug,
            context=args.context or _read_optional(args.context_file),
            decision=args.decision,
            alternatives=args.alternatives or _read_optional(args.alternatives_file),
            consequences=args.consequences,
            evidence=args.evidence,
            status=args.status,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(entry)
        return 0

    try:
        append_entry(args.decisions, entry)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"appended ADR '{args.slug}' to {args.decisions}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
