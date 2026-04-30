"""Plan 2.8 weekly summary json-fence count.

Counts fenced code blocks whose info-string identifies a
JSON language (``json``, ``json5``, ``jsonc``). Match is
case-insensitive on the first whitespace-delimited token.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

_FENCE = re.compile(r"^(\s*)(```|~~~)\s*(.*)$")
_JSON = frozenset({"json", "json5", "jsonc"})


def compute(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "count": 0}
    count = 0
    in_fence = False
    current_json = False
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _FENCE.match(line)
        if not m:
            continue
        if in_fence:
            if current_json:
                count += 1
            in_fence = False
            current_json = False
            continue
        info = m.group(3).strip().split()
        lang = info[0].lower() if info else ""
        in_fence = True
        current_json = lang in _JSON
    return {"schema_version": 1, "count": count}


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary json-fence count\n"
        "\n"
        f"- count: {report['count']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Count of JSON-language fenced code blocks.",
    )
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.summary.exists():
        print(f"ERROR: summary not found: {args.summary}", file=sys.stderr)
        return 1

    report = compute(args.summary)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
