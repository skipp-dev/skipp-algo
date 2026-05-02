"""Plan 2.8 smallest-files report.

Lists the bottom-N files in the artifact directory by size
(ascending; ties broken by name ascending). Mirror of
``plan_2_8_digest_largest_files.py``. Subdirectories are
ignored.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def build(artifact_dir: Path, bottom_n: int) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    if artifact_dir.is_dir():
        for path in artifact_dir.iterdir():
            if not path.is_file():
                continue
            rows.append({"name": path.name, "size": path.stat().st_size})
    rows.sort(key=lambda e: (e["size"], e["name"]))
    if bottom_n > 0:
        rows = rows[:bottom_n]
    return {
        "schema_version": 1,
        "bottom_n":       bottom_n,
        "count":          len(rows),
        "entries":        rows,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 digest smallest files",
        "",
        f"- bottom_n: {report['bottom_n']}",
        f"- count: {report['count']}",
        "",
        "| file | size |",
        "|---|---:|",
    ]
    if report["entries"]:
        for e in report["entries"]:
            lines.append(f"| `{e['name']}` | {e['size']} |")
    else:
        lines.append("| _none_ | 0 |")
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
        description="Bottom-N smallest files in artifact directory.",
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--bottom-n", type=int, default=10)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.artifact_dir.is_dir():
        print(f"ERROR: artifact dir not found: {args.artifact_dir}",
              file=sys.stderr)
        return 1

    report = build(args.artifact_dir, args.bottom_n)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
