"""Plan 2.8 digest stale-report.

Classifies each file in an artifact directory as ``fresh``,
``warn``, or ``stale`` given two day-thresholds. Unlike the
plain artifact-age helper this helper groups by severity
bucket so operators can glance at the report.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def classify(
    artifact_dir: Path, *,
    warn_days: float,
    stale_days: float,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    now_ = now or _dt.datetime.now(tz=_dt.UTC)
    fresh: list[dict[str, Any]] = []
    warn: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    if artifact_dir.is_dir():
        for path in sorted(artifact_dir.iterdir()):
            if not path.is_file():
                continue
            mtime = _dt.datetime.fromtimestamp(
                path.stat().st_mtime, tz=_dt.UTC,
            )
            age = max(0.0, (now_ - mtime).total_seconds() / 86400.0)
            entry = {"name": path.name, "age_days": round(age, 2)}
            if age >= stale_days:
                stale.append(entry)
            elif age >= warn_days:
                warn.append(entry)
            else:
                fresh.append(entry)
    return {
        "schema_version": 1,
        "warn_days":      warn_days,
        "stale_days":     stale_days,
        "fresh":          fresh,
        "warn":           warn,
        "stale":          stale,
    }


def render_markdown(report: dict[str, Any]) -> str:
    def _fmt(items: list[dict[str, Any]]) -> str:
        if not items:
            return "_(none)_"
        return "\n".join(
            f"- `{e['name']}` ({e['age_days']:.2f}d)" for e in items
        )
    return (
        "# Plan 2.8 artifact stale report\n\n"
        f"- warn_days:  {report['warn_days']}\n"
        f"- stale_days: {report['stale_days']}\n"
        f"- fresh: {len(report['fresh'])}, "
        f"warn: {len(report['warn'])}, stale: {len(report['stale'])}\n\n"
        "### Stale\n\n" + _fmt(report["stale"]) + "\n\n"
        "### Warn\n\n" + _fmt(report["warn"]) + "\n"
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
        description="Classify artifacts by age severity.",
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--warn-days",  type=float, default=7.0)
    parser.add_argument("--stale-days", type=float, default=14.0)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-stale", action="store_true")
    args = parser.parse_args(argv)

    if not args.artifact_dir.is_dir():
        print(f"ERROR: artifact dir not found: {args.artifact_dir}",
              file=sys.stderr)
        return 1

    report = classify(
        args.artifact_dir,
        warn_days=args.warn_days,
        stale_days=args.stale_days,
    )
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_stale and report["stale"]:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
