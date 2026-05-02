"""Plan 2.8 artifact-catalog diff.

Compares two ``plan_2_8_digest_artifact_catalog`` JSON outputs
(prior vs current) and reports artifacts that moved between
``known`` and ``unknown`` lists plus first-seen and dropped
entries.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _known(data: dict[str, Any]) -> set[str]:
    out = set()
    for e in data.get("known") or []:
        if isinstance(e, dict) and isinstance(e.get("name"), str):
            out.add(e["name"])
    return out


def _unknown(data: dict[str, Any]) -> set[str]:
    out = set()
    for e in data.get("unknown") or []:
        if isinstance(e, dict) and isinstance(e.get("name"), str):
            out.add(e["name"])
        elif isinstance(e, str):
            out.add(e)
    return out


def diff(prior: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    pk, pu = _known(prior), _unknown(prior)
    ck, cu = _known(current), _unknown(current)
    return {
        "schema_version":     1,
        "added_known":        sorted(ck - pk - pu),
        "added_unknown":      sorted(cu - pu - pk),
        "dropped":            sorted((pk | pu) - (ck | cu)),
        "known_to_unknown":   sorted(cu & pk),
        "unknown_to_known":   sorted(ck & pu),
    }


def render_markdown(report: dict[str, Any]) -> str:
    def _section(title: str, items: list[str]) -> str:
        if not items:
            return f"### {title}\n\n_(none)_\n"
        body = "\n".join(f"- `{n}`" for n in items)
        return f"### {title}\n\n{body}\n"
    return (
        "# Plan 2.8 artifact catalog diff\n\n"
        + _section("Added (known)",      report["added_known"]) + "\n"
        + _section("Added (unknown)",    report["added_unknown"]) + "\n"
        + _section("Dropped",            report["dropped"]) + "\n"
        + _section("Known -> unknown",   report["known_to_unknown"]) + "\n"
        + _section("Unknown -> known",   report["unknown_to_known"]) + "\n"
    )

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
        description="Diff two artifact-catalog JSON outputs.",
    )
    parser.add_argument("--prior",   type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output",  type=Path, default=None)
    parser.add_argument("--fail-on-unknown-growth", action="store_true")
    args = parser.parse_args(argv)

    if not args.current.exists():
        print(f"ERROR: current not found: {args.current}", file=sys.stderr)
        return 1

    report = diff(_load(args.prior), _load(args.current))
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_unknown_growth and (
        report["added_unknown"] or report["known_to_unknown"]
    ):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
