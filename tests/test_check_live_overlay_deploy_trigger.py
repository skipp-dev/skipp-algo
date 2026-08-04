"""The Railway deploy-trigger drift guard's decision logic.

Root cause it exists for (2026-07-24): the live_overlay_daemon Railway service
had a native GitHub deploy trigger (branch=main, no path filter), so every push
to main redeployed the daemon — ~23/day, most touching nothing in it — wiping
the bar cache and resetting uptime. The service is meant to be CI-only
(source=none); this guard fails if a native trigger reappears.

Network is mocked: these pin the exit-code contract, not Railway connectivity.
"""
from __future__ import annotations

import hashlib
import http.client
import importlib.util
import json
import ssl
import urllib.error
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_live_overlay_deploy_trigger.py"


def _load():
    spec = importlib.util.spec_from_file_location("deploy_trigger_guard", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def guard(monkeypatch):
    mod = _load()
    monkeypatch.delenv("RAILWAY_PROJECT_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("RAILWAY_API_TOKEN", "t")
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "p")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "e")
    return mod


def test_no_trigger_is_healthy(guard, monkeypatch):
    monkeypatch.setattr(guard, "_fetch_triggers", lambda *a, **k: [])
    assert guard.main() == 0


def test_native_trigger_is_drift(guard, monkeypatch):
    monkeypatch.setattr(
        guard,
        "_fetch_triggers",
        lambda *a, **k: [
            {"id": "x", "provider": "github", "repository": "skipp-dev/skipp-algo", "branch": "main"}
        ],
    )
    assert guard.main() == 1


def test_missing_token_skips_without_failing(monkeypatch):
    """Dormancy is now DECLARED (_DEPLOYMENT_IS_CONFIGURED), not inferred from a
    missing token — so a truly dormant deployment must say so explicitly."""
    mod = _load()
    monkeypatch.setattr(mod, "_DEPLOYMENT_IS_CONFIGURED", False)
    # BOTH token variables: with the project-token path added, deleting only
    # RAILWAY_API_TOKEN would let an ambient RAILWAY_PROJECT_ACCESS_TOKEN keep
    # the guard live and this test would assert the wrong thing.
    monkeypatch.delenv("RAILWAY_PROJECT_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("RAILWAY_API_TOKEN", raising=False)
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "p")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "e")
    # No token -> dormant guard must return 0 (mirrors deploy workflow no-op),
    # and must NOT reach the network.
    def _boom(*a, **k):  # pragma: no cover - must not be called
        raise AssertionError("network hit despite missing token")

    monkeypatch.setattr(mod, "_fetch_triggers", _boom)
    assert mod.main() == 0


def test_a_configured_project_token_is_ignored_not_preferred(guard, monkeypatch):
    """Project tokens cannot query deploymentTriggers — measured, not assumed.

    Run 30831201160 (2026-08-03): the operator's project token, sent with its
    correct Project-Access-Token header, resolves ``projectToken`` to this
    exact project yet gets "Not Authorized" for ``deploymentTriggers``; an
    account-scoped token reading the identical query returns data. #4343
    preferred the project token for a few hours, which made the guard uncurably
    red while that secret was set. main() must therefore not read it at all.
    """
    monkeypatch.setenv("RAILWAY_PROJECT_ACCESS_TOKEN", "proj-tok")
    seen: dict = {}

    def _capture(token, *a, **k):
        seen["token"] = token
        seen["auth_kind"] = k.get("auth_kind")
        return []

    monkeypatch.setattr(guard, "_fetch_triggers", _capture)
    assert guard.main() == 0
    assert seen == {"token": "t", "auth_kind": "account"}


def test_auth_header_still_knows_both_railway_header_schemes(guard):
    """The header property is real and stays documented in code.

    A project token sent as Bearer fails even ``{ me }`` with the same bare
    "Not Authorized" an unauthenticated request gets — whoever next reaches for
    a project token here should find working header code next to the measured
    refutation, not rediscover both from the API's unhelpful error.
    """
    assert guard._auth_header("proj-tok", "project") == {"Project-Access-Token": "proj-tok"}
    assert guard._auth_header("acct-tok", "account") == {"Authorization": "Bearer acct-tok"}


def test_api_error_is_inconclusive_not_pass(guard, monkeypatch):
    def _raise(*a, **k):
        raise RuntimeError("Railway API errors: [...]")

    monkeypatch.setattr(guard, "_fetch_triggers", _raise)
    # rc=2 (inconclusive) is distinct from 0 (healthy) so an auth/API break
    # never masquerades as "no drift".
    assert guard.main() == 2


