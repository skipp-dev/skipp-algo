"""Plan 2.8 manifest diff.

Compares two manifest JSONs produced by
``scripts/plan_2_8_manifest.py`` and reports:

  - ``added_scripts``    — present in current, missing in baseline
  - ``removed_scripts``  — missing in current, present in baseline
  - ``newly_testless``   — still present, but lost its test
  - ``newly_tested``     — still present, and gained a test
  - ``flag_changes``     — CLI flag additions/removals per script

Pure stdlib. Shape is a single JSON object; markdown output is
optional. Designed for weekly digest consumption.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def _index(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in manifest.get("entries", []):
        if not isinstance(row, dict):
            continue
        key = row.get("script")
        if isinstance(key, str):
            out[key] = row
    return out


def diff(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    b = _index(baseline)
    c = _index(current)

    added = sorted(set(c) - set(b))
    removed = sorted(set(b) - set(c))
    common = sorted(set(b) & set(c))

    newly_testless: list[str] = []
    newly_tested: list[str] = []
    flag_changes: list[dict[str, Any]] = []

    for key in common:
        bb = b[key]
        cc = c[key]
        bh = bool(bb.get("has_test"))
        ch = bool(cc.get("has_test"))
        if bh and not ch:
            newly_testless.append(key)
        elif (not bh) and ch:
            newly_tested.append(key)

        b_flags = list(bb.get("cli_flags", []))
        c_flags = list(cc.get("cli_flags", []))
        if b_flags != c_flags:
            added_flags = [f for f in c_flags if f not in b_flags]
            removed_flags = [f for f in b_flags if f not in c_flags]
            if added_flags or removed_flags:
                flag_changes.append({
                    "script":        key,
                    "added_flags":   added_flags,
                    "removed_flags": removed_flags,
                })

    return {
        "schema_version": 1,
        "counts": {
            "added_scripts":   len(added),
            "removed_scripts": len(removed),
            "newly_testless":  len(newly_testless),
            "newly_tested":    len(newly_tested),
            "flag_changes":    len(flag_changes),
        },
        "added_scripts":   added,
        "removed_scripts": removed,
        "newly_testless":  newly_testless,
        "newly_tested":    newly_tested,
        "flag_changes":    flag_changes,
    }


def render_markdown(report: dict[str, Any]) -> str:
    c = report["counts"]
    lines = [
        "# Plan 2.8 manifest diff",
        "",
        f"- added scripts:   {c['added_scripts']}",
        f"- removed scripts: {c['removed_scripts']}",
        f"- newly testless:  {c['newly_testless']}",
        f"- newly tested:    {c['newly_tested']}",
        f"- flag changes:    {c['flag_changes']}",
        "",
    ]

    def _bullets(title: str, items: list[str]) -> None:
        lines.append(f"## {title} ({len(items)})")
        lines.append("")
        if not items:
            lines.append("_none_")
        else:
            for item in items:
                lines.append(f"- `{item}`")
        lines.append("")

    _bullets("Added scripts",   report["added_scripts"])
    _bullets("Removed scripts", report["removed_scripts"])
    _bullets("Newly testless",  report["newly_testless"])
    _bullets("Newly tested",    report["newly_tested"])

    lines.append(f"## Flag changes ({len(report['flag_changes'])})")
    lines.append("")
    if not report["flag_changes"]:
        lines.append("_none_")
    else:
        lines.append("| script | added | removed |")
        lines.append("| --- | --- | --- |")
        for row in report["flag_changes"]:
            added_flags = ", ".join(f"`{f}`" for f in row["added_flags"]) or "-"
            removed_flags = \
                ", ".join(f"`{f}`" for f in row["removed_flags"]) or "-"
            lines.append(
                f"| `{row['script']}` | {added_flags} | {removed_flags} |"
            )
    return "\n".join(lines).rstrip() + "\n"


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest is not a JSON object")
    return data

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
        description="Diff two Plan 2.8 manifest JSONs.",
    )
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--current",  type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="json")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-regression", action="store_true",
                        help="exit 1 if anything was removed or lost a test")
    args = parser.parse_args(argv)

    try:
        baseline = _load(args.baseline)
        current = _load(args.current)
    except FileNotFoundError as exc:
        print(f"ERROR: manifest not found: {exc}", file=sys.stderr)
        return 1
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: invalid manifest: {exc}", file=sys.stderr)
        return 1

    report = diff(baseline, current)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_regression and (
        report["counts"]["removed_scripts"] > 0
        or report["counts"]["newly_testless"] > 0
    ):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
