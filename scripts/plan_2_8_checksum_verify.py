"""Plan 2.8 checksum verifier.

Reads a ``checksums.json`` (as produced by
``plan_2_8_artifact_checksum.py``) and verifies every listed file
against the current contents of a directory. Reports mismatches,
missing files, and extra (un-checksummed) files.
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


def verify(
    manifest: dict[str, Any], artifact_dir: Path, *,
    skip_names: tuple[str, ...] = (),
) -> dict[str, Any]:
    expected: dict[str, str] = {}
    for entry in manifest.get("entries", []):
        if isinstance(entry, dict) \
                and isinstance(entry.get("path"), str) \
                and isinstance(entry.get("sha256"), str):
            expected[entry["path"]] = entry["sha256"]
    missing: list[str] = []
    mismatches: list[dict[str, str]] = []
    for path, expected_hash in sorted(expected.items()):
        target = artifact_dir / path
        if not target.is_file():
            missing.append(path)
            continue
        actual = _sha256(target)
        if actual != expected_hash:
            mismatches.append({
                "path": path, "expected": expected_hash, "actual": actual,
            })
    # find un-checksummed files in the tree
    extra: list[str] = []
    if artifact_dir.exists():
        for child in sorted(artifact_dir.rglob("*")):
            if not child.is_file():
                continue
            if child.name in skip_names:
                continue
            rel = child.relative_to(artifact_dir).as_posix()
            if rel not in expected:
                extra.append(rel)
    return {
        "schema_version": 1,
        "artifact_dir":   str(artifact_dir),
        "counts": {
            "expected":   len(expected),
            "missing":    len(missing),
            "mismatches": len(mismatches),
            "extra":      len(extra),
        },
        "missing":    missing,
        "mismatches": mismatches,
        "extra":      extra,
    }


def render_markdown(report: dict[str, Any]) -> str:
    c = report["counts"]
    lines = [
        "# Plan 2.8 checksum verification",
        "",
        f"- expected:   {c['expected']}",
        f"- missing:    {c['missing']}",
        f"- mismatches: {c['mismatches']}",
        f"- extra:      {c['extra']}",
        "",
    ]
    if report["missing"]:
        lines.append("## Missing")
        lines.extend(f"- `{p}`" for p in report["missing"])
        lines.append("")
    if report["mismatches"]:
        lines.append("## Mismatches")
        for row in report["mismatches"]:
            lines.append(
                f"- `{row['path']}`: expected `{row['expected']}`, "
                f"got `{row['actual']}`",
            )
        lines.append("")
    if report["extra"]:
        lines.append("## Extra (not in manifest)")
        lines.extend(f"- `{p}`" for p in report["extra"])
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
        description="Verify Plan 2.8 artifact checksums.",
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--skip", default="",
        help="comma-separated filenames to ignore when flagging extras",
    )
    parser.add_argument("--fail-on-mismatch", action="store_true")
    parser.add_argument("--fail-on-missing", action="store_true")
    args = parser.parse_args(argv)

    if not args.manifest.exists():
        print(f"ERROR: manifest not found: {args.manifest}",
              file=sys.stderr)
        return 1
    if not args.artifact_dir.exists():
        print(f"ERROR: artifact dir not found: {args.artifact_dir}",
              file=sys.stderr)
        return 1

    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: manifest JSON invalid: {exc}", file=sys.stderr)
        return 1
    if not isinstance(manifest, dict):
        print("ERROR: manifest must be a JSON object", file=sys.stderr)
        return 1

    skip_names = tuple(s.strip() for s in args.skip.split(",") if s.strip())
    report = verify(manifest, args.artifact_dir, skip_names=skip_names)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_mismatch and report["counts"]["mismatches"] > 0:
        return 1
    if args.fail_on_missing and report["counts"]["missing"] > 0:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