def _diag_resp(payload: dict):
    class _Resp:
        def read(self):
            return json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return _Resp()


def _run_failing(guard, monkeypatch, diag_payload, *, exc=None):
    """Drive main() down the failure path and let the diagnosis probe answer."""

    def _raise(*a, **k):
        raise RuntimeError("Railway API errors: [{'message': 'Not Authorized'}]")

    monkeypatch.setattr(guard, "_fetch_triggers", _raise)

    def _urlopen(req, timeout=0):
        if exc is not None:
            raise exc
        # The probe must authenticate the same way the failing call did.
        assert req.headers.get("Authorization") == "Bearer t"
        return _diag_resp(diag_payload)

    monkeypatch.setattr(guard.urllib.request, "urlopen", _urlopen)
    return guard.main()


def test_failure_names_the_credential_it_used(guard, monkeypatch, capsys):
    """The old message never said which token was tried.

    With three auth layers fixed in one day (Cloudflare UA #4334, project-token
    header #4343, project-token refutation #4345) each round re-derived the
    credential from the workflow file. Print it.
    """
    rc = _run_failing(guard, monkeypatch, {"data": {"project": {"name": "skipp-algo"}}})
    assert rc == 2
    assert "account token in RAILWAY_API_TOKEN" in capsys.readouterr().err


def test_the_probe_asks_about_the_project_never_about_the_person(guard, monkeypatch):
    """`me` is the wrong question and Railway documents why.

    "This query cannot be used with a workspace or project token because the
    data returned is scoped to your personal account" (docs.railway.com/guides/
    public-api). skipp-algo lives in a WORKSPACE — measured 2026-08-03: the
    operator's personal account token answers `me` and still cannot see the
    project — so the credential this guard needs is a workspace token, and the
    old probe reported exactly that healthy credential as dead.
    """
    sent: dict = {}

    def _raise(*a, **k):
        raise RuntimeError("Railway API errors: [{'message': 'Not Authorized'}]")

    monkeypatch.setattr(guard, "_fetch_triggers", _raise)

    def _urlopen(req, timeout=0):
        sent["body"] = json.loads(req.data.decode("utf-8"))
        return _diag_resp({"data": {"project": {"name": "skipp-algo"}}})

    monkeypatch.setattr(guard.urllib.request, "urlopen", _urlopen)
    guard.main()

    # NOT a bare "me" substring check — that matches the `name` field we do
    # select, and would pass on the very query it is meant to forbid.
    compact = sent["body"]["query"].replace(" ", "")
    assert "me{" not in compact, "the probe must not select the personal `me` field"
    assert "project(id:" in compact
    # The probe must ask about the SAME project the failing query used.
    assert sent["body"]["variables"] == {"projectId": "p"}


def test_unreachable_project_names_the_workspace_fix(guard, monkeypatch, capsys):
    # The project is invisible to this credential -> wrong workspace/revoked.
    rc = _run_failing(guard, monkeypatch, {"errors": [{"message": "Not Authorized"}]})
    err = capsys.readouterr().err
    assert rc == 2
    assert "cannot see the project" in err
    assert "WORKSPACE token" in err
    assert "#4345" in err


def test_a_reachable_project_clears_the_credential(guard, monkeypatch, capsys):
    """The credential reaches the project, so it is not the fault — and the
    message must not invent one. It used to say "the refusal is field-level,
    escalate the token's permissions", which sent the operator to issue a fourth
    token for a fault that was an empty serviceId (#4359). Name that instead."""
    rc = _run_failing(guard, monkeypatch, {"data": {"project": {"name": "skipp-algo"}}})
    err = capsys.readouterr().err
    assert rc == 2
    assert "credential is NOT the fault" in err
    assert "Suspect the service id next" in err
    assert "field-level" not in err


def test_empty_project_payload_is_treated_as_unreachable_not_valid(guard, monkeypatch, capsys):
    # No errors key but no name either — must not be read as a healthy token.
    rc = _run_failing(guard, monkeypatch, {"data": {"project": {}}})
    assert rc == 2
    assert "cannot see the project" in capsys.readouterr().err


def test_diagnosis_failure_is_inconclusive_not_a_verdict(guard, monkeypatch, capsys):
    rc = _run_failing(guard, monkeypatch, {}, exc=urllib.error.URLError("dns"))
    err = capsys.readouterr().err
    assert rc == 2
    assert "inconclusive" in err


