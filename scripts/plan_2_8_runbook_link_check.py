"""Plan 2.8 runbook link check.

Scans a markdown document for intra-document anchor links of the
form ``[text](#slug)`` and verifies that each referenced ``slug``
corresponds to a heading in the same document (using the same
slugification rules as ``plan_2_8_runbook_toc.py``).

External links (``http(s)://``, ``mailto:``, cross-file links) are
ignored. Fenced code blocks are skipped when discovering headings
and when scanning for links. Duplicate slugs are disambiguated by
appending ``-1``, ``-2``, ... so multiple identical headings are
all reachable.

Pure stdlib.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

HEADING_RE = re.compile(r"^(#{2,6})\s+(.+?)\s*$")
LINK_RE = re.compile(r"\[([^\]]+)\]\(#([^)\s]+)\)")


def _slug(text: str) -> str:
    s = text.strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-]", "", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def _iter_non_fenced(text: str):
    """Yield (lineno, line) pairs for lines outside fenced code blocks."""
    in_fence = False
    for i, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        yield i, line


def collect_anchors(text: str) -> set[str]:
    anchors: set[str] = set()
    seen: dict[str, int] = {}
    for _, line in _iter_non_fenced(text):
        m = HEADING_RE.match(line.strip())
        if not m:
            continue
        slug = _slug(m.group(2).strip())
        n = seen.get(slug, 0)
        seen[slug] = n + 1
        anchor = slug if n == 0 else f"{slug}-{n}"
        anchors.add(anchor)
    return anchors


def collect_links(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for lineno, line in _iter_non_fenced(text):
        for m in LINK_RE.finditer(line):
            out.append({
                "line":   lineno,
                "text":   m.group(1),
                "anchor": m.group(2),
            })
    return out


def check(text: str) -> dict[str, Any]:
    anchors = collect_anchors(text)
    links = collect_links(text)
    broken = [ln for ln in links if ln["anchor"] not in anchors]
    return {
        "schema_version": 1,
        "counts": {
            "anchors": len(anchors),
            "links":   len(links),
            "broken":  len(broken),
        },
        "broken":  broken,
    }


def render_markdown(report: dict[str, Any]) -> str:
    c = report["counts"]
    lines = [
        "# Plan 2.8 runbook link check",
        "",
        f"- anchors:        {c['anchors']}",
        f"- intra-doc links: {c['links']}",
        f"- broken:         {c['broken']}",
        "",
    ]
    if not report["broken"]:
        lines.append("All intra-doc links resolve.")
        return "\n".join(lines) + "\n"
    lines.append("## Broken links")
    lines.append("")
    lines.append("| line | text | anchor |")
    lines.append("| --- | --- | --- |")
    for b in report["broken"]:
        lines.append(f"| {b['line']} | {b['text']} | `#{b['anchor']}` |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify intra-doc anchor links in a markdown document.",
    )
    parser.add_argument("--doc", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-broken", action="store_true")
    args = parser.parse_args(argv)

    if not args.doc.exists():
        print(f"ERROR: doc not found: {args.doc}", file=sys.stderr)
        return 1
    report = check(args.doc.read_text(encoding="utf-8"))
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_broken and report["counts"]["broken"] > 0:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
