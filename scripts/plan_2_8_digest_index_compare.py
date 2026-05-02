"""Plan 2.8 weekly-index diff.

Compares a *prior* ``index.json`` (from the previous weekly run)
against the *current* ``index.json`` and reports added / removed
files plus files whose size changed. Pure stdlib.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def _load(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    out: dict[str, int] = {}
    for entry in payload.get("entries", []):
        if not isinstance(entry, dict):
            continue
        p = entry.get("path")
        s = entry.get("size")
        if isinstance(p, str) and isinstance(s, int):
            out[p] = s
    return out


def diff(
    prior: dict[str, int], current: dict[str, int],
) -> dict[str, Any]:
    prior_keys = set(prior)
    curr_keys = set(current)
    added = sorted(curr_keys - prior_keys)
    removed = sorted(prior_keys - curr_keys)
    changed: list[dict[str, Any]] = []
    for key in sorted(prior_keys & curr_keys):
        if prior[key] != current[key]:
            changed.append({
                "path":  key,
                "before": prior[key],
                "after":  current[key],
                "delta":  current[key] - prior[key],
            })
    return {
        "schema_version": 1,
        "counts": {
            "added":   len(added),
            "removed": len(removed),
            "changed": len(changed),
        },
        "added":   added,
        "removed": removed,
        "changed": changed,
    }


def render_markdown(report: dict[str, Any]) -> str:
    c = report["counts"]
    lines = [
        "# Plan 2.8 weekly-index diff",
        "",
        f"- added:   {c['added']}",
        f"- removed: {c['removed']}",
        f"- changed: {c['changed']}",
        "",
    ]
    if not (report["added"] or report["removed"] or report["changed"]):
        lines.append("_No differences from prior run._")
        return "\n".join(lines) + "\n"
    if report["added"]:
        lines.append("## Added")
        lines.extend(f"- `{p}`" for p in report["added"])
        lines.append("")
    if report["removed"]:
        lines.append("## Removed")
        lines.extend(f"- `{p}`" for p in report["removed"])
        lines.append("")
    if report["changed"]:
        lines.append("## Changed")
        for row in report["changed"]:
            lines.append(
                f"- `{row['path']}`: {row['before']} \u2192 {row['after']} "
                f"(delta {row['delta']:+d})",
            )
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
        description="Diff two Plan 2.8 weekly index.json files.",
    )
    parser.add_argument("--prior", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-change", action="store_true")
    args = parser.parse_args(argv)

    if not args.current.exists():
        print(f"ERROR: current not found: {args.current}", file=sys.stderr)
        return 1

    prior = _load(args.prior)
    current = _load(args.current)
    report = diff(prior, current)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_change and any(report["counts"].values()):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