def test_fetch_parses_the_graphql_edge_shape(guard, monkeypatch):
    """`_fetch_triggers` unwraps data.deploymentTriggers.edges[].node — the exact
    shape returned live on 2026-07-24."""
    captured = {}

    class _Resp:
        def __init__(self, body):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["auth"] = req.headers.get("Authorization")
        body = (
            b'{"data":{"deploymentTriggers":{"edges":['
            b'{"node":{"id":"0da78ef2","repository":"skipp-dev/skipp-algo",'
            b'"branch":"main","provider":"github"}}]}}}'
        )
        return _Resp(body)

    monkeypatch.setattr(guard.urllib.request, "urlopen", _fake_urlopen)
    nodes = guard._fetch_triggers("tok", "p", "e", "svc")
    assert nodes == [
        {"id": "0da78ef2", "repository": "skipp-dev/skipp-algo", "branch": "main", "provider": "github"}
    ]
    assert captured["auth"] == "Bearer tok"


def test_fetch_sends_an_explicit_user_agent(guard, monkeypatch):
    """Railway sits behind Cloudflare, which blocks urllib's default agent.

    Measured 2026-08-03 against backboard.railway.com/graphql/v2: the request
    with no User-Agent (urllib then sends ``Python-urllib/3.12``) is answered
    with ``HTTP 403 / error code: 1010``; the identical request carrying any
    User-Agent returns 200. That 403 is exactly what
    live-overlay-deploy-trigger-guard reported on every run from at least
    2026-07-25, and it reads like a credential problem while being a header
    problem — so pin the header.
    """
    captured = {}

    class _Resp:
        def read(self):
            return b'{"data":{"deploymentTriggers":{"edges":[]}}}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake_urlopen(req, timeout=0):
        # urllib capitalises header keys passed to Request(...).
        captured["ua"] = req.headers.get("User-agent") or req.headers.get("User-Agent")
        return _Resp()

    monkeypatch.setattr(guard.urllib.request, "urlopen", _fake_urlopen)
    guard._fetch_triggers("tok", "p", "e", "svc")
    assert captured["ua"], "no User-Agent set — Cloudflare answers 403 (error code 1010)"
    assert "python-urllib" not in captured["ua"].lower()


def test_fetch_raises_on_graphql_errors(guard, monkeypatch):
    class _Resp:
        def read(self):
            return b'{"errors":[{"message":"nope"}]}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(guard.urllib.request, "urlopen", lambda req, timeout=0: _Resp())
    with pytest.raises(RuntimeError):
        guard._fetch_triggers("tok", "p", "e", "svc")


def test_guard_workflow_invokes_the_script():
    """The scheduled `live-overlay-deploy-trigger-guard` workflow must run this
    script (also gives the workflow test coverage per the orphan inventory)."""
    wf = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "live-overlay-deploy-trigger-guard.yml"
    )
    text = wf.read_text(encoding="utf-8")
    assert "scripts/check_live_overlay_deploy_trigger.py" in text
    assert "schedule:" in text  # runs on a cadence, not push



def test_the_failure_fingerprints_the_credential_without_revealing_it(guard, monkeypatch, capsys):
    """Same token, works locally, refused from the runner — name the value.

    Measured 2026-08-03: the operator's workspace token answers
    deploymentTriggers from his machine and is refused from the runner. Either
    the runner receives a different value or it does not, and no log line could
    say which. The fingerprint is comparable and non-reversible.
    """
    rc = _run_failing(guard, monkeypatch, {"data": {"project": {"name": "skipp-algo"}}})
    err = capsys.readouterr().err
    assert rc == 2
    assert "CREDENTIAL: len=1 sha256[:8]=" in err

    fingerprint = err.split("sha256[:8]=")[1].split()[0]
    assert len(fingerprint) == 8
    assert fingerprint == hashlib.sha256(b"t").hexdigest()[:8]

    # The fixture's token is the single character "t". Asserting it is absent
    # from a German-and-English sentence would pass on any string containing no
    # "t" at all, so anchor on the line that carries the secret's derivative:
    # the CREDENTIAL line must contain the length, the digest, and nothing else
    # drawn from the token.
    credential_line = next(line for line in err.splitlines() if line.startswith("CREDENTIAL:"))
    assert credential_line == (
        f"CREDENTIAL: len=1 sha256[:8]={fingerprint} "
        "(compare locally: printf '%s' \"$TOKEN\" | shasum -a 256 | cut -c1-8)"
    )


def test_fingerprint_is_stable_and_differs_between_values(guard):
    a = guard._credential_fingerprint("alpha")
    b = guard._credential_fingerprint("beta")
    assert a == guard._credential_fingerprint("alpha")
    assert a != b
    # Whitespace is the historical failure mode; it must change the fingerprint.
    assert guard._credential_fingerprint("alpha") != guard._credential_fingerprint("alpha\n")


