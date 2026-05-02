"""Plan 2.8 weekly-summary link checker.

Scans ``weekly_summary.md`` for internal anchor links
(``[text](#slug)``) and verifies each one points at an existing
section heading. Emits a per-link report in md or json. Optional
``--fail-on-broken`` turns any broken link into rc=1.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

# Matches `[label](#slug)` but **not** http(s) or file links.
LINK_RE = re.compile(r"\[([^\]]+)\]\(#([A-Za-z0-9][A-Za-z0-9_\-]*)\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def _slugify(heading: str) -> str:
    # Lowercase, drop anything that isn't a-z/0-9/space/-, then
    # replace spaces with hyphens.
    s = heading.lower()
    s = re.sub(r"[^a-z0-9\s\-]", "", s)
    s = re.sub(r"\s+", "-", s.strip())
    return s


def scan(md: str) -> dict[str, Any]:
    headings: set[str] = set()
    for line in md.splitlines():
        m = HEADING_RE.match(line)
        if m:
            headings.add(_slugify(m.group(2)))
    links: list[dict[str, Any]] = []
    for m in LINK_RE.finditer(md):
        slug = m.group(2)
        links.append({
            "label": m.group(1),
            "slug":  slug,
            "ok":    slug in headings,
        })
    broken = [ln for ln in links if not ln["ok"]]
    return {
        "schema_version": 1,
        "total":           len(links),
        "broken_count":    len(broken),
        "links":           links,
        "broken":          broken,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 weekly-summary link check",
        "",
        f"- links:  {report['total']}",
        f"- broken: {report['broken_count']}",
        "",
    ]
    if report["broken"]:
        lines.append("## Broken links")
        for b in report["broken"]:
            lines.append(f"- [{b['label']}](#{b['slug']}) -> missing heading")
        lines.append("")
    else:
        lines.append("_All links resolve._")
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
        description="Check that weekly_summary.md anchor links resolve.",
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-broken", action="store_true")
    args = parser.parse_args(argv)

    if not args.input.is_file():
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        return 1

    report = scan(args.input.read_text(encoding="utf-8"))
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_broken and report["broken_count"] > 0:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
