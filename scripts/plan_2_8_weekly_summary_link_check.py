"""Plan 2.8 weekly summary link checker.

Parses the weekly summary markdown for ``[text](target)``
links and reports:

- total link count
- URL link count (targets that look like absolute URLs)
- fragment-only link count (targets starting with ``#``)
- fragment-only links that have no matching heading anchor

Headings are normalised to GitHub-style anchor slugs
(lowercase; non-alphanumeric to ``-``; collapse repeated
dashes; strip leading/trailing dashes).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_SLUG_SUB = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    s = _SLUG_SUB.sub("-", text.lower()).strip("-")
    return s


def compute(summary_path: Path) -> dict[str, Any]:
    text = ""
    if summary_path.is_file():
        text = summary_path.read_text(encoding="utf-8")

    anchors: set[str] = set()
    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m is not None:
            anchors.add(_slug(m.group(1)))

    targets = _LINK_RE.findall(text)
    total = len(targets)
    url_count = sum(1 for t in targets if "://" in t or t.startswith("mailto:"))
    frag_total = 0
    frag_missing: list[str] = []
    for t in targets:
        if t.startswith("#"):
            frag_total += 1
            anchor = t.lstrip("#")
            if anchor and anchor not in anchors:
                frag_missing.append(t)
    return {
        "schema_version":      1,
        "total":               total,
        "url_count":           url_count,
        "fragment_count":      frag_total,
        "missing_fragments":   sorted(set(frag_missing)),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 weekly summary link check",
        "",
        f"- total: {report['total']}",
        f"- url_count: {report['url_count']}",
        f"- fragment_count: {report['fragment_count']}",
        f"- missing_fragments: {len(report['missing_fragments'])}",
        "",
    ]
    if report["missing_fragments"]:
        lines.append("## Missing anchors")
        lines.append("")
        for frag in report["missing_fragments"]:
            lines.append(f"- `{frag}`")
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check links in the weekly summary markdown.",
    )
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument(
        "--fail-on-missing-fragments",
        action="store_true",
        help="Exit 1 if any fragment-only link has no matching anchor.",
    )
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.summary.is_file():
        print(f"ERROR: summary not found: {args.summary}", file=sys.stderr)
        return 1

    report = compute(args.summary)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_missing_fragments and report["missing_fragments"]:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
