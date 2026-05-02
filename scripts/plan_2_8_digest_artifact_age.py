"""Plan 2.8 digest artifact-age reporter.

For each regular file under ``--artifact-dir``, report name,
size, mtime, and age-in-days relative to ``--now`` (default: the
current UTC time). Optional ``--fail-on-older-than DAYS`` fails
the process if any artifact is older than the threshold.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def scan(
    artifact_dir: Path, *,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    now_ = now or _dt.datetime.now(tz=_dt.UTC)
    entries: list[dict[str, Any]] = []
    if artifact_dir.is_dir():
        for path in sorted(artifact_dir.iterdir()):
            if not path.is_file():
                continue
            mtime = _dt.datetime.fromtimestamp(
                path.stat().st_mtime, tz=_dt.UTC,
            )
            age = (now_ - mtime).total_seconds() / 86400.0
            if age < 0:
                age = 0.0
            entries.append({
                "name":     path.name,
                "size":     path.stat().st_size,
                "mtime":    mtime.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "age_days": round(age, 2),
            })
    oldest = max((e["age_days"] for e in entries), default=0.0)
    return {
        "schema_version": 1,
        "captured_at":    now_.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count":          len(entries),
        "oldest_days":    round(oldest, 2),
        "entries":        entries,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 artifact age",
        "",
        f"- captured_at: {report['captured_at']}",
        f"- count:       {report['count']}",
        f"- oldest:      {report['oldest_days']:.2f} days",
        "",
        "| file | size | mtime | age (days) |",
        "|---|---:|---|---:|",
    ]
    if report["entries"]:
        for e in report["entries"]:
            lines.append(
                f"| `{e['name']}` | {e['size']} | {e['mtime']} "
                f"| {e['age_days']:.2f} |"
            )
    else:
        lines.append("| _none_ | 0 | - | 0.00 |")
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
        description="Report artifact ages (days).",
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-older-than", type=float, default=None)
    args = parser.parse_args(argv)

    if not args.artifact_dir.is_dir():
        print(f"ERROR: artifact dir not found: {args.artifact_dir}",
              file=sys.stderr)
        return 1

    report = scan(args.artifact_dir)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_older_than is not None \
            and report["oldest_days"] > args.fail_on_older_than:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
