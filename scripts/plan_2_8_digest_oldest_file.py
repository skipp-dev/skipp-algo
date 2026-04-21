"""Plan 2.8 digest oldest file.

Reports the single oldest artifact-directory file by mtime.
Subdirectories are ignored. When the directory is empty, the
report returns ``found=False``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build(root: Path) -> dict[str, Any]:
    candidates: list[tuple[float, str, int]] = []
    if root.exists():
        for p in root.iterdir():
            if not p.is_file():
                continue
            st = p.stat()
            candidates.append((st.st_mtime, p.name, st.st_size))
    if not candidates:
        return {"schema_version": 1, "found": False}
    candidates.sort(key=lambda t: (t[0], t[1]))
    mtime, name, size = candidates[0]
    iso = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    return {
        "schema_version": 1,
        "found":          True,
        "name":           name,
        "size_bytes":     size,
        "mtime":          iso,
    }


def render_markdown(report: dict[str, Any]) -> str:
    if not report.get("found"):
        return "# Plan 2.8 digest oldest file\n\n_none_\n"
    return (
        "# Plan 2.8 digest oldest file\n"
        "\n"
        f"- name: {report['name']}\n"
        f"- size_bytes: {report['size_bytes']}\n"
        f"- mtime: {report['mtime']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Single oldest artifact file by mtime.",
    )
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
