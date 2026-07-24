#!/usr/bin/env python3
"""Guard: the live_overlay_daemon Railway service must have NO native GitHub
deploy trigger.

The daemon is designed to deploy **only** via CI
(`.github/workflows/deploy-live-overlay-daemon.yml`, path-filtered to
`services/live_overlay_daemon/**`), so its Railway service source is meant to be
`none` — see `services/live_overlay_daemon/OPS.md`. A native Railway GitHub
trigger has no path filter, so it redeploys the daemon on *every* push to
`main` (2026-07-24: ~23/day, most touching nothing in the daemon), wiping the
bar cache and resetting uptime each time. With `checkSuites:false` it also
deploys before CI validates the commit. This drift is invisible in the repo —
it lives in Railway config — so this guard catches it re-appearing.

Auth reuses the same read-capable Railway API token the `railway_metrics`
bridge already uses (`RAILWAY_API_TOKEN` + `RAILWAY_PROJECT_ID` +
`RAILWAY_ENVIRONMENT_ID`), plus the service id
(`RAILWAY_LIVE_OVERLAY_SERVICE_ID`, defaulting to the production service).

Exit codes:
  0  no native deploy trigger (healthy)  OR  token not configured (skipped)
  1  a native deploy trigger exists (drift — remove it, see OPS.md)
  2  the check could not run (auth/network/API error)

Skipping on an absent token mirrors `deploy-live-overlay-daemon.yml`, which
no-ops without its Railway secret: an unconfigured guard must not false-fail.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

# Matches the railway_metrics bridge's proven-in-production endpoint. Overridable
# for tests / a future endpoint move via RAILWAY_GRAPHQL_ENDPOINT.
_GRAPHQL_ENDPOINT = os.environ.get(
    "RAILWAY_GRAPHQL_ENDPOINT", "https://backboard.railway.com/graphql/v2"
)
# Production live_overlay_daemon service (skipp-dev's Projects / skipp-algo).
_DEFAULT_SERVICE_ID = "705582c5-ba8b-4c6e-848c-33bffe0a61b0"

_QUERY = (
    "query($projectId: String!, $environmentId: String!, $serviceId: String!) {"
    " deploymentTriggers(projectId: $projectId, environmentId: $environmentId,"
    " serviceId: $serviceId) { edges { node { id repository branch provider } } } }"
)


def _fetch_triggers(
    token: str, project_id: str, environment_id: str, service_id: str, timeout: float = 15.0
) -> list[dict]:
    """Return the service's deployment-trigger nodes. Raises on API/transport error."""
    payload = json.dumps(
        {
            "query": _QUERY,
            "variables": {
                "projectId": project_id,
                "environmentId": environment_id,
                "serviceId": service_id,
            },
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        _GRAPHQL_ENDPOINT,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if body.get("errors"):
        raise RuntimeError(f"Railway API errors: {body['errors']}")
    edges = (body.get("data") or {}).get("deploymentTriggers", {}).get("edges") or []
    return [e["node"] for e in edges if e.get("node")]


def main() -> int:
    token = os.environ.get("RAILWAY_API_TOKEN")
    project_id = os.environ.get("RAILWAY_PROJECT_ID")
    environment_id = os.environ.get("RAILWAY_ENVIRONMENT_ID")
    service_id = os.environ.get("RAILWAY_LIVE_OVERLAY_SERVICE_ID", _DEFAULT_SERVICE_ID)

    if not (token and project_id and environment_id):
        print(
            "SKIP: RAILWAY_API_TOKEN / RAILWAY_PROJECT_ID / RAILWAY_ENVIRONMENT_ID "
            "not all set — deploy-trigger drift guard did not run.",
        )
        return 0

    try:
        triggers = _fetch_triggers(token, project_id, environment_id, service_id)
    except (urllib.error.URLError, RuntimeError, ValueError, KeyError) as exc:
        print(f"ERROR: could not query Railway deployment triggers: {exc}", file=sys.stderr)
        return 2

    if not triggers:
        print("OK: live_overlay_daemon has no native Railway deploy trigger (CI-only).")
        return 0

    print(
        "DRIFT: live_overlay_daemon has a native Railway deploy trigger — it "
        "redeploys on EVERY push to its branch, bypassing the path-filtered CI "
        "workflow. Remove it (see services/live_overlay_daemon/OPS.md):",
        file=sys.stderr,
    )
    for node in triggers:
        print(
            f"  - id={node.get('id')} provider={node.get('provider')} "
            f"repo={node.get('repository')} branch={node.get('branch')}",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
