"""Publish a compact weekly research/governance digest to Notion."""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime
from pathlib import Path

try:
    import composio_ops
except ImportError:
    from scripts import composio_ops


ROOT = Path(__file__).resolve().parents[1]


def render() -> tuple[str, str]:
    day = datetime.now(UTC).date().isoformat()
    title = f"skipp-algo research digest — {day}"
    decisions = sorted((ROOT / "governance" / "promotion_decisions").glob("*.json"), reverse=True)[:10]
    reports = sorted((ROOT / "artifacts" / "reports").glob("*.json"), reverse=True)[:10]
    lines = [f"# {title}", "", "Generated from repository-owned evidence. Not a trading instruction.", ""]
    decision_lines = [f"- `{p.name}`" for p in decisions] or ["- none"]
    report_lines = [f"- `{p.name}`" for p in reports] or ["- none"]
    lines.extend(["## Recent promotion decisions", *decision_lines])
    lines.extend(["", "## Recent research reports", *report_lines])
    lines.extend(["", "## Source", f"- commit: `{os.getenv('GITHUB_SHA', 'local')}`"])
    return title, "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    title, markdown = render()
    if args.dry_run:
        print(markdown)
        return 0
    parent = os.getenv("NOTION_RESEARCH_PARENT_ID", "").strip()
    if not parent:
        parser.error("NOTION_RESEARCH_PARENT_ID is required")
    result = composio_ops.create_notion_page(parent, title, markdown=markdown)
    print(result.detail)
    return 0 if result.delivered else 1


if __name__ == "__main__":
    raise SystemExit(main())
