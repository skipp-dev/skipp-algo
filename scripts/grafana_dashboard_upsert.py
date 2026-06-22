#!/usr/bin/env python3
"""Upsert the SMC Live Overlay dashboard JSON to Grafana Cloud.

Reads the API key from the macOS Keychain entry ``skipp.grafana.api``.
Run from the repository root:

    python scripts/grafana_dashboard_upsert.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

DASHBOARD_UID = "smc-live-overlay-v1"
DASHBOARD_PATH = Path("services/live_overlay_daemon/infra/grafana/dashboard.json")
GRAFANA_URL = "https://bronzeporridge977.grafana.net"
KEYCHAIN_SERVICE = "skipp.grafana.api"


def _api_key() -> str:
    result = subprocess.run(  # noqa: S603
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def main() -> int:
    if not DASHBOARD_PATH.exists():
        print(f"Dashboard file not found: {DASHBOARD_PATH}", file=sys.stderr)
        return 1

    dashboard = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    # Force upsert: clear server-side id/uid so Grafana matches by uid below.
    dashboard["uid"] = DASHBOARD_UID
    dashboard["id"] = None

    payload = {
        "dashboard": dashboard,
        "overwrite": True,
        "message": "Automated dashboard upsert from repo",
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{GRAFANA_URL}/api/dashboards/db",
        data=data,
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            print(f"Dashboard upserted: {body.get('url')}")
            return 0
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read().decode('utf-8')}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