def _project_payload(env_ids):
    return {
        "data": {
            "project": {
                "name": "skipp-algo",
                "environments": {"edges": [{"node": {"id": i}} for i in env_ids]},
            }
        }
    }


def test_a_foreign_environment_id_is_named_before_the_token_is_blamed(guard, monkeypatch, capsys):
    """deploymentTriggers takes an environment; the project probe does not.

    So a correct token and a correct project id still produce "Not Authorized"
    when RAILWAY_ENVIRONMENT_ID belongs to a different project — same message,
    entirely different fix. The fixture's environment is "e"; the project here
    reports other ids.
    """
    rc = _run_failing(guard, monkeypatch, _project_payload(["env-a", "env-b"]))
    err = capsys.readouterr().err
    assert rc == 2
    assert "RAILWAY_ENVIRONMENT_ID is NOT one of this project's 2 environments" in err
    # It must NOT reach for the token: both other inputs are proven good here.
    assert "Escalate the token" not in err


def test_a_member_environment_moves_the_suspicion_to_the_service_id(
    guard, monkeypatch, capsys
):
    rc = _run_failing(guard, monkeypatch, _project_payload(["e", "other"]))
    err = capsys.readouterr().err
    assert rc == 2
    assert "RAILWAY_ENVIRONMENT_ID belongs to" in err
    assert "Suspect the service id next" in err


def test_an_unlistable_environment_set_does_not_invent_a_verdict(guard, monkeypatch, capsys):
    """No environments in the payload -> membership is unknown, not false.

    Claiming the environment is foreign because the API did not enumerate it
    would send the operator to re-set a secret that is fine.
    """
    rc = _run_failing(guard, monkeypatch, {"data": {"project": {"name": "skipp-algo"}}})
    err = capsys.readouterr().err
    assert rc == 2
    assert "is NOT one of this project" not in err


# --- credential-capability probe (2026-08-03) --------------------------------
# Built when `deploymentTriggers` looked permanently denied to both credentials
# (run 30840756670). It was not denied: the runner was sending an EMPTY serviceId
# and Railway answers that with the same "Not Authorized" (#4359). With the id
# fixed every candidate field reads fine (run 30847141633).
#
# The probe stays because it is what produced both of those findings, and it is
# only worth running if a wrong field name and a denied field are told apart —
# otherwise the next guess masquerades as a permission wall for another week.


def _probe_env(guard, monkeypatch, bodies):
    """Answer every probe request from `bodies` (a list, consumed in order)."""
    seen = []

    class _Resp:
        def __init__(self, body):
            self._body = body

        def read(self):
            return json.dumps(self._body).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _urlopen(req, timeout=0):
        seen.append(
            {
                "query": json.loads(req.data.decode("utf-8"))["query"],
                "variables": json.loads(req.data.decode("utf-8"))["variables"],
                "headers": dict(req.headers),
            }
        )
        return _Resp(bodies[min(len(seen) - 1, len(bodies) - 1)])

    monkeypatch.setattr(guard.urllib.request, "urlopen", _urlopen)
    return seen


def test_classify_separates_a_denied_field_from_a_wrong_field_name(guard):
    assert guard._classify({"errors": [{"message": "Not Authorized"}]})[0] == "DENIED"
    assert (
        guard._classify(
            {"errors": [{"message": 'Cannot query field "source" on type "X"'}]}
        )[0]
        == "SCHEMA"
    )
    assert guard._classify({"errors": [{"message": "upstream exploded"}]})[0] == "ERROR"
    assert guard._classify({"data": {"project": {"name": "skipp-algo"}}})[0] == "OK"


def test_probe_asks_every_candidate_with_every_credential_it_has(guard, monkeypatch):
    monkeypatch.setenv("RAILWAY_TOKEN", "proj-tok")
    seen = _probe_env(guard, monkeypatch, [{"errors": [{"message": "Not Authorized"}]}])

    assert guard.main(["--probe"]) == 0

    assert len(seen) == 2 * len(guard._PROBE_QUERIES)
    # Both header schemes were exercised — a probe that silently sent Bearer for
    # the project token would measure the header bug, not the permission.
    schemes = {tuple(sorted(k.lower() for k in call["headers"])) for call in seen}
    assert any("authorization" in s for s in schemes)
    assert any("project-access-token" in s for s in schemes)


