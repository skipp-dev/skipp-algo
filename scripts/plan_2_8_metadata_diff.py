"""Plan 2.8 digest-metadata diff.

Compares current ``metadata.json`` to a prior copy (downloaded via
``dawidd6/action-download-artifact@v6``) and reports:

- python version change
- platform change
- script count delta
- per-script size deltas (added / removed / changed)

Pure stdlib.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _scripts_map(payload: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for entry in payload.get("scripts", []) or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        size = entry.get("size")
        if isinstance(name, str) and isinstance(size, int):
            out[name] = size
    return out


def diff(prior: dict[str, Any],
         current: dict[str, Any]) -> dict[str, Any]:
    p_scripts = _scripts_map(prior)
    c_scripts = _scripts_map(current)
    added = sorted(set(c_scripts) - set(p_scripts))
    removed = sorted(set(p_scripts) - set(c_scripts))
    changed: list[dict[str, Any]] = []
    for name in sorted(set(p_scripts) & set(c_scripts)):
        if p_scripts[name] != c_scripts[name]:
            changed.append({
                "name":  name,
                "prior": p_scripts[name],
                "current": c_scripts[name],
                "delta": c_scripts[name] - p_scripts[name],
            })
    return {
        "schema_version": 1,
        "python_prior":   prior.get("python"),
        "python_current": current.get("python"),
        "platform_prior":   prior.get("platform"),
        "platform_current": current.get("platform"),
        "count_prior":   len(p_scripts),
        "count_current": len(c_scripts),
        "added":   added,
        "removed": removed,
        "changed": changed,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Plan 2.8 metadata diff", ""]
    lines.append(
        f"- python: {report['python_prior']} -> "
        f"{report['python_current']}"
    )
    lines.append(
        f"- scripts count: {report['count_prior']} -> "
        f"{report['count_current']}"
    )
    lines.append("")
    if report["added"]:
        lines.append("## Added")
        lines.extend(f"- `{n}`" for n in report["added"])
        lines.append("")
    if report["removed"]:
        lines.append("## Removed")
        lines.extend(f"- `{n}`" for n in report["removed"])
        lines.append("")
    if report["changed"]:
        lines.append("## Size changes")
        for c in report["changed"]:
            sign = "+" if c["delta"] > 0 else ""
            lines.append(
                f"- `{c['name']}`: {c['prior']} -> "
                f"{c['current']} ({sign}{c['delta']})"
            )
        lines.append("")
    if not (report["added"] or report["removed"]
            or report["changed"]):
        lines.append("_No script changes._")
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
        description="Diff current metadata.json against prior.",
    )
    parser.add_argument("--prior", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-change", action="store_true")
    args = parser.parse_args(argv)

    if not args.current.is_file():
        print(f"ERROR: current not found: {args.current}",
              file=sys.stderr)
        return 1

    report = diff(_load(args.prior), _load(args.current))
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_change and (
        report["added"] or report["removed"] or report["changed"]
    ):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
