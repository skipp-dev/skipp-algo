"""Plan 2.8 digest<>coverage projector.

Projects digest alerts onto the coverage slice by ``(tf, family)`` to
surface reconciliation issues:

  - ``alerts_without_coverage``: alert pairs missing from coverage
  - ``coverage_without_alerts``: coverage pairs with no alerts (OK)
  - ``intersection``:           pairs present in both

Expected shapes (duck-typed; tolerant of extra keys):

    digest:    {..., "alerts": [{"tf": ..., "family": ..., ...}, ...]}
    coverage:  {"entries": [{"tf": ..., "family": ..., ...}, ...]}
                OR [{"tf": ..., "family": ..., ...}, ...]

Pure stdlib.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def _pairs(items: Iterable[Any]) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        tf = item.get("tf")
        fam = item.get("family")
        if isinstance(tf, str) and isinstance(fam, str):
            out.add((tf, fam))
    return out


def _coverage_entries(coverage: Any) -> list[dict[str, Any]]:
    if isinstance(coverage, dict):
        entries = coverage.get("entries")
        if isinstance(entries, list):
            return [e for e in entries if isinstance(e, dict)]
    if isinstance(coverage, list):
        return [e for e in coverage if isinstance(e, dict)]
    return []


def project(digest: Any, coverage: Any) -> dict[str, Any]:
    alerts = []
    if isinstance(digest, dict):
        a = digest.get("alerts")
        if isinstance(a, list):
            alerts = a
    alert_pairs = _pairs(alerts)
    coverage_pairs = _pairs(_coverage_entries(coverage))

    def _sorted(pairs: set[tuple[str, str]]) -> list[dict[str, str]]:
        return [
            {"tf": tf, "family": fam}
            for tf, fam in sorted(pairs)
        ]

    return {
        "schema_version": 1,
        "counts": {
            "alerts":   len(alert_pairs),
            "coverage": len(coverage_pairs),
            "alerts_without_coverage":
                len(alert_pairs - coverage_pairs),
            "coverage_without_alerts":
                len(coverage_pairs - alert_pairs),
            "intersection": len(alert_pairs & coverage_pairs),
        },
        "alerts_without_coverage":
            _sorted(alert_pairs - coverage_pairs),
        "coverage_without_alerts":
            _sorted(coverage_pairs - alert_pairs),
        "intersection":
            _sorted(alert_pairs & coverage_pairs),
    }


def render_markdown(report: dict[str, Any]) -> str:
    c = report["counts"]
    lines = [
        "# Plan 2.8 digest vs coverage",
        "",
        f"- alerts:   {c['alerts']}",
        f"- coverage: {c['coverage']}",
        f"- alerts without coverage: {c['alerts_without_coverage']}",
        f"- coverage without alerts: {c['coverage_without_alerts']}",
        f"- intersection: {c['intersection']}",
        "",
    ]

    def _table(title: str, rows: list[dict[str, str]]) -> None:
        lines.append(f"## {title} ({len(rows)})")
        lines.append("")
        if not rows:
            lines.append("_none_")
            lines.append("")
            return
        lines.append("| tf | family |")
        lines.append("| --- | --- |")
        for r in rows:
            lines.append(f"| {r['tf']} | {r['family']} |")
        lines.append("")

    _table("Alerts without coverage", report["alerts_without_coverage"])
    _table("Coverage without alerts", report["coverage_without_alerts"])
    return "\n".join(lines).rstrip() + "\n"


def _load(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(str(path))
    return json.loads(path.read_text(encoding="utf-8"))

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
        description="Project Plan 2.8 digest alerts onto the coverage "
                    "slice and surface reconciliation issues.",
    )
    parser.add_argument("--digest", type=Path, required=True)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-gap", action="store_true",
                        help="exit 1 if any alert is missing from coverage")
    args = parser.parse_args(argv)

    try:
        digest = _load(args.digest)
        coverage = _load(args.coverage)
    except FileNotFoundError as exc:
        print(f"ERROR: input not found: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON: {exc}", file=sys.stderr)
        return 1

    report = project(digest, coverage)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_gap and report["counts"]["alerts_without_coverage"] > 0:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