def test_probe_reports_each_candidate_and_never_prints_the_token(
    guard, monkeypatch, capsys
):
    monkeypatch.setenv("RAILWAY_API_TOKEN", "super-secret-token")
    monkeypatch.delenv("RAILWAY_TOKEN", raising=False)
    _probe_env(guard, monkeypatch, [{"data": {"serviceInstance": {"source": {}}}}])

    assert guard.main(["--probe"]) == 0

    out = capsys.readouterr().out
    for name, _query, _needed in guard._PROBE_QUERIES:
        assert name in out
    assert "super-secret-token" not in out
    assert guard._credential_fingerprint("super-secret-token") in out
    assert "RAILWAY_TOKEN: not set — skipped" in out


def test_probe_never_asserts_so_it_cannot_redden_the_daily_guard(guard, monkeypatch):
    """A measurement that can fail the guard would not get run at all."""

    def _boom(*a, **k):
        raise AssertionError("probe mode must not run the assert path")

    monkeypatch.setattr(guard, "_fetch_triggers", _boom)
    _probe_env(guard, monkeypatch, [{"errors": [{"message": "Not Authorized"}]}])
    assert guard.main(["--probe"]) == 0


def test_a_project_token_alone_still_skips_rather_than_asserting(guard, monkeypatch):
    """RAILWAY_TOKEN reaches the step's env for the probe. The assert path must
    not silently adopt it: project tokens are measured to be denied
    deploymentTriggers (#4345), so adopting one would turn a SKIP into a red.

    Declared dormant here so the missing-account-token case exercises the SKIP
    path this test targets, rather than the now-separate declared-configured
    ERROR path (dormancy is declared, not inferred, since 2026-08-04)."""
    monkeypatch.setattr(guard, "_DEPLOYMENT_IS_CONFIGURED", False)
    monkeypatch.delenv("RAILWAY_API_TOKEN", raising=False)
    monkeypatch.setenv("RAILWAY_TOKEN", "proj-tok")

    def _boom(*a, **k):
        raise AssertionError("must not query Railway with the project token")

    monkeypatch.setattr(guard, "_fetch_triggers", _boom)
    assert guard.main([]) == 0


def test_guard_workflow_can_dispatch_the_probe():
    wf = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "live-overlay-deploy-trigger-guard.yml"
    )
    text = wf.read_text(encoding="utf-8")
    assert "probe_credentials:" in text
    assert "--probe" in text
    # The scheduled run must keep asserting: an input that defaults to probing
    # would replace the daily guard with a daily measurement.
    assert "default: false" in text


def test_an_empty_service_id_secret_falls_back_to_the_production_default(
    guard, monkeypatch
):
    """GitHub maps a MISSING secret to "" — not to an absent env var.

    So `os.environ.get(name, default)` never returned the default, and the guard
    asked Railway about service "". It stayed invisible while deploymentTriggers
    answered "Not Authorized" before the id could matter, and surfaced the moment
    the readable fallback had to locate the service (run 30845071629: "service
    has no instance in environment *** among the project's 10 services").
    """
    monkeypatch.setenv("RAILWAY_LIVE_OVERLAY_SERVICE_ID", "")
    seen: dict = {}

    def _capture(token, project_id, environment_id, service_id, *a, **k):
        seen["service_id"] = service_id
        return []

    monkeypatch.setattr(guard, "_fetch_triggers", _capture)
    assert guard.main() == 0
    assert seen["service_id"] == guard._DEFAULT_SERVICE_ID


def test_an_explicit_service_id_secret_still_wins(guard, monkeypatch):
    """The override must keep working — the fix is about "" only."""
    monkeypatch.setenv("RAILWAY_LIVE_OVERLAY_SERVICE_ID", "some-other-service")
    seen: dict = {}

    def _capture(token, project_id, environment_id, service_id, *a, **k):
        seen["service_id"] = service_id
        return []

    monkeypatch.setattr(guard, "_fetch_triggers", _capture)
    assert guard.main() == 0
    assert seen["service_id"] == "some-other-service"


# --- review follow-up 2026-08-04: false green / false red on odd responses ----


def _answer_with(guard, monkeypatch, body):
    class _Resp:
        def read(self):
            return json.dumps(body).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(guard.urllib.request, "urlopen", lambda req, timeout=0: _Resp())


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"data": None},
        {"data": {}},
        {"data": {"deploymentTriggers": None}},
        {"data": {"deploymentTriggers": {}}},
        {"data": {"deploymentTriggers": {"edges": None}}},
        [],
        "nope",
    ],
)
def test_an_unreadable_response_is_inconclusive_never_healthy(
    guard, monkeypatch, capsys, body
):
    """A 200 whose body does not contain the answer must be exit 2.

    Measured before this fix: `{}` and `{"data": null}` printed "OK: no native
    deploy trigger" — fail-OPEN in a fail-closed guard, because every level was
    read with `or {}`. And `{"data": {"deploymentTriggers": null}}` raised an
    uncaught AttributeError, which exits the PROCESS with status 1 — the code
    this guard reserves for DRIFT. Both halves of the requirement, wrong.
    """
    _answer_with(guard, monkeypatch, body)
    rc = guard.main()
    out = capsys.readouterr().out
    assert rc == 2
    assert "no native Railway deploy trigger" not in out


