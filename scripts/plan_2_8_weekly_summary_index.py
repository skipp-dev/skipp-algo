"""Plan 2.8 weekly summary index.

Aggregates all weekly markdown reports in a digest directory into
one ``weekly_summary.md`` with a table-of-contents and copy-through
snippets. Missing inputs are skipped with a placeholder so the
output is always complete. Pure stdlib.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scripts.smc_atomic_write import atomic_write_text

# (filename, heading) pairs. Order is the TOC order.
DEFAULT_SECTIONS: tuple[tuple[str, str], ...] = (
    ("status_ledger_summary.md",        "Status ledger summary"),
    ("status_flip_alert.md",            "Status flip alert"),
    ("downtime.md",                     "Ledger downtime"),
    ("size_budget.md",                  "Size budget"),
    ("archive_index.md",                "Archive index"),
    ("index_diff.md",                   "Weekly-index diff"),
)


def build(
    artifact_dir: Path, *,
    sections: tuple[tuple[str, str], ...] = DEFAULT_SECTIONS,
) -> str:
    entries: list[tuple[str, str, bool]] = []
    for filename, heading in sections:
        target = artifact_dir / filename
        present = target.is_file() and target.stat().st_size > 0
        entries.append((filename, heading, present))

    lines: list[str] = ["# Plan 2.8 weekly summary", ""]
    lines.append("## Contents")
    lines.append("")
    for i, (_filename, heading, present) in enumerate(entries, start=1):
        state = "" if present else " _(missing)_"
        slug = heading.lower().replace(" ", "-")
        lines.append(f"{i}. [{heading}](#{slug}){state}")
    lines.append("")
    for filename, heading, present in entries:
        lines.append(f"## {heading}")
        lines.append("")
        if present:
            body = (artifact_dir / filename).read_text(encoding="utf-8")
            # strip a leading H1 so sections stay H2+
            for idx, line in enumerate(body.splitlines()):
                if line.startswith("# "):
                    body = "\n".join(body.splitlines()[idx + 1:])
                    body = body.lstrip("\n")
                    break
            lines.append(body.rstrip())
        else:
            lines.append("_Report not present for this run._")
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
        description="Aggregate Plan 2.8 weekly markdown reports.",
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if not args.artifact_dir.is_dir():
        print(f"ERROR: artifact dir not found: {args.artifact_dir}",
              file=sys.stderr)
        return 1

    body = build(args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(body, args.output)
    if not args.quiet:
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
