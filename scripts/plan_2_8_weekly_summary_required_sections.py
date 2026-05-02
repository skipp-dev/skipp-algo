"""Plan 2.8 weekly-summary required-sections validator.

Asserts that ``weekly_summary.md`` contains every entry in
``DEFAULT_REQUIRED`` as a ``## `` heading. Reports any missing
entries and exits non-zero under ``--fail-on-missing``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

DEFAULT_REQUIRED: tuple[str, ...] = (
    "Status ledger summary",
    "Status flip alert",
    "Downtime",
    "Size budget",
    "Archive index",
    "Index diff",
)


_H2 = re.compile(r"^##\s+(.+?)\s*$")


def _headings(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        m = _H2.match(line)
        if m is not None:
            out.append(m.group(1).strip())
    return out


def compute(text: str, *, required: tuple[str, ...]) -> dict[str, Any]:
    found = _headings(text)
    present = [h for h in required if h in found]
    missing = [h for h in required if h not in found]
    return {
        "schema_version": 1,
        "required":       list(required),
        "present":        present,
        "missing":        missing,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 weekly summary required sections",
        "",
        f"- required: {len(report['required'])}",
        f"- present:  {len(report['present'])}",
        f"- missing:  {len(report['missing'])}",
        "",
        "### Missing",
        "",
    ]
    if report["missing"]:
        lines.extend(f"- `{h}`" for h in report["missing"])
    else:
        lines.append("_(none)_")
    lines.append("")
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
        description="Validate required ##-headings in weekly_summary.md.",
    )
    parser.add_argument("--input",  type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-missing", action="store_true")
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        return 1

    report = compute(
        args.input.read_text(encoding="utf-8"),
        required=DEFAULT_REQUIRED,
    )
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_missing and report["missing"]:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
