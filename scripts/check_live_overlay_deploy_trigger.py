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

Auth, in order of preference (plus `RAILWAY_PROJECT_ID` +
`RAILWAY_ENVIRONMENT_ID`, and the service id
`RAILWAY_LIVE_OVERLAY_SERVICE_ID` defaulting to the production service):

* `RAILWAY_PROJECT_ACCESS_TOKEN` — a Railway PROJECT token, scoped to exactly
  this project + environment, sent as the `Project-Access-Token` header.
  Verified live 2026-08-03: the operator's project token resolves
  `projectToken { projectId environmentId }` to this project.
* `RAILWAY_API_TOKEN` — an account/workspace token, sent as
  `Authorization: Bearer` (the header project tokens do NOT accept).

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


def _auth_header(token: str, auth_kind: str) -> dict[str, str]:
    """The header Railway expects for this token type.

    Project tokens do NOT authenticate via ``Authorization: Bearer`` — they use
    a dedicated ``Project-Access-Token`` header (docs.railway.com/guides/
    public-api). Measured 2026-08-03: a project token sent as Bearer fails even
    ``{ me }`` with the same bare "Not Authorized" an unauthenticated request
    gets, so the error text cannot distinguish a wrong header from a missing
    token. A project token is also the better credential here: it is scoped to
    exactly one project + environment instead of the whole account.
    """
    if auth_kind == "project":
        return {"Project-Access-Token": token}
    return {"Authorization": f"Bearer {token}"}


def _fetch_triggers(
    token: str,
    project_id: str,
    environment_id: str,
    service_id: str,
    timeout: float = 15.0,
    auth_kind: str = "account",
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
            **_auth_header(token, auth_kind),
            "Content-Type": "application/json",
            # Railway sits behind Cloudflare, which rejects urllib's default
            # ``Python-urllib/3.x`` agent with HTTP 403 / error code 1010 —
            # measured 2026-08-03: identical request, any User-Agent, 200.
            # Without this the guard reports "403 Forbidden", which reads as a
            # credential fault and hid a header fault for weeks.
            "User-Agent": "skipp-algo-deploy-trigger-guard/1",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if body.get("errors"):
        raise RuntimeError(f"Railway API errors: {body['errors']}")
    edges = (body.get("data") or {}).get("deploymentTriggers", {}).get("edges") or []
    return [e["node"] for e in edges if e.get("node")]


_PROJECT_TOKEN_QUERY = "query { projectToken { projectId environmentId } }"


def _diagnose_project_token(
    token: str,
    project_id: str,
    environment_id: str,
    timeout: float = 15.0,
) -> str:
    """Say which of the cases Railway's bare "Not Authorized" is hiding.

    ``deploymentTriggers`` answers "Not Authorized" for a revoked token, for a
    token pointing at another project, and for a live token that simply may not
    read that field — three different fixes, one message. ``projectToken``
    resolves against the token itself, so it separates them.

    Returns a single operator-facing line. Never echoes the token, and reports
    the resolved ids only as match/mismatch: they are repository secrets, and
    an unmasked id in a public log is a leak.
    """
    req = urllib.request.Request(
        _GRAPHQL_ENDPOINT,
        data=json.dumps({"query": _PROJECT_TOKEN_QUERY}).encode("utf-8"),
        headers={
            "Project-Access-Token": token,
            "Content-Type": "application/json",
            "User-Agent": "skipp-algo-deploy-trigger-guard/1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 - literal endpoint
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return f"follow-up probe could not run ({type(exc).__name__}) — diagnosis inconclusive"

    if body.get("errors"):
        return (
            "Railway does not recognise this project token (projectToken -> "
            f"{body['errors']}) — it was revoked or rotated; issue a new one and "
            "update RAILWAY_PROJECT_ACCESS_TOKEN"
        )
    resolved = (body.get("data") or {}).get("projectToken") or {}
    got_project = resolved.get("projectId")
    got_env = resolved.get("environmentId")
    if not got_project or not got_env:
        return "projectToken returned no ids — diagnosis inconclusive"
    if got_project != project_id or got_env != environment_id:
        which = []
        if got_project != project_id:
            which.append("project")
        if got_env != environment_id:
            which.append("environment")
        return (
            f"the project token is live but resolves to a different {'/'.join(which)} "
            "than RAILWAY_PROJECT_ID / RAILWAY_ENVIRONMENT_ID — the token and the ids "
            "describe different places"
        )
    return (
        "the project token is live and scoped to exactly this project+environment, "
        "so deploymentTriggers is beyond what a project token may read — unset "
        "RAILWAY_PROJECT_ACCESS_TOKEN to fall back to the account token in "
        "RAILWAY_API_TOKEN"
    )


def main() -> int:
    project_token = os.environ.get("RAILWAY_PROJECT_ACCESS_TOKEN")
    account_token = os.environ.get("RAILWAY_API_TOKEN")
    token, auth_kind = (
        (project_token, "project") if project_token else (account_token, "account")
    )
    project_id = os.environ.get("RAILWAY_PROJECT_ID")
    environment_id = os.environ.get("RAILWAY_ENVIRONMENT_ID")
    service_id = os.environ.get("RAILWAY_LIVE_OVERLAY_SERVICE_ID", _DEFAULT_SERVICE_ID)

    if not (token and project_id and environment_id):
        print(
            "SKIP: neither RAILWAY_PROJECT_ACCESS_TOKEN nor RAILWAY_API_TOKEN set, "
            "or RAILWAY_PROJECT_ID / RAILWAY_ENVIRONMENT_ID missing — "
            "deploy-trigger drift guard did not run.",
        )
        return 0

    try:
        triggers = _fetch_triggers(
            token, project_id, environment_id, service_id, auth_kind=auth_kind
        )
    except (urllib.error.URLError, RuntimeError, ValueError, KeyError) as exc:
        # Name the credential: RAILWAY_PROJECT_ACCESS_TOKEN wins outright when
        # set, with no fallback, so a dead project token masks a working
        # account token — and the old message never said which one was tried.
        print(
            f"ERROR: could not query Railway deployment triggers "
            f"using the {auth_kind} token: {exc}",
            file=sys.stderr,
        )
        if auth_kind == "project":
            print(
                f"DIAGNOSIS: {_diagnose_project_token(token, project_id, environment_id)}",
                file=sys.stderr,
            )
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
