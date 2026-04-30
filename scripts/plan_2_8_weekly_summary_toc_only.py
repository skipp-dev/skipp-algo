"""Plan 2.8 weekly-summary TOC-only extractor.

Reads ``weekly_summary.md`` and emits just the TOC block (its
``## Contents`` section, up to the next ``## `` heading) as a
standalone markdown artifact. Useful for inlining into
``$GITHUB_STEP_SUMMARY``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scripts.smc_atomic_write import atomic_write_text

CONTENTS_HEADING = "## Contents"


def extract(md: str) -> str:
    lines = md.splitlines()
    try:
        start = lines.index(CONTENTS_HEADING)
    except ValueError:
        return ""
    out: list[str] = [CONTENTS_HEADING]
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        out.append(line)
    # Trim trailing blank lines.
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract the TOC section from weekly_summary.md.",
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-empty", action="store_true")
    args = parser.parse_args(argv)

    if not args.input.is_file():
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        return 1

    body = extract(args.input.read_text(encoding="utf-8"))
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_empty and not body.strip():
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
