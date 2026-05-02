"""Plan 2.8 rollout-runbook section check.

Verifies the rollout runbook contains all canonical top-level (``## ``)
sections and emits a compact md/json report. Pure stdlib.

Canonical sections (configurable via ``--required``) default to::

    Weekly
    Monthly
    Files added

Heading detection ignores fenced code blocks and trailing whitespace.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path

from scripts.smc_atomic_write import atomic_write_text

DEFAULT_REQUIRED: tuple[str, ...] = (
    "Phase timeline (addendum \u00a76)",
    "Daily automation",
    "Status quick-check",
)
HEADING_RE = re.compile(r"^## +(.+?)\s*$")


def _iter_non_fenced(text: str) -> Iterable[str]:
    in_fence = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        yield line


def collect_sections(text: str) -> list[str]:
    out: list[str] = []
    for line in _iter_non_fenced(text):
        m = HEADING_RE.match(line)
        if m:
            out.append(m.group(1).strip())
    return out


def check(
    text: str,
    *,
    required: Iterable[str] = DEFAULT_REQUIRED,
) -> dict[str, object]:
    required_list = [r.strip() for r in required if r.strip()]
    sections = collect_sections(text)
    present = [r for r in required_list if r in sections]
    missing = [r for r in required_list if r not in sections]
    return {
        "schema_version": 1,
        "counts": {
            "required": len(required_list),
            "present":  len(present),
            "missing":  len(missing),
            "sections": len(sections),
        },
        "required": required_list,
        "present":  present,
        "missing":  missing,
        "sections": sections,
    }


def render_markdown(report: dict[str, object]) -> str:
    c = report["counts"]  # type: ignore[assignment]
    lines = [
        "# Plan 2.8 runbook section check",
        "",
        f"- required: {c['required']}",
        f"- present:  {c['present']}",
        f"- missing:  {c['missing']}",
        f"- total sections: {c['sections']}",
        "",
    ]
    missing = report["missing"]  # type: ignore[index]
    if missing:
        lines.append("## Missing")
        lines.append("")
        for name in missing:  # type: ignore[union-attr]
            lines.append(f"- `{name}`")
    else:
        lines.append("_All required sections present._")
    return "\n".join(lines).rstrip() + "\n"

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
        description="Check the Plan 2.8 runbook for required sections.",
    )
    parser.add_argument("--doc", type=Path, required=True)
    parser.add_argument(
        "--required",
        default=",".join(DEFAULT_REQUIRED),
        help="comma-separated list of section titles to require",
    )
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-missing", action="store_true")
    args = parser.parse_args(argv)

    if not args.doc.exists():
        print(f"ERROR: doc not found: {args.doc}", file=sys.stderr)
        return 1
    text = args.doc.read_text(encoding="utf-8")

    required = [s.strip() for s in args.required.split(",") if s.strip()]
    report = check(text, required=required)

    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_missing and report["counts"]["missing"] > 0:  # type: ignore[index]
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
