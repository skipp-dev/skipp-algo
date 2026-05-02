"""Plan 2.8 digest top extension.

Reports the most common file extension in the artifact
directory (ties break alphabetically asc). Files without an
extension are grouped under the empty string. Subdirectories
are ignored.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def build(root: Path) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    if root.exists():
        for p in root.iterdir():
            if not p.is_file():
                continue
            ext = p.suffix.lower().lstrip(".")
            counts[ext] += 1
    if not counts:
        return {
            "schema_version":  1,
            "file_count":      0,
            "top_ext":         None,
            "top_count":       0,
        }
    best_count = max(counts.values())
    top_ext = sorted(e for e, c in counts.items() if c == best_count)[0]
    return {
        "schema_version":  1,
        "file_count":      sum(counts.values()),
        "top_ext":         top_ext,
        "top_count":       best_count,
    }


def render_markdown(report: dict[str, Any]) -> str:
    ext = report["top_ext"]
    ext_s = f".{ext}" if ext else ("(none)" if ext is None else "(no-ext)")
    return (
        "# Plan 2.8 digest top extension\n"
        "\n"
        f"- file_count: {report['file_count']}\n"
        f"- top_ext: {ext_s}\n"
        f"- top_count: {report['top_count']}\n"
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
        description="Most common file extension in artifact dir.",
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--fail-below-count", type=int, default=None)
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
    if (args.fail_below_count is not None
            and report["top_count"] < args.fail_below_count):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
