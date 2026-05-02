"""Plan 2.8 digest size sum.

Sums the byte size of files in the artifact directory.
Subdirectories are ignored. Empty directories report 0.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def build(root: Path) -> dict[str, Any]:
    total_bytes = 0
    file_count = 0
    if root.exists():
        for p in root.iterdir():
            if p.is_file():
                file_count += 1
                total_bytes += p.stat().st_size
    return {
        "schema_version":  1,
        "file_count":      file_count,
        "total_bytes":     total_bytes,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 digest size sum\n"
        "\n"
        f"- file_count: {report['file_count']}\n"
        f"- total_bytes: {report['total_bytes']}\n"
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
        description="Sum of file bytes in artifact dir.",
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--fail-above-bytes", type=int, default=None)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.artifact_dir.exists():
        print(
            f"ERROR: artifact dir not found: {args.artifact_dir}",
            file=sys.stderr,
        )
        return 1

    report = build(args.artifact_dir)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if (args.fail_above_bytes is not None
            and report["total_bytes"] > args.fail_above_bytes):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
