"""Plan 2.8 digest tiny files.

Lists files in the artifact directory smaller than a
configurable byte threshold. Subdirectories are ignored.
Entries are sorted by size ascending, then by name ascending.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def build(root: Path, threshold: int) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    total = 0
    if root.exists():
        for p in root.iterdir():
            if not p.is_file():
                continue
            total += 1
            size = p.stat().st_size
            if size < threshold:
                entries.append({"name": p.name, "size": size})
    entries.sort(key=lambda e: (e["size"], e["name"]))
    return {
        "schema_version":  1,
        "threshold_bytes": threshold,
        "file_count":      total,
        "tiny_count":      len(entries),
        "entries":         entries,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 digest tiny files",
        "",
        f"- threshold_bytes: {report['threshold_bytes']}",
        f"- file_count: {report['file_count']}",
        f"- tiny_count: {report['tiny_count']}",
        "",
    ]
    if not report["entries"]:
        lines.extend(["_none_", ""])
    else:
        for e in report["entries"]:
            lines.append(f"  - {e['name']} ({e['size']}B)")
        lines.append("")
    return "\n".join(lines)

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
        description="List files below a byte threshold.",
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--threshold-bytes", type=int, default=100)
    parser.add_argument(
        "--fail-on-tiny", action="store_true",
        help="Exit 1 if any file is below threshold.",
    )
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.artifact_dir.exists():
        print(
            f"ERROR: artifact dir not found: {args.artifact_dir}",
            file=sys.stderr,
        )
        return 1

    report = build(args.artifact_dir, max(0, args.threshold_bytes))
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_tiny and report["tiny_count"] > 0:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
