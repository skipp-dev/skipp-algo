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

Auth: `RAILWAY_API_TOKEN` — an ACCOUNT/workspace token, `Authorization:
Bearer` — plus `RAILWAY_PROJECT_ID` + `RAILWAY_ENVIRONMENT_ID`, and the
service id `RAILWAY_LIVE_OVERLAY_SERVICE_ID` defaulting to the production
service.

A Railway PROJECT token cannot drive this guard, and that is measured, not
assumed: sent with its correct `Project-Access-Token` header it resolves
`projectToken { projectId environmentId }` to this exact project, yet the
same token gets "Not Authorized" for `deploymentTriggers` (run 30831201160,
2026-08-03), while an account-scoped session token reading the identical
query with identical variables gets data. The docs document no per-query
scope table, so this refutation is the only authority. #4343 briefly
PREFERRED a project token on the assumption that project-scoped meant
query-complete; that preference made the guard uncurably red whenever the
project-token secret was set, and was removed the same day.

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
    token.

    Kept although main() no longer takes project tokens: the header property is
    real and measured, and the next person who reaches for a project token here
    should find the refutation (see the module docstring) instead of the API's
    unhelpful error.
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


# Asks the only question this guard actually needs answered: can the credential
# SEE the project? NOT `{ me }`. Railway's docs are explicit that `me` "cannot
# be used with a workspace or project token because the data returned is scoped
# to your personal account" — so a perfectly good WORKSPACE token fails it, and
# the probe would report a healthy credential as dead.
#
# That is not hypothetical. Measured 2026-08-03 across four credentials: the
# operator's CLI session reads the project, his personal ACCOUNT token answers
# `me` but cannot see the project ("scope, not identity"), and a project token
# answers neither. The account token's failure is the informative one — it means
# skipp-algo lives in a WORKSPACE, not in the personal account, so a workspace
# token is the correct credential here and `me` is exactly the wrong question.
_PROJECT_VISIBILITY_QUERY = "query($projectId: String!) { project(id: $projectId) { name } }"


def _diagnose_account_token(token: str, project_id: str, timeout: float = 15.0) -> str:
    """Say which fault Railway's bare "Not Authorized" is hiding.

    ``deploymentTriggers`` answers the same line for a credential that cannot
    reach this project at all and for one that reaches it but is denied this
    field — different fixes, identical message. So the probe asks whether the
    credential can SEE the project.

    It used to ask ``{ me }``. That was wrong in a way this guard could not
    survive: Railway documents that ``me`` "cannot be used with a workspace or
    project token because the data returned is scoped to your personal
    account", so a healthy WORKSPACE token — the credential this project
    actually needs — was reported as "does not authenticate at all". Measured
    2026-08-03: the operator's personal account token answers ``me`` yet cannot
    see the project, which is precisely how we learned the project lives in a
    workspace rather than in the personal account.

    Returns one operator-facing line and never echoes the token or project data.
    """
    req = urllib.request.Request(
        _GRAPHQL_ENDPOINT,
        data=json.dumps(
            {"query": _PROJECT_VISIBILITY_QUERY, "variables": {"projectId": project_id}}
        ).encode("utf-8"),
        headers={
            **_auth_header(token, "account"),
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

    if body.get("errors") or not ((body.get("data") or {}).get("project") or {}).get("name"):
        return (
            "RAILWAY_API_TOKEN cannot see the project in RAILWAY_PROJECT_ID at all — "
            "wrong workspace, revoked, or mistyped. skipp-algo lives in a WORKSPACE, "
            "so issue a WORKSPACE token for the workspace that owns it (a personal "
            "account token does not reach it; project tokens cannot read "
            "deploymentTriggers either: #4345)"
        )
    return (
        "RAILWAY_API_TOKEN CAN see the project — so the refusal is field-level: this "
        "credential reaches the project but is denied deploymentTriggers. Escalate the "
        "token's permissions or query a different field"
    )


def main() -> int:
    # Deliberately NOT reading RAILWAY_PROJECT_ACCESS_TOKEN: project tokens
    # cannot query deploymentTriggers (measured, see module docstring), and a
    # preferred-but-unauthorized credential kept this guard red no matter what
    # else was configured.
    token = os.environ.get("RAILWAY_API_TOKEN")
    project_id = os.environ.get("RAILWAY_PROJECT_ID")
    environment_id = os.environ.get("RAILWAY_ENVIRONMENT_ID")
    service_id = os.environ.get("RAILWAY_LIVE_OVERLAY_SERVICE_ID", _DEFAULT_SERVICE_ID)

    if not (token and project_id and environment_id):
        print(
            "SKIP: RAILWAY_API_TOKEN (account token) / RAILWAY_PROJECT_ID / "
            "RAILWAY_ENVIRONMENT_ID not all set — deploy-trigger drift guard "
            "did not run.",
        )
        return 0

    try:
        triggers = _fetch_triggers(
            token, project_id, environment_id, service_id, auth_kind="account"
        )
    except (urllib.error.URLError, RuntimeError, ValueError, KeyError) as exc:
        print(
            "ERROR: could not query Railway deployment triggers using the "
            f"account token in RAILWAY_API_TOKEN: {exc}",
            file=sys.stderr,
        )
        # "Not Authorized" alone cannot say whether the credential is dead or
        # merely outside this project's workspace — two different fixes. Ask
        # `me`, which resolves against the token by itself, and print the
        # answer next to the failure instead of leaving it to the next round.
        print(
            f"DIAGNOSIS: {_diagnose_account_token(token, project_id)}",
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
