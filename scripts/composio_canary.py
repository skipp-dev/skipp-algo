"""Run non-mutating synthetic probes through each Composio connection."""

from __future__ import annotations

import argparse
import json
from typing import Any

try:
    import composio_ops
except ImportError:
    from scripts import composio_ops


PROBES: dict[str, tuple[str, dict[str, Any]]] = {
    "slack": ("SLACK_TEST_AUTH", {}),
    "github": ("GITHUB_GET_THE_AUTHENTICATED_USER", {}),
    "outlook": ("OUTLOOK_GET_PROFILE", {"user_id": "me"}),
    "notion": ("NOTION_GET_ABOUT_USER", {"user_id": "me"}),
}


def run(toolkits: list[str]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for toolkit in toolkits:
        slug, arguments = PROBES[toolkit]
        result = composio_ops.execute_tool(slug, arguments, toolkit=toolkit, access="read")
        results.append(
            {
                "toolkit": toolkit,
                "tool": slug,
                "ok": result.delivered,
                "skipped": result.skipped,
                "detail": result.detail,
            }
        )
    return {"ok": all(item["ok"] for item in results), "probes": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolkits", default="slack,github,outlook,notion")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    toolkits = [item.strip() for item in args.toolkits.split(",") if item.strip()]
    unknown = sorted(set(toolkits) - PROBES.keys())
    if unknown:
        parser.error(f"unknown toolkits: {', '.join(unknown)}")
    report = run(toolkits)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        from scripts.smc_atomic_write import atomic_write_text

        atomic_write_text(rendered, args.output)
    print(rendered, end="")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
