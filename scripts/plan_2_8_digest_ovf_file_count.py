"""Plan 2.8 digest ovf file count."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def build(artifact_dir: Path) -> dict[str, Any]:
    if not artifact_dir.exists():
        return {
            "schema_version":    1,
            "file_count":        0,
            "ovf_file_count":    0,
        }
    files = [p for p in artifact_dir.iterdir() if p.is_file()]
    n = sum(1 for p in files if p.suffix.lower() == ".ovf")
    return {
        "schema_version":    1,
        "file_count":        len(files),
        "ovf_file_count":    n,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 digest ovf file count\n"
        "\n"
        f"- file_count: {report['file_count']}\n"
        f"- ovf_file_count: {report['ovf_file_count']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ovf file count.")
    parser.add_argument("--artifact-dir", type=Path, required=True)
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
        args.output.write_text(body, encoding="utf-8")
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
