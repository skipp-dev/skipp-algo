"""Plan 2.8 rollout runbook TOC.

Scans a markdown document (default ``docs/plan_2_8_rollout_runbook.md``)
for ``##`` and ``###`` headings and emits a table-of-contents sidebar
as either markdown (with in-doc anchor links) or JSON.

Anchor slug rules mirror GitHub's heuristic:

  - lowercased
  - spaces -> ``-``
  - non [a-z0-9-] characters dropped
  - leading/trailing dashes trimmed

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

HEADING_RE = re.compile(r"^(#{2,6})\s+(.+?)\s*$")


def _slug(text: str) -> str:
    s = text.strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-]", "", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def parse_toc(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    in_fence = False
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = HEADING_RE.match(stripped)
        if not m:
            continue
        hashes, title = m.group(1), m.group(2).strip()
        level = len(hashes)
        slug = _slug(title)
        n = seen.get(slug, 0)
        seen[slug] = n + 1
        anchor = slug if n == 0 else f"{slug}-{n}"
        out.append({"level": level, "title": title, "anchor": anchor})
    return out


def render_markdown(entries: list[dict[str, Any]],
                    *, min_level: int = 2,
                    max_level: int = 3) -> str:
    lines = ["# Plan 2.8 runbook TOC", ""]
    kept = [e for e in entries
            if min_level <= e["level"] <= max_level]
    if not kept:
        lines.append("_No headings in requested range._")
        return "\n".join(lines) + "\n"
    for e in kept:
        indent = "  " * (e["level"] - min_level)
        lines.append(f"{indent}- [{e['title']}](#{e['anchor']})")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Emit a table-of-contents sidebar for a markdown doc.",
    )
    parser.add_argument("--doc", type=Path, required=True)
    parser.add_argument("--min-level", type=int, default=2)
    parser.add_argument("--max-level", type=int, default=3)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.doc.exists():
        print(f"ERROR: doc not found: {args.doc}", file=sys.stderr)
        return 1
    entries = parse_toc(args.doc.read_text(encoding="utf-8"))
    if args.format == "json":
        payload = {
            "schema_version": 1,
            "doc":             str(args.doc),
            "min_level":       args.min_level,
            "max_level":       args.max_level,
            "entries":         [e for e in entries
                                if args.min_level <= e["level"]
                                <= args.max_level],
        }
        body = json.dumps(payload, indent=2) + "\n"
    else:
        body = render_markdown(
            entries, min_level=args.min_level, max_level=args.max_level,
        )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
