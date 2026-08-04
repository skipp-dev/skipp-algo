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

Railway answers "Not Authorized" for an unresolvable serviceId, not just for a
credential it rejects — and that cost this guard a week. From 2026-07-31 it sent
an EMPTY service id (a missing Actions secret arrives as "", #4359), so every
run came back "Not Authorized" on `deploymentTriggers` and the failure read as a
permission wall. Three token types were issued chasing it; #4349 proved the
credential, the project and the environment all correct, which should have been
the clue. With the id fixed, the same credential reads the same field
(run 30847017825).

Two refutations worth keeping, both measured 2026-08-03 with the correct id
(run 30847141633, both credentials, one run): every candidate field is readable,
so there is NO field-level denial — and `serviceInstance.source.repo` is
`skipp-dev/skipp-algo` while `deploymentTriggers` is EMPTY. A connected repo is
therefore NOT evidence of a native trigger: the 2026-07-24 cleanup removed the
trigger and left the repo association. A guard built on `source.repo` (#4354)
would have reported drift every day, so it was removed the same day it shipped.

Exit codes:
  0  no native deploy trigger (healthy)  OR  the deployment is declared
     unconfigured (_DEPLOYMENT_IS_CONFIGURED = False) and an input is missing
     (skipped)
  1  a native deploy trigger exists (drift — remove it, see OPS.md)
  2  could not verify: auth/network/API error or unreadable response, OR an
     input is missing while _DEPLOYMENT_IS_CONFIGURED is True (a deleted or
     mistyped secret, not a healthy state)

Skipping on an absent input mirrors `deploy-live-overlay-daemon.yml`, which
no-ops without its Railway secret — but only while the deployment is declared
unconfigured. With the declaration True (the production default), a missing
input cannot false-fail as a healthy skip; it exits 2.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

# Matches the railway_metrics bridge's proven-in-production endpoint. Overridable
# for tests / a future endpoint move via RAILWAY_GRAPHQL_ENDPOINT. `or`, not a
# get() default, for the same reason as service_id below: an env var mapped to a
# missing Actions secret arrives as "", which a two-argument default accepts.
_GRAPHQL_ENDPOINT = (
    os.environ.get("RAILWAY_GRAPHQL_ENDPOINT") or "https://backboard.railway.com/graphql/v2"
)
# Production live_overlay_daemon service (skipp-dev's Projects / skipp-algo).
_DEFAULT_SERVICE_ID = "705582c5-ba8b-4c6e-848c-33bffe0a61b0"

# Does the deployment this guard watches exist? This is a DECLARATION, not a
# probe — the guard cannot ask "am I supposed to be configured?" of an API it
# needs the missing credential to reach.
#
# It exists because exit 0 meant two different things: "verified, no drift" and
# "not configured, did not run". A deleted Actions secret therefore produced a
# permanent green whose message reads exactly like the designed dormant state.
# With this, a missing input is exit 2 while the daemon is deployed, and the
# dormant state requires a reviewed repo change instead of a quiet one in the
# GitHub settings UI. `test_the_declaration_cannot_be_flipped_to_silence_the
# _guard` couples it to the deploy workflow's existence so it cannot be used
# as a mute button.
_DEPLOYMENT_IS_CONFIGURED = True

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


def _graphql(
    query: str,
    variables: dict[str, str],
    token: str,
    auth_kind: str = "account",
    timeout: float = 15.0,
) -> dict:
    """POST one GraphQL document and return the decoded body, errors included.

    The single HTTP call site in this module: the guard query, the diagnosis
    probe and the credential-capability probe all go through here, so the
    Cloudflare User-Agent workaround below cannot be forgotten by one of them
    (and the urlopen ledger pins one line rather than three).
    """
    req = urllib.request.Request(
        _GRAPHQL_ENDPOINT,
        data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
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
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 - literal endpoint
        return json.loads(resp.read().decode("utf-8"))


def _fetch_triggers(
    token: str,
    project_id: str,
    environment_id: str,
    service_id: str,
    timeout: float = 15.0,
    auth_kind: str = "account",
) -> list[dict]:
    """Return the service's deployment-trigger nodes. Raises on API/transport error."""
    body = _graphql(
        _QUERY,
        {
            "projectId": project_id,
            "environmentId": environment_id,
            "serviceId": service_id,
        },
        token,
        auth_kind=auth_kind,
        timeout=timeout,
    )
    if not isinstance(body, dict):
        raise RuntimeError(f"Railway returned non-object JSON: {str(body)[:200]}")
    if body.get("errors"):
        raise RuntimeError(f"Railway API errors: {body['errors']}")
    # Assert the shape; do NOT default it. The previous line was
    #     (body.get("data") or {}).get("deploymentTriggers", {}).get("edges") or []
    # which reads a body with no `data` at all as "no triggers" — fail-OPEN in a
    # fail-closed guard, and measured: `{}` and `{"data": null}` both printed
    # "OK: no native deploy trigger" without having verified anything. A
    # spec-conforming server pairs `data: null` with `errors` (raised above), but
    # this endpoint sits behind Cloudflare, which is exactly where unexpected
    # 200-with-JSON bodies come from — and "cannot parse" must be exit 2, never
    # exit 0 or 1.
    triggers = (body.get("data") or {}).get("deploymentTriggers")
    if not isinstance(triggers, dict) or not isinstance(triggers.get("edges"), list):
        raise RuntimeError(
            f"unexpected deploymentTriggers shape, cannot verify: {str(body)[:200]}"
        )
    return [e["node"] for e in triggers["edges"] if isinstance(e, dict) and e.get("node")]


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
_PROJECT_VISIBILITY_QUERY = (
    "query($projectId: String!) { project(id: $projectId) { name"
    " environments { edges { node { id } } } } }"
)


def _credential_fingerprint(token: str) -> str:
    """A comparable, non-reversible label for the credential the runner received.

    Written 2026-08-03, when the operator's workspace token answered
    ``deploymentTriggers`` from his machine and was refused from the runner --
    apparently the same query, the same header, the same secret. Two worlds no
    log line could tell apart: a DIFFERENT value reaches the runner, or the same
    one is treated differently.

    It was neither. The runner sent an EMPTY serviceId (#4359) and Railway
    answers that with the same "Not Authorized" it gives a rejected credential.
    Kept anyway: it costs one line, it took the credential out of the suspect
    list for good, and the whole reason that week was expensive is that one
    error string stood for four different faults.

    So publish something comparable. sha256 truncated to 8 hex chars is not
    reversible and does not narrow a brute-force search in any useful way,
    while the operator can run
    ``printf '%s' "$TOKEN" | shasum -a 256 | cut -c1-8`` and compare directly.
    Length is included because the historical failure was whitespace.
    """
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]
    return f"len={len(token)} sha256[:8]={digest}"


def _diagnose_account_token(
    token: str, project_id: str, environment_id: str = "", timeout: float = 15.0
) -> str:
    """Say which fault Railway's bare "Not Authorized" is hiding.

    ``deploymentTriggers`` answers the same line for at least four faults: a
    credential that cannot reach this project, one that reaches it but lacks the
    field, an environment id from another project, and — the one that actually
    happened, #4359 — a serviceId that resolves to nothing. Different fixes,
    identical message. So the probe asks whether the credential can SEE the
    project, which separates the first from the rest.

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
    try:
        body = _graphql(
            _PROJECT_VISIBILITY_QUERY,
            {"projectId": project_id},
            token,
            auth_kind="account",
            timeout=timeout,
        )
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return f"follow-up probe could not run ({type(exc).__name__}) — diagnosis inconclusive"

    # A non-object body would raise AttributeError here — out of this function's
    # except tuple, out of main()'s, and out of the process with status 1, which
    # this guard defines as DRIFT. The diagnosis exists to explain a failure; it
    # must not be able to convert one into a false verdict.
    if not isinstance(body, dict):
        return "follow-up probe got non-object JSON — diagnosis inconclusive"

    if body.get("errors") or not ((body.get("data") or {}).get("project") or {}).get("name"):
        return (
            "RAILWAY_API_TOKEN cannot see the project in RAILWAY_PROJECT_ID at all — "
            "wrong workspace, revoked, or mistyped. skipp-algo lives in a WORKSPACE, "
            "so issue a WORKSPACE token for the workspace that owns it (a personal "
            "account token does not reach it; project tokens cannot read "
            "deploymentTriggers either: #4345)"
        )
    # The project resolved, so RAILWAY_PROJECT_ID and the credential are both
    # right. deploymentTriggers takes an ENVIRONMENT too, and nothing above
    # touches it — an environment id that belongs to some other project is
    # answered with the same "Not Authorized", so check membership before
    # blaming the token's permissions.
    environments = {
        (edge.get("node") or {}).get("id")
        for edge in (
            ((body.get("data") or {}).get("project") or {}).get("environments") or {}
        ).get("edges")
        or []
    }
    if environment_id and environments and environment_id not in environments:
        return (
            "RAILWAY_API_TOKEN and RAILWAY_PROJECT_ID are both correct — the project "
            "resolves — but RAILWAY_ENVIRONMENT_ID is NOT one of this project's "
            f"{len(environments)} environments, and Railway answers that with the same "
            "'Not Authorized'. Re-read it from `railway status` and re-set the secret"
        )
    return (
        "RAILWAY_API_TOKEN CAN see the project and RAILWAY_ENVIRONMENT_ID belongs to "
        "it, so the credential is NOT the fault. Suspect the service id next: an "
        "unresolvable serviceId gets the same 'Not Authorized', and that — not a "
        "permission wall — is what this guard chased for a week (#4359). Run the "
        "workflow with probe_credentials=true to see which fields answer"
    )


# Candidate ways to answer "is this service natively repo-triggered?", measured
# against every credential this repo owns. Built to find a substitute for a
# `deploymentTriggers` that looked permanently denied; it earned its keep twice
# over instead, and neither time the way it was meant to.
#
# Run 30843047407 (empty serviceId, before #4359): deploymentTriggers and
# serviceInstance.source DENIED, project.services[].source OK. Read as a
# field-level permission wall. It was not one — the id was empty, and every
# query that named a service failed for that reason.
#
# Run 30847141633 (correct serviceId): ALL FOUR fields OK for BOTH credentials,
# which refuted the permission story, and `serviceInstance.source.repo` came
# back "skipp-dev/skipp-algo" while `deploymentTriggers` came back EMPTY —
# refuting the substitute itself. A connected repo is not a native trigger; the
# 2026-07-24 cleanup removed the trigger and left the repo association. The
# guard built on that equivalence (#4354) would have cried drift daily and was
# removed the same day.
#
# Keep the probe. Twice now the thing that unblocked this was one run that
# reported what each credential can actually read, side by side.
#
# `deployments` is on the list because it is PROVEN readable from CI — the
# deploy workflow polls it after every `railway up` with the project token
# (deploy-live-overlay-daemon.yml). Its `meta` may carry the origin of a
# deployment, which would make it a tripwire even if no config field is legible.
_PROBE_QUERIES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("deploymentTriggers", _QUERY, ("projectId", "environmentId", "serviceId")),
    (
        "serviceInstance.source",
        "query($environmentId: String!, $serviceId: String!) {"
        " serviceInstance(environmentId: $environmentId, serviceId: $serviceId)"
        " { id source { repo image } } }",
        ("environmentId", "serviceId"),
    ),
    (
        "project.services[].source",
        "query($projectId: String!) { project(id: $projectId) { services { edges"
        " { node { id name serviceInstances { edges { node { environmentId"
        " source { repo image } } } } } } } } }",
        ("projectId",),
    ),
    (
        "deployments.meta",
        "query($projectId: String!, $environmentId: String!, $serviceId: String!) {"
        " deployments(first: 1, input: { projectId: $projectId,"
        " environmentId: $environmentId, serviceId: $serviceId })"
        " { edges { node { id status createdAt meta } } } }",
        ("projectId", "environmentId", "serviceId"),
    ),
)


# Leaf values printed verbatim. Everything else is reported by TYPE, never by
# value: one of the probe's four queries is `deployments.meta`, a free-form
# object whose contents Railway decides, and this prints into a CI log. GitHub
# masks registered secrets; it cannot mask what it was never told about.
#
# The allowlist is the set of fields that actually answered a question here:
# `repo`/`image` refuted the source-as-trigger equivalence, `edges` counts
# answered "is there a trigger", and id/name/status/branch/provider identify
# WHICH object answered.
_PAYLOAD_FIELDS = frozenset(
    {"id", "name", "repo", "image", "status", "branch", "provider", "createdAt"}
)
_PAYLOAD_MAX = 400
_PAYLOAD_MAX_DEPTH = 5


def _summarize(value: object, key: str = "", depth: int = 0) -> str:
    """Structure in full, allowlisted leaves verbatim, everything else by type."""
    if depth > _PAYLOAD_MAX_DEPTH:
        return "…"
    if isinstance(value, dict):
        return (
            "{"
            + ", ".join(
                f"{k}={_summarize(v, k, depth + 1)}" for k, v in sorted(value.items())
            )
            + "}"
        )
    if isinstance(value, list):
        if not value:
            return "[0 items]"
        # One representative element at the SAME depth: unwrapping the list
        # exposes a repeated shape, not a new nesting level the way a dict key
        # is one — the depth budget must not charge twice for the one hop
        # `deployments.edges[0].node` needs before reaching real fields.
        return f"[{len(value)} items: {_summarize(value[0], key, depth)}]"
    if value is None or isinstance(value, bool):
        return str(value)
    if key in _PAYLOAD_FIELDS:
        return json.dumps(value)[:80]
    return f"<{type(value).__name__}>"


def _classify(body: dict) -> tuple[str, str]:
    """Split Railway's failures into the three that need different fixes.

    DENIED means the field exists and this credential may not read it — escalate
    or replace the credential. SCHEMA means the field name is wrong — my query is
    the bug, not the token. Conflating them is exactly how a guessed field name
    would masquerade as a permission wall for another week.

    SCHEMA therefore wins a mixed body. A query naming four fields can come back
    with one "Cannot query field" and one "Not Authorized"; testing DENIED first
    reported that as a pure permission wall, which is the conflation this
    docstring promises to prevent, in the one case where it matters most.

    The OK detail is a SUMMARY, not the payload: see `_summarize`. A probe that
    prints whatever a third-party API returns is a log-exfiltration surface, and
    the probe's value was always the shape of the answer, not its contents.
    """
    if not isinstance(body, dict):
        return "ERROR", f"non-object JSON response: {str(body)[:200]}"
    errors = body.get("errors") or []
    if not errors:
        summary = _summarize(body.get("data") or {})
        return "OK", summary[:_PAYLOAD_MAX] + ("…" if len(summary) > _PAYLOAD_MAX else "")
    # An error object without `message` must not degrade to an empty detail —
    # that prints as a verdict with no evidence behind it.
    messages = "; ".join(
        str(err.get("message") or err) if isinstance(err, dict) else str(err)
        for err in errors
    )
    if any(
        marker in messages
        for marker in ("Cannot query field", "Unknown argument", "Unknown type")
    ):
        return ("SCHEMA+DENIED" if "Not Authorized" in messages else "SCHEMA"), messages[
            :200
        ]
    if "Not Authorized" in messages:
        return "DENIED", messages[:200]
    return "ERROR", messages[:200]


def _probe(project_id: str, environment_id: str, service_id: str) -> int:
    """Print which candidate query each available credential may actually read.

    Read-only and always exit 0: this is a measurement, and a measurement that
    can turn the daily guard red would not get run.
    """
    variables = {
        "projectId": project_id,
        "environmentId": environment_id,
        "serviceId": service_id,
    }
    credentials = [
        ("account", "RAILWAY_API_TOKEN", os.environ.get("RAILWAY_API_TOKEN")),
        # The deploy workflow's project token, sent with its own header. It is
        # the only credential proven to answer a Railway query from a runner.
        ("project", "RAILWAY_TOKEN", os.environ.get("RAILWAY_TOKEN")),
    ]
    for auth_kind, env_name, token in credentials:
        if not token:
            print(f"PROBE {env_name}: not set — skipped")
            continue
        print(f"PROBE {env_name} ({auth_kind} header): {_credential_fingerprint(token)}")
        for name, query, needed in _PROBE_QUERIES:
            try:
                body = _graphql(
                    query,
                    {key: variables[key] for key in needed},
                    token,
                    auth_kind=auth_kind,
                )
            except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                status, detail = "TRANSPORT", f"{type(exc).__name__}: {exc}"
            else:
                status, detail = _classify(body)
            print(f"  {name:<28} {status:<9} {detail}")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Deliberately NOT reading RAILWAY_PROJECT_ACCESS_TOKEN: project tokens
    # cannot query deploymentTriggers (measured, see module docstring), and a
    # preferred-but-unauthorized credential kept this guard red no matter what
    # else was configured.
    token = os.environ.get("RAILWAY_API_TOKEN")
    project_id = os.environ.get("RAILWAY_PROJECT_ID")
    environment_id = os.environ.get("RAILWAY_ENVIRONMENT_ID")
    # `or`, not a get() default. GitHub Actions sets an env var mapped to a
    # MISSING secret to the empty string, so the two-argument default never
    # applied and this guard asked Railway about service "" — invisible for as
    # long as deploymentTriggers answered "Not Authorized" first, and surfaced
    # the moment the readable fallback had to locate the service (run
    # 30845071629: "service  has no instance ... among the project's 10").
    service_id = os.environ.get("RAILWAY_LIVE_OVERLAY_SERVICE_ID") or _DEFAULT_SERVICE_ID

    if "--probe" in (sys.argv[1:] if argv is None else argv):
        if not (project_id and environment_id):
            print(
                "SKIP: RAILWAY_PROJECT_ID / RAILWAY_ENVIRONMENT_ID not set — "
                "credential probe did not run."
            )
            return 0
        return _probe(project_id, environment_id, service_id)

    # Name the ones that are actually missing. The old line listed all three
    # whichever was empty, so deleting a single secret would have parked the
    # guard on a permanent silent green with a message that looks like the
    # designed dormant state — a fresh instance of the very class this guard
    # spent four commits learning ("a missing Actions secret arrives as '' ").
    missing = [
        name
        for name, value in (
            ("RAILWAY_API_TOKEN", token),
            ("RAILWAY_PROJECT_ID", project_id),
            ("RAILWAY_ENVIRONMENT_ID", environment_id),
        )
        if not value
    ]
    if missing and _DEPLOYMENT_IS_CONFIGURED:
        print(
            f"ERROR: {', '.join(missing)} not set, but this repo declares the "
            "live_overlay_daemon deployment as configured "
            "(_DEPLOYMENT_IS_CONFIGURED). A deleted or mistyped secret is not a "
            "healthy state — the guard has verified NOTHING. Restore the secret, "
            "or retire the deployment and flip the declaration in a reviewed PR.",
            file=sys.stderr,
        )
        return 2
    if missing:
        print(
            f"SKIP: {', '.join(missing)} not set and the deployment is declared "
            "unconfigured — deploy-trigger drift guard did not run.",
        )
        return 0

    try:
        triggers = _fetch_triggers(
            token, project_id, environment_id, service_id, auth_kind="account"
        )
    # TimeoutError explicitly, like the two other handlers in this file: urllib
    # wraps a CONNECT-phase timeout in URLError, but a timeout during
    # resp.read() propagates as a bare TimeoutError. Uncaught, it escapes with a
    # traceback and a process exit status of 1 — which this guard defines as
    # DRIFT. A network stall on the daily cron would send the operator into the
    # Railway console hunting a trigger that does not exist.
    except (
        urllib.error.URLError,
        TimeoutError,
        RuntimeError,
        ValueError,
        KeyError,
    ) as exc:
        print(
            "ERROR: could not query Railway deployment triggers using the "
            f"account token in RAILWAY_API_TOKEN: {exc}",
            file=sys.stderr,
        )
        # "Not Authorized" alone cannot say whether the credential is dead or
        # merely outside this project's workspace — two different fixes. Ask
        # whether it can SEE the project and print the answer next to the
        # failure instead of leaving it to the next round.
        print(
            f"DIAGNOSIS: {_diagnose_account_token(token, project_id, environment_id)}",
            file=sys.stderr,
        )
        # Which credential arrived here, comparably and without revealing it.
        print(
            f"CREDENTIAL: {_credential_fingerprint(token)} "
            "(compare locally: printf '%s' \"$TOKEN\" | shasum -a 256 | cut -c1-8)",
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
