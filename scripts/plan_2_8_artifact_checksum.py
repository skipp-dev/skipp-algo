"""Plan 2.8 artifact checksum emitter.

Walks a directory and computes SHA-256 for every regular file,
writing ``checksums.json`` (+ optional ``checksums.md``). Pure
stdlib.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute(artifact_dir: Path, *, skip_names: tuple[str, ...] = ()) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    total_size = 0
    if artifact_dir.exists():
        for child in sorted(artifact_dir.rglob("*")):
            if not child.is_file():
                continue
            if child.name in skip_names:
                continue
            size = child.stat().st_size
            entries.append({
                "path":   child.relative_to(artifact_dir).as_posix(),
                "size":   size,
                "sha256": _sha256(child),
            })
            total_size += size
    return {
        "schema_version": 1,
        "artifact_dir":   str(artifact_dir),
        "counts": {
            "files":      len(entries),
            "total_size": total_size,
        },
        "entries": entries,
    }


def render_markdown(report: dict[str, Any]) -> str:
    c = report["counts"]
    lines = [
        "# Plan 2.8 artifact checksums",
        "",
        f"- files:      {c['files']}",
        f"- total size: {c['total_size']} bytes",
        "",
    ]
    if not report["entries"]:
        lines.append("_No artifacts present._")
        return "\n".join(lines) + "\n"
    lines.append("| path | size | sha256 |")
    lines.append("| --- | --- | --- |")
    for row in report["entries"]:
        lines.append(
            f"| `{row['path']}` | {row['size']} | `{row['sha256']}` |",
        )
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
        description="Emit SHA-256 checksums for a directory.",
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument("--md-output", type=Path, default=None)
    parser.add_argument(
        "--skip", default="",
        help="comma-separated filenames to skip (basename match)",
    )
    args = parser.parse_args(argv)

    if not args.artifact_dir.exists():
        print(f"ERROR: artifact dir not found: {args.artifact_dir}",
              file=sys.stderr)
        return 1

    skip_names = tuple(
        s.strip() for s in args.skip.split(",") if s.strip()
    )
    report = compute(args.artifact_dir, skip_names=skip_names)
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(json.dumps(report, indent=2) + "\n", args.json_output)
    if args.md_output is not None:
        args.md_output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(render_markdown(report), args.md_output)
    if args.json_output is None and args.md_output is None:
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
