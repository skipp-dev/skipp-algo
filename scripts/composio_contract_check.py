"""Validate pinned Composio tool schemas against the live catalog."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from typing import Any

try:
    import composio_ops
except ImportError:
    from scripts import composio_ops


def fetch_tools(toolkit: str, api_key: str, *, opener: Any = None) -> dict[str, dict[str, Any]]:
    query = urllib.parse.urlencode({"toolkit_slug": toolkit, "toolkit_versions": "latest", "limit": 1000})
    request = urllib.request.Request(
        f"{composio_ops._base_url()}/api/v3.1/tools?{query}",
        headers={"x-api-key": api_key, "User-Agent": "skipp-algo-composio-contract/1"},
    )
    client = opener or urllib.request.build_opener()
    with client.open(request, timeout=20) as response:  # nosec B310 - configured Composio host
        payload = json.loads(response.read().decode("utf-8"))
    return {item["slug"]: item for item in payload.get("items", [])}


def check_contracts(api_key: str, *, opener: Any = None) -> list[str]:
    grouped: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for slug, spec in composio_ops.tool_registry().items():
        grouped[str(spec["toolkit"])].append((slug, spec))

    errors: list[str] = []
    for toolkit, specs in sorted(grouped.items()):
        live = fetch_tools(toolkit, api_key, opener=opener)
        for slug, spec in specs:
            remote = live.get(slug)
            if remote is None:
                errors.append(f"{slug}: missing from live {toolkit} catalog")
                continue
            if remote.get("version") != spec["version"]:
                errors.append(f"{slug}: version drift pinned={spec['version']} live={remote.get('version')}")
            live_required = set(remote.get("input_parameters", {}).get("required", []))
            pinned_required = set(spec.get("required", []))
            if live_required != pinned_required:
                errors.append(
                    f"{slug}: required-argument drift pinned={sorted(pinned_required)} live={sorted(live_required)}"
                )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    api_key = composio_ops._api_key()
    if not api_key:
        print("Composio project key is not configured", file=sys.stderr)
        return 2
    try:
        errors = check_contracts(api_key)
    except Exception as exc:  # the checker must turn transport breakage into a red canary
        errors = [f"catalog request failed: {type(exc).__name__}: {exc}"]
    report = {"ok": not errors, "environment": os.getenv("COMPOSIO_ENVIRONMENT", "prod"), "errors": errors}
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        from scripts.smc_atomic_write import atomic_write_text

        atomic_write_text(rendered, args.output)
    print(rendered, end="")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
