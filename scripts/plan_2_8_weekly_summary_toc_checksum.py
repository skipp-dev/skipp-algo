"""Plan 2.8 weekly-summary TOC-checksum helper.

Extracts the ``## Contents`` block from a ``weekly_summary.md``
file, normalises it (strip trailing whitespace per line, drop
leading/trailing blank lines), and emits a stable SHA256
checksum so silent TOC drift between runs is detectable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def extract(text: str) -> str:
    lines = text.splitlines()
    start: int | None = None
    end: int | None = None
    for idx, line in enumerate(lines):
        if line.strip() == "## Contents":
            start = idx + 1
            break
    if start is None:
        return ""
    for idx in range(start, len(lines)):
        if lines[idx].startswith("## "):
            end = idx
            break
    body = lines[start:end] if end is not None else lines[start:]
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    return "\n".join(line.rstrip() for line in body)


def compute(text: str) -> dict[str, Any]:
    block = extract(text)
    digest = hashlib.sha256(block.encode("utf-8")).hexdigest() \
        if block else ""
    return {
        "schema_version": 1,
        "present":        bool(block),
        "lines":          len(block.splitlines()),
        "sha256":         digest,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary TOC checksum\n\n"
        f"- present: {str(report['present']).lower()}\n"
        f"- lines:   {report['lines']}\n"
        f"- sha256:  {report['sha256'] or 'n/a'}\n"
    )

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
        description="Stable SHA256 of weekly_summary TOC.",
    )
    parser.add_argument("--input",  type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-missing", action="store_true")
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        return 1

    report = compute(args.input.read_text(encoding="utf-8"))
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_missing and not report["present"]:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
