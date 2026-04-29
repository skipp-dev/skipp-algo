"""Plan 2.8 per-file size-budget guard.

Scans a directory and reports files whose size exceeds a
configurable byte budget (default 1 MiB). With
``--fail-on-breach`` the process exits non-zero when any file is
over the limit. Intended to protect the weekly digest artifact
bundle from unintentional bloat.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

DEFAULT_MAX_BYTES = 1 * 1024 * 1024  # 1 MiB


def scan(
    artifact_dir: Path, *, max_bytes: int,
    skip_names: tuple[str, ...] = (),
) -> dict[str, Any]:
    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    entries: list[dict[str, Any]] = []
    breaches: list[dict[str, Any]] = []
    if artifact_dir.exists():
        for child in sorted(artifact_dir.rglob("*")):
            if not child.is_file():
                continue
            if child.name in skip_names:
                continue
            try:
                size = child.stat().st_size
            except OSError:
                size = 0
            rel = child.relative_to(artifact_dir).as_posix()
            row = {"path": rel, "size": size}
            entries.append(row)
            if size > max_bytes:
                breaches.append(row)
    return {
        "schema_version": 1,
        "artifact_dir":   str(artifact_dir),
        "max_bytes":      max_bytes,
        "counts": {
            "files":    len(entries),
            "breaches": len(breaches),
        },
        "breaches": breaches,
    }


def render_markdown(report: dict[str, Any]) -> str:
    c = report["counts"]
    lines = [
        "# Plan 2.8 size budget",
        "",
        f"- files:     {c['files']}",
        f"- breaches:  {c['breaches']}",
        f"- max_bytes: {report['max_bytes']}",
        "",
    ]
    if not report["breaches"]:
        lines.append("_All files within budget._")
        return "\n".join(lines) + "\n"
    lines.append("| path | size |")
    lines.append("| --- | --- |")
    for row in report["breaches"]:
        lines.append(f"| `{row['path']}` | {row['size']} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report files exceeding a per-file size budget.",
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--skip", default="",
                        help="comma-separated filenames to ignore")
    parser.add_argument("--fail-on-breach", action="store_true")
    args = parser.parse_args(argv)

    if not args.artifact_dir.exists():
        print(f"ERROR: artifact dir not found: {args.artifact_dir}",
              file=sys.stderr)
        return 1
    if args.max_bytes < 0:
        print("ERROR: --max-bytes must be non-negative", file=sys.stderr)
        return 1

    skip_names = tuple(s.strip() for s in args.skip.split(",") if s.strip())
    report = scan(
        args.artifact_dir, max_bytes=args.max_bytes,
        skip_names=skip_names,
    )
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_breach and report["counts"]["breaches"] > 0:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