def test_a_well_formed_empty_answer_is_still_healthy(guard, monkeypatch, capsys):
    """The shape assertion must not make the real healthy answer inconclusive."""
    _answer_with(guard, monkeypatch, {"data": {"deploymentTriggers": {"edges": []}}})
    rc = guard.main()
    assert rc == 0
    assert "no native Railway deploy trigger" in capsys.readouterr().out


@pytest.mark.parametrize(
    "edges",
    [
        [{}],
        [{"node": None}],
        [1, 2, 3],
    ],
    ids=["node_key_missing", "node_is_null", "entries_not_dicts"],
)
def test_a_malformed_trigger_edge_is_inconclusive_never_healthy(
    guard, monkeypatch, capsys, edges
):
    """``[e["node"] for e in edges if isinstance(e, dict) and e.get("node")]``
    (the previous implementation) FILTERED a malformed edge away instead of
    rejecting it, so all three shapes here silently produced an empty trigger
    list — rc 0 "no native deploy trigger" without having verified anything,
    contradicting the fail-closed comment right above `_fetch_triggers`'s
    outer-shape assertion (same fail-OPEN class, one level deeper). An edge
    that is not a dict carrying a dict `node` must be unreadable, not evidence
    of health.
    """
    _answer_with(guard, monkeypatch, {"data": {"deploymentTriggers": {"edges": edges}}})
    rc = guard.main()
    out = capsys.readouterr().out
    assert rc == 2
    assert "no native Railway deploy trigger" not in out


def test_a_read_timeout_is_inconclusive_not_drift(guard, monkeypatch, capsys):
    """urllib wraps a CONNECT timeout in URLError, but a timeout during
    resp.read() propagates as a bare TimeoutError. Uncaught it escapes main()
    and the process exits 1 — which this guard defines as DRIFT, sending the
    operator to hunt a trigger that does not exist."""

    def _timeout(*a, **k):
        raise TimeoutError("timed out")

    monkeypatch.setattr(guard, "_fetch_triggers", _timeout)
    monkeypatch.setattr(guard.urllib.request, "urlopen", _timeout)
    rc = guard.main()
    assert rc == 2
    assert "DRIFT" not in capsys.readouterr().err


@pytest.mark.parametrize(
    "exc",
    [
        ssl.SSLError("bad record mac"),
        ConnectionResetError("connection reset by peer"),
        http.client.IncompleteRead(b"partial"),
    ],
    ids=["ssl_error", "connection_reset", "incomplete_read"],
)
def test_a_transport_fault_during_read_is_inconclusive_not_drift(guard, monkeypatch, exc):
    """TimeoutError (tested above) was only one member of this class.

    ssl.SSLError and ConnectionResetError are OSError SIBLINGS, not
    subclasses of URLError or TimeoutError — a tuple that names only those two
    (like this guard's did before the 2026-08-04 review) lets both escape.
    http.client.IncompleteRead is neither an OSError nor a ValueError, so it
    escaped too. All three are real faults resp.read() can raise; escaping
    main() exits the process with status 1 — DRIFT — sending the operator to
    hunt a trigger that does not exist. Patching only ``urlopen`` (not
    ``_fetch_triggers`` directly) exercises the real call path AND the
    follow-up diagnosis probe in the except block, which hits the identical
    widened tuple in ``_diagnose_account_token``.
    """

    def _raise(*a, **k):
        raise exc

    monkeypatch.setattr(guard.urllib.request, "urlopen", _raise)
    rc = guard.main()
    assert rc == 2


def test_the_error_line_names_only_the_variable_that_is_missing(monkeypatch, capsys):
    """Deleting one secret must not read like the designed dormant state.

    Superseded from a soft SKIP into the loud ERROR path (2026-08-04): with the
    deployment declared configured (the default), a single missing secret is no
    longer a silent green — it names only what is actually missing and refuses
    to claim health."""
    mod = _load()
    monkeypatch.delenv("RAILWAY_PROJECT_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("RAILWAY_API_TOKEN", "t")
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "p")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "")

    assert mod.main() == 2
    err = capsys.readouterr().err
    assert "RAILWAY_ENVIRONMENT_ID not set" in err
    assert "RAILWAY_API_TOKEN" not in err
    assert "deleted or mistyped secret" in err


