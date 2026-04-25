"""Plan 2.8 digest oldest/newest.

Reports the oldest and newest files in the artifact directory
by modification time. Ties are broken by name ascending. The
``oldest`` and ``newest`` fields are ``None`` when the
directory is empty.
"""

from __future__ import annotations

from scripts.smc_atomic_write import atomic_write_text

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _entries(root: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for p in root.iterdir():
        if not p.is_file():
            continue
        st = p.stat()
        items.append({
            "name":  p.name,
            "size":  st.st_size,
            "mtime": round(st.st_mtime, 3),
        })
    return items


def build(root: Path) -> dict[str, Any]:
    items = _entries(root) if root.exists() else []
    if not items:
        return {
            "schema_version": 1,
            "file_count":     0,
            "oldest":         None,
            "newest":         None,
        }
    oldest = min(items, key=lambda e: (e["mtime"], e["name"]))
    newest = max(items, key=lambda e: (e["mtime"], -ord(e["name"][0])))
    # Deterministic tiebreak on max: sort desc mtime then asc name.
    newest = sorted(
        items, key=lambda e: (-e["mtime"], e["name"]),
    )[0]
    return {
        "schema_version": 1,
        "file_count":     len(items),
        "oldest":         oldest,
        "newest":         newest,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 digest oldest/newest",
        "",
        f"- file_count: {report['file_count']}",
    ]
    if report["oldest"] is None:
        lines.extend(["- oldest: _none_", "- newest: _none_", ""])
    else:
        o = report["oldest"]
        n = report["newest"]
        lines.append(f"- oldest: {o['name']} ({o['size']}B, {o['mtime']})")
        lines.append(f"- newest: {n['name']} ({n['size']}B, {n['mtime']})")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Oldest and newest files in the artifact dir.",
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
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
