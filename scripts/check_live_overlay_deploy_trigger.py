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

Two questions, because Railway only answers the second one. Measured 2026-08-03
(run 30843047407, both of this repo's credentials, one run): `deploymentTriggers`
and `serviceInstance.source` are both DENIED while `project.services[]
.serviceInstances[].source` is readable — and the project resolves and the
environment belongs to it, so this is not a credential fault (#4349). The guard
therefore asks the authoritative field first and, when it is refused, asks what a
native trigger is CREATED from: a GitHub repo connected to the service. That is
a substitute, not the same field, and the guard says so in every verdict it
reaches that way.

Exit codes:
  0  no native deploy trigger (healthy)  OR  token not configured (skipped)
  1  a native deploy trigger exists, or a GitHub repo is connected to the
     service in this environment (drift — disconnect it, see OPS.md)
  2  neither question could be answered, or the service could not be located
     (auth/network/API error, or wrong service/environment id)

Skipping on an absent token mirrors `deploy-live-overlay-daemon.yml`, which
no-ops without its Railway secret: an unconfigured guard must not false-fail.
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
    if body.get("errors"):
        raise RuntimeError(f"Railway API errors: {body['errors']}")
    edges = (body.get("data") or {}).get("deploymentTriggers", {}).get("edges") or []
    return [e["node"] for e in edges if e.get("node")]


# The fallback question, and the only one Railway lets this repo ask.
# Measured 2026-08-03, run 30843047407, BOTH credentials, same run:
#
#     deploymentTriggers        DENIED
#     serviceInstance.source    DENIED
#     project.services[].source OK
#     deployments.meta          OK (empty for this service)
#
# So the authoritative field is unreachable and this is the substitute. It is a
# substitute, not the same field: a service's `source.repo` is what Railway
# connects a GitHub repository to, and connecting one is what CREATES the native
# deploy trigger — that is the shape the 2026-07-24 drift actually had. The API
# will not confirm the equivalence from here (the field that would is the denied
# one), so the guard says which question it answered whenever it answers this
# one, and never claims to have read deploymentTriggers.
_SERVICE_SOURCE_QUERY = (
    "query($projectId: String!) { project(id: $projectId) { services { edges {"
    " node { id name serviceInstances { edges { node { environmentId"
    " source { repo image } } } } } } } } }"
)


class _ServiceNotFoundError(RuntimeError):
    """Our service/environment pair is not in the project's service list.

    Its own type because it must NOT read as "no repo connected": an unlocatable
    service is an unanswered question, and answering it "healthy" would make the
    guard pass hardest exactly when its inputs are wrong.
    """


def _fetch_service_source(
    token: str,
    project_id: str,
    environment_id: str,
    service_id: str,
    timeout: float = 15.0,
    auth_kind: str = "account",
) -> dict:
    """Return `{name, repo, image}` for our service instance in our environment."""
    body = _graphql(
        _SERVICE_SOURCE_QUERY,
        {"projectId": project_id},
        token,
        auth_kind=auth_kind,
        timeout=timeout,
    )
    if body.get("errors"):
        raise RuntimeError(f"Railway API errors: {body['errors']}")
    services = (
        ((body.get("data") or {}).get("project") or {}).get("services") or {}
    ).get("edges") or []
    for edge in services:
        node = edge.get("node") or {}
        if node.get("id") != service_id:
            continue
        for inst_edge in (node.get("serviceInstances") or {}).get("edges") or []:
            inst = inst_edge.get("node") or {}
            # Instances exist per environment; a repo connected in staging is
            # not this environment's trigger.
            if inst.get("environmentId") != environment_id:
                continue
            source = inst.get("source") or {}
            return {
                "name": node.get("name"),
                "repo": source.get("repo"),
                "image": source.get("image"),
            }
    raise _ServiceNotFoundError(
        f"service {service_id} has no instance in environment {environment_id} "
        f"among the project's {len(services)} services"
    )


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

    Measured 2026-08-03: the operator's workspace token answers
    ``deploymentTriggers`` from his machine and is refused from the runner --
    same query, same variables, same header, allegedly the same secret. That
    leaves exactly two worlds, and no log line could tell them apart: the
    runner receives a DIFFERENT value, or it receives the same one and Railway
    treats the caller differently.

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
        "it — so the refusal is field-level: this credential reaches the project but "
        "is denied deploymentTriggers. Escalate the token's permissions or query a "
        "different field"
    )


# Candidate ways to answer "is this service natively repo-triggered?", to be
# measured against every credential this repo owns. `deploymentTriggers` is the
# authoritative one and is DENIED to both of them (run 30840756670 for the
# workspace token, 30831201160 for the project token) — the project resolves,
# the environment belongs to it, and Railway still refuses the field. So the
# question is no longer "which credential" but "which readable field carries
# the same fact", and that is a measurement, not a guess: a wrong field name
# and a denied field produce different errors, and this probe separates them.
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


def _classify(body: dict) -> tuple[str, str]:
    """Split Railway's failures into the three that need different fixes.

    DENIED means the field exists and this credential may not read it — escalate
    or replace the credential. SCHEMA means the field name is wrong — my query is
    the bug, not the token. Conflating them is exactly how a guessed field name
    would masquerade as a permission wall for another week.
    """
    errors = body.get("errors") or []
    if not errors:
        payload = json.dumps(body.get("data") or {}, sort_keys=True)
        return "OK", payload[:400] + ("…" if len(payload) > 400 else "")
    messages = "; ".join(str(err.get("message", "")) for err in errors)
    if "Not Authorized" in messages:
        return "DENIED", messages[:200]
    if any(
        marker in messages
        for marker in ("Cannot query field", "Unknown argument", "Unknown type")
    ):
        return "SCHEMA", messages[:200]
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
        # Expected as of 2026-08-03: Railway denies `deploymentTriggers` to both
        # of this repo's credentials while the project itself resolves and the
        # environment belongs to it (runs 30840756670 / 30843047407). So do not
        # give up here — ask the readable question, and only report failure if
        # that one fails too. The note stays on stderr because a guard that
        # silently substitutes its question is worse than one that cannot run.
        print(
            "NOTE: deploymentTriggers is not readable with this credential "
            f"({exc}) — falling back to the service's configured source, which "
            "is what a native GitHub trigger is created from.",
            file=sys.stderr,
        )
        try:
            source = _fetch_service_source(
                token, project_id, environment_id, service_id, auth_kind="account"
            )
        except (
            urllib.error.URLError,
            RuntimeError,
            ValueError,
            KeyError,
        ) as fallback_exc:
            return _report_unrunnable(token, project_id, environment_id, fallback_exc)
        if not source.get("repo"):
            print(
                f"OK: {source.get('name') or 'live_overlay_daemon'} has no GitHub "
                "repo connected in this environment, so Railway cannot have "
                "created a native deploy trigger for it (source.repo=None, "
                f"source.image={source.get('image')!r}). deploymentTriggers itself "
                "is denied to this credential — this is the readable substitute, "
                "not that field."
            )
            return 0
        print(
            "DRIFT: live_overlay_daemon has a GitHub repo connected in Railway "
            f"(source.repo={source['repo']!r}) — that is what creates a native "
            "deploy trigger, which has no path filter and redeploys on EVERY "
            "push to its branch, bypassing the path-filtered CI workflow. "
            "Disconnect it (see services/live_overlay_daemon/OPS.md).",
            file=sys.stderr,
        )
        return 1

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


def _report_unrunnable(
    token: str, project_id: str, environment_id: str, exc: Exception
) -> int:
    """Neither question could be answered — say which fault, name the credential."""
    if isinstance(exc, _ServiceNotFoundError):
        print(
            f"ERROR: {exc} — the guard could not locate the service it is meant "
            "to watch, so it has NOT verified anything. Check "
            "RAILWAY_LIVE_OVERLAY_SERVICE_ID / RAILWAY_ENVIRONMENT_ID.",
            file=sys.stderr,
        )
    else:
        print(
            "ERROR: could not query Railway using the account token in "
            f"RAILWAY_API_TOKEN — neither deploymentTriggers nor the service "
            f"source: {exc}",
            file=sys.stderr,
        )
    # "Not Authorized" alone cannot say whether the credential is dead or merely
    # outside this project's workspace — two different fixes. Ask whether it can
    # SEE the project, and print the answer next to the failure instead of
    # leaving it to the next round.
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


if __name__ == "__main__":
    raise SystemExit(main())