def test_a_schema_error_is_not_swallowed_by_a_denial_in_the_same_body(guard):
    """A query naming four fields can fail both ways at once. Reporting that as
    a pure permission wall is the conflation _classify exists to prevent."""
    mixed = {
        "errors": [
            {"message": 'Cannot query field "meta" on type "Deployment"'},
            {"message": "Not Authorized"},
        ]
    }
    status, detail = guard._classify(mixed)
    assert status == "SCHEMA+DENIED"
    assert "Cannot query field" in detail and "Not Authorized" in detail


def test_classify_survives_shapes_that_carry_no_message(guard):
    assert guard._classify([])[0] == "ERROR"
    status, detail = guard._classify({"errors": [{"extensions": {"code": "UNAUTH"}}]})
    assert status == "ERROR"
    assert detail  # a verdict with no evidence behind it is not a verdict


# --- dormancy must be declared, not inferred (2026-08-04) --------------------


def test_the_inconclusive_message_names_the_missing_secret_and_denies_health(
    monkeypatch, capsys
):
    mod = _load()
    monkeypatch.setenv("RAILWAY_API_TOKEN", "t")
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "p")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "")

    rc = mod.main()

    out, err = capsys.readouterr()
    assert rc == 2
    assert "RAILWAY_ENVIRONMENT_ID" in err
    assert "RAILWAY_API_TOKEN" not in err  # only what is actually missing
    assert "verified NOTHING" in err
    assert "no native Railway deploy trigger" not in out


def test_an_undeclared_deployment_still_skips_green(monkeypatch):
    """The dormant case stays legitimate — but only when the repo says so."""
    mod = _load()
    monkeypatch.setattr(mod, "_DEPLOYMENT_IS_CONFIGURED", False)
    monkeypatch.delenv("RAILWAY_API_TOKEN", raising=False)
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "p")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "e")

    def _boom(*a, **k):
        raise AssertionError("must not reach the network while dormant")

    monkeypatch.setattr(mod, "_fetch_triggers", _boom)
    assert mod.main() == 0


def test_the_declaration_cannot_be_flipped_to_silence_the_guard():
    """Anti-arbitrariness coupling. The declaration is only honest while the
    deployment exists, so flipping it requires ALSO retiring the deploy
    workflow — which is a reviewable change, not a quiet one."""
    mod = _load()
    deploy_workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "deploy-live-overlay-daemon.yml"
    )
    assert deploy_workflow.exists(), (
        "the daemon's deploy workflow is gone — if the deployment was retired, "
        "flip _DEPLOYMENT_IS_CONFIGURED to False in the same PR and update this test"
    )
    assert mod._DEPLOYMENT_IS_CONFIGURED is True


# --- the probe must not echo unaudited remote data (2026-08-04) --------------


def test_the_ok_summary_prints_structure_not_unknown_values(guard):
    """`deployments.meta` is Railway-controlled and free-form: not just its
    VALUES but its KEY NAMES are third-party content, so the whole subtree
    collapses to a key count rather than being enumerated (2026-08-04 review:
    a prior version enumerated key names verbatim below `meta`, which
    contradicted the comment's own "reported by type only" claim)."""
    body = {
        "data": {
            "deployments": {
                "edges": [
                    {
                        "node": {
                            "id": "d1446af4",
                            "status": "SUCCESS",
                            "meta": {
                                "branch": "main",
                                "commitAuthor": "unaudited-value-42",
                            },
                        }
                    }
                ]
            }
        }
    }
    status, detail = guard._classify(body)
    assert status == "OK"
    assert "unaudited-value-42" not in detail
    # Not just the leaf value — the key NAME must not leak either.
    assert "commitAuthor" not in detail
    # `branch` is inside `meta` here, so it is free-form too — no allowlist
    # exemption just because the name matches. See
    # test_the_allowlist_does_not_reach_inside_the_freeform_meta_object for the
    # contrast with the same name at a trusted position.
    assert "main" not in detail
    assert "branch" not in detail
    # `meta` itself still says HOW MUCH it holds — just not what it's named.
    assert "meta={<2 keys>}" in detail
    # Allowlisted leaves outside `meta` and the shape must survive — a summary
    # nobody can read would just get replaced by the raw dump again.
    assert "status=" in detail and "SUCCESS" in detail
    assert "id=" in detail


