"""Plan 2.8 digest comparator.

Given two ``digest.json`` payloads (baseline + current), list the
drift alerts that:

  - appeared in current but not baseline  (``added``)
  - disappeared from current               (``removed``)
  - stayed present across both             (``persistent``)

Alert identity = ``(tf, family)``. Pure stdlib.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def _keyset(digest: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for a in digest.get("alerts") or []:
        tf = str(a.get("tf", ""))
        fam = str(a.get("family", ""))
        if not tf or not fam:
            continue
        out[(tf, fam)] = a
    return out


def compare(
    baseline: dict[str, Any], current: dict[str, Any],
) -> dict[str, Any]:
    b = _keyset(baseline)
    c = _keyset(current)
    b_keys = set(b)
    c_keys = set(c)

    added_keys      = c_keys - b_keys
    removed_keys    = b_keys - c_keys
    persistent_keys = b_keys & c_keys

    def _sorted(keys: Iterable[tuple[str, str]],
                src: dict[tuple[str, str], dict[str, Any]],
                ) -> list[dict[str, Any]]:
        return [src[k] for k in sorted(keys)]

    return {
        "schema_version": 1,
        "counts": {
            "baseline":   len(b_keys),
            "current":    len(c_keys),
            "added":      len(added_keys),
            "removed":    len(removed_keys),
            "persistent": len(persistent_keys),
        },
        "added":      _sorted(added_keys, c),
        "removed":    _sorted(removed_keys, b),
        "persistent": _sorted(persistent_keys, c),
    }


def render_markdown(report: dict[str, Any]) -> str:
    c = report["counts"]
    lines = [
        "# Plan 2.8 digest comparison",
        "",
        f"- baseline alerts:   {c['baseline']}",
        f"- current alerts:    {c['current']}",
        f"- added:             {c['added']}",
        f"- removed:           {c['removed']}",
        f"- persistent:        {c['persistent']}",
        "",
    ]
    for section in ("added", "removed", "persistent"):
        rows = report[section]
        lines.append(f"## {section.title()} ({len(rows)})")
        lines.append("")
        if not rows:
            lines.append("_none_")
            lines.append("")
            continue
        lines.append("| tf | family | delta_pp |")
        lines.append("| --- | --- | --- |")
        for r in rows:
            lines.append(f"| {r.get('tf', '')} | {r.get('family', '')} | "
                         f"{r.get('delta_pp', '')} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"digest file must be a JSON object: {path}")
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
        description="Compare two Plan 2.8 digest.json snapshots.",
    )
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-added", action="store_true")
    args = parser.parse_args(argv)

    for label, p in (("baseline", args.baseline), ("current", args.current)):
        if not p.exists():
            print(f"ERROR: {label} not found: {p}", file=sys.stderr)
            return 1

    report = compare(_load(args.baseline), _load(args.current))
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_added and report["counts"]["added"] > 0:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
