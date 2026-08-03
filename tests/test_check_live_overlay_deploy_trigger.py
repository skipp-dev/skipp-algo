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
import importlib.util
import json
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
    mod = _load()
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


def test_reachable_project_names_a_field_level_denial(guard, monkeypatch, capsys):
    # The credential reaches the project, so only the field is refused.
    rc = _run_failing(guard, monkeypatch, {"data": {"project": {"name": "skipp-algo"}}})
    err = capsys.readouterr().err
    assert rc == 2
    assert "refusal is field-level" in err


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