def test_the_allowlist_does_not_reach_inside_the_freeform_meta_object(guard):
    """`meta`'s shape is Railway's, not ours. An allowlisted name occurring
    inside it must not be trusted just because the same name is safe at a
    position whose shape we define — that would make the allowlist only as
    safe as Railway's naming choices, which is the object this task exists to
    stop trusting. That now extends to the KEY NAME too: `meta`'s own
    `branch` key must not be printed at all, only counted."""
    body = {
        "data": {
            "deployments": {
                "edges": [
                    {
                        "node": {
                            "branch": "main",
                            "meta": {"branch": "sneaky-value-99"},
                        }
                    }
                ]
            }
        }
    }
    detail = guard._classify(body)[1]
    assert "sneaky-value-99" not in detail
    assert 'branch="main"' in detail
    assert "meta={<1 keys>}" in detail
    # The only occurrence of the word "branch" in the whole summary must be
    # the trusted top-level one — `meta`'s `branch` key name is gone, not
    # merely its value.
    assert detail.count("branch") == 1


def test_the_summary_keeps_the_answers_the_probe_exists_for(guard):
    """These two payloads decided real questions on 2026-08-03: an empty edge
    list means no trigger, and source.repo revealed that a connected repo is not
    a trigger. Both must stay legible."""
    empty = {"data": {"deploymentTriggers": {"edges": []}}}
    assert "[0 items]" in guard._classify(empty)[1]

    source = {
        "data": {
            "serviceInstance": {
                "id": "89b0b518",
                "source": {"image": None, "repo": "skipp-dev/skipp-algo"},
            }
        }
    }
    detail = guard._classify(source)[1]
    assert "skipp-dev/skipp-algo" in detail
    assert "image=None" in detail


def test_repository_is_allowlisted_like_its_sibling_field_repo(guard):
    """`deploymentTriggers` selects `repository`, not `repo` (that's a
    different query's field name for the same fact). Before this fix the
    allowlist had only `repo`, so a real trigger's repo rendered `<str>` in
    the probe while main()'s DRIFT path printed it verbatim to stderr on the
    very same field — redacting it in the probe was inconsistent, not
    protective."""
    body = {
        "data": {
            "deploymentTriggers": {
                "edges": [
                    {
                        "node": {
                            "id": "0da78ef2",
                            "repository": "skipp-dev/skipp-algo",
                            "branch": "main",
                            "provider": "github",
                        }
                    }
                ]
            }
        }
    }
    detail = guard._classify(body)[1]
    assert 'repository="skipp-dev/skipp-algo"' in detail


def test_the_summary_is_bounded_in_depth(guard):
    """Nested past `_PAYLOAD_MAX_DEPTH` (12, sized from the deepest real
    `_PROBE_QUERIES` shape — see the constant's comment): 13 single-key levels
    puts the leaf one level beyond the cap. Shallower than this (measured up
    to 12 levels) renders in full and would make the assertion vacuous."""
    deep = {
        "data": {
            "a": {
                "b": {
                    "c": {
                        "d": {
                            "e": {
                                "f": {
                                    "g": {
                                        "h": {
                                            "i": {
                                                "j": {"k": {"l": {"m": "deep"}}}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    assert "…" in guard._classify(deep)[1]


def test_the_summary_is_bounded_in_width(guard):
    """The width bound (`_PAYLOAD_MAX` / the `_classify` slice) is a SEPARATE
    mechanism from the depth bound above and needs its own payload that
    actually exceeds it pre-truncation.

    ``[{"node": {"name": ...}} for _ in range(200)]`` (the previous payload)
    does NOT do that: a list only renders ONE representative element (`the
    shape repeats, the values do not` — see `_summarize`), so the untruncated
    summary is ~42 chars regardless of how many list items exist, nowhere near
    the 400-char cap. That made the width assertion pass whether or not the
    slice in `_classify` (``summary[:_PAYLOAD_MAX] + ("…" if ...)``) was even
    present — verified 2026-08-04 by deleting the slice: this test still
    passed. A DICT, not a list, renders every sibling key, so width to
    exceed the cap needs sibling KEYS. 80 sibling keys is measured (see
    `_summarize(wide["data"])` with the slice removed) to produce an
    870-char unsliced summary, truncated by the real code to exactly 401
    (400 + the ellipsis) — comfortably over the bound, unlike the previous
    list-based payload's ~42 chars.
    """
    wide = {"data": {f"k{i}": "v" for i in range(80)}}
    detail = guard._classify(wide)[1]
    assert len(detail) <= 401  # 400 + the ellipsis
    assert detail.endswith("…")


def test_the_summary_survives_shapes_that_are_not_objects(guard):
    assert guard._classify({"data": None})[1] == "{}"
    assert "[3 items" in guard._classify({"data": {"x": [1, 2, 3]}})[1]
