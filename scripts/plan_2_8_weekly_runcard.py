"""Plan 2.8 weekly operator runcard.

Consolidates the per-step markdown artifacts the weekly digest
workflow already produces into a single one-page dashboard:

  - Digest verdict + drift alerts
  - Snooze config lint findings
  - Slice coverage
  - Slice stability
  - Rolling alert-history summary

Any input file that is missing or empty is skipped without failure
(fail-soft by design). Pure stdlib.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
from collections.abc import Iterable
from pathlib import Path

from scripts.smc_atomic_write import atomic_write_text

SECTION_MAP: tuple[tuple[str, str], ...] = (
    ("Weekly digest",            "weekly_digest.md"),
    ("Drift alerts (issue body)", "issue_body.md"),
    ("Snooze config lint",       "snooze_lint.md"),
    ("Snapshot diff",            "snapshot_diff.md"),
    ("Top movers",               "top_movers.md"),
    ("Slice coverage",           "coverage.md"),
    ("Slice stability",          "stability.md"),
    ("Alert-history summary",    "alert_history_summary.md"),
)


def _fold(sources: Iterable[tuple[str, Path]]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for heading, path in sources:
        if not path.exists():
            continue
        body = path.read_text(encoding="utf-8").strip()
        if not body:
            continue
        out.append((heading, body))
    return out


def render_runcard(
    artifact_dir: Path,
    *,
    run_url: str | None = None,
    now: _dt.datetime | None = None,
) -> str:
    now_ = now or _dt.datetime.now(tz=_dt.UTC)
    header = [
        "# Plan 2.8 weekly runcard",
        "",
        f"_generated:_ `{now_.strftime('%Y-%m-%dT%H:%M:%SZ')}`",
    ]
    if run_url:
        header.append(f"_run:_ {run_url}")
    header.append("")

    sources = [(h, artifact_dir / fn) for (h, fn) in SECTION_MAP]
    sections = _fold(sources)
    if not sections:
        header.append("_No digest artifacts found. Runcard is empty._")
        return "\n".join(header) + "\n"

    header.append("## Included sections")
    header.append("")
    for heading, _ in sections:
        header.append(f"- {heading}")
    header.append("")

    body: list[str] = []
    for heading, text in sections:
        body.append("---")
        body.append("")
        body.append(f"## {heading}")
        body.append("")
        body.append(text)
        body.append("")
    return "\n".join(header) + "\n" + "\n".join(body) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assemble the Plan 2.8 weekly operator runcard.",
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-url", default=None)
    args = parser.parse_args(argv)

    if not args.artifact_dir.exists():
        print(f"ERROR: artifact dir not found: {args.artifact_dir}",
              file=sys.stderr)
        return 1
    body = render_runcard(args.artifact_dir, run_url=args.run_url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
