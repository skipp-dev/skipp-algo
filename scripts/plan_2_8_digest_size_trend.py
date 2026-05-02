"""Plan 2.8 artifact size-trend reporter.

Compares the total bytes in two artifact directories (prior vs
current) and reports absolute and percentage deltas. A
``--fail-on-drop-pct`` threshold catches unexpected shrinkage
(e.g. a workflow step silently stopped producing output).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def _total_bytes(directory: Path) -> tuple[int, int]:
    if not directory.is_dir():
        return 0, 0
    total = 0
    count = 0
    for path in directory.iterdir():
        if path.is_file():
            total += path.stat().st_size
            count += 1
    return total, count


def compute(prior: Path, current: Path) -> dict[str, Any]:
    p_bytes, p_count = _total_bytes(prior)
    c_bytes, c_count = _total_bytes(current)
    delta = c_bytes - p_bytes
    if p_bytes <= 0:
        pct: float | None = None
    else:
        pct = round((delta / p_bytes) * 100.0, 2)
    return {
        "schema_version": 1,
        "prior_bytes":    p_bytes,
        "current_bytes":  c_bytes,
        "prior_count":    p_count,
        "current_count":  c_count,
        "delta_bytes":    delta,
        "delta_pct":      pct,
    }


def render_markdown(report: dict[str, Any]) -> str:
    pct = report["delta_pct"]
    pct_s = "n/a" if pct is None else f"{pct:+.2f}%"
    return (
        "# Plan 2.8 artifact size trend\n\n"
        f"- prior:   {report['prior_bytes']} bytes "
        f"({report['prior_count']} files)\n"
        f"- current: {report['current_bytes']} bytes "
        f"({report['current_count']} files)\n"
        f"- delta:   {report['delta_bytes']:+d} bytes ({pct_s})\n"
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
        description="Compare total artifact bytes between two dirs.",
    )
    parser.add_argument("--prior",   type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output",  type=Path, default=None)
    parser.add_argument("--fail-on-drop-pct", type=float, default=None)
    args = parser.parse_args(argv)

    if not args.current.is_dir():
        print(f"ERROR: current dir not found: {args.current}",
              file=sys.stderr)
        return 1

    report = compute(args.prior, args.current)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_drop_pct is not None \
            and report["delta_pct"] is not None \
            and report["delta_pct"] < -abs(args.fail_on_drop_pct):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
