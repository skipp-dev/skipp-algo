"""The Railway deploy-trigger drift guard's decision logic.

Root cause it exists for (2026-07-24): the live_overlay_daemon Railway service
had a native GitHub deploy trigger (branch=main, no path filter), so every push
to main redeployed the daemon — ~23/day, most touching nothing in it — wiping
the bar cache and resetting uptime. The service is meant to be CI-only
(source=none); this guard fails if a native trigger reappears.

Network is mocked: these pin the exit-code contract, not Railway connectivity.
"""
from __future__ import annotations

import importlib.util
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

