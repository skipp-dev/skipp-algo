"""Contract pin for ``deploy-live-overlay-daemon.yml``.

Railway's native GitHub auto-deploy for the ``live_overlay_daemon`` service
stopped firing (the connection references the pre-rename ``skippALGO`` org
slug), so merges to main did not reach production. This workflow deploys the
daemon deterministically on every main push that touches it, via the
SHA-stamping wrapper (``scripts/deploy_live_overlay.sh``) so production tracks
main AND ``live_overlay_build_info`` shows the real deployed commit.

This test freezes the security-relevant contract so a refactor cannot
silently weaken it, and (per ``test_workflow_orphan_inventory``) gives the
workflow its required test reference.
"""
from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-live-overlay-daemon.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _doc() -> dict:
    return yaml.safe_load(_text())


def _on(doc: dict):
    # PyYAML parses the bare mapping key ``on:`` as the boolean ``True``.
    return doc["on"] if "on" in doc else doc[True]


def test_workflow_exists_with_live_window_marker() -> None:
    head = _text().splitlines()[:10]
    assert any(line.startswith("# live-window:") for line in head), (
        "workflow needs a `# live-window:` marker in the first 10 lines"
    )


def test_triggers_on_main_push_with_paths_and_dispatch() -> None:
    on = _on(_doc())
    assert "workflow_dispatch" in on
    push = on["push"]
    assert push["branches"] == ["main"]
    # Only deploy when the daemon (or its deploy tooling) actually changed.
    assert "services/live_overlay_daemon/**" in push["paths"]
    assert "scripts/deploy_live_overlay.sh" in push["paths"]


def test_permissions_are_read_only() -> None:
    assert _doc()["permissions"] == {"contents": "read"}


def test_concurrency_never_cancels_an_in_flight_deploy() -> None:
    conc = _doc()["concurrency"]
    assert conc["cancel-in-progress"] is False


def test_deploy_is_gated_on_railway_token() -> None:
    text = _text()
    # Absent secret -> notice, gate output false, so the file is inert.
    assert "Missing secret RAILWAY_TOKEN" in text
    assert "secrets.RAILWAY_TOKEN" in text
    # Steps gate on the token-presence output (step env is invisible to `if:`).
    assert "steps.gate.outputs.run == 'true'" in text


def test_railway_token_is_scoped_to_steps_not_the_job() -> None:
    # Defense-in-depth: checkout/install must not see the token.
    job = _doc()["jobs"]["deploy"]
    assert "RAILWAY_TOKEN" not in (job.get("env") or {})


def test_railway_cli_install_runs_postinstall_and_sanity_checks() -> None:
    # @railway/cli fetches its platform binary in `postinstall`; suppressing
    # npm lifecycle scripts leaves a dead shim that exits 1 with zero output
    # (the root cause of every failed deploy on 2026-07-07, 07:55-10:38Z).
    # The exact version pin is the supply-chain control; the sanity call
    # proves the binary is real before the deploy trusts it.
    text = _text()
    assert "--ignore-scripts" not in text
    assert "railway --version" in text


def test_deploy_is_verified_not_fire_and_forget() -> None:
    text = _text()
    # `railway up --detach` returns before the deploy completes; a verify step
    # must poll until a deployment CREATED AFTER the job started reaches
    # terminal SUCCESS (a stale prior SUCCESS can never false-pass).
    assert "Verify deployment" in text
    assert "started=" in text
    assert "fromdateiso8601" in text
    assert "ended in status" in text


def test_verify_uses_graphql_not_the_cli_list() -> None:
    # Empirical (2026-07-07, dispatches 28856828169 + 28859622704): under a
    # project token the CLI's `railway deployment list` dies with "No linked
    # project found" (with or without RAILWAY_PROJECT_ID), so verify must use
    # the public GraphQL API, where project tokens are first-class.
    text = _text()
    assert "Project-Access-Token" in text
    assert "backboard.railway.com/graphql" in text
    assert "railway deployment list" not in text


def test_railway_up_env_stays_token_only() -> None:
    # Keep the exact token-only env the successful deploys (07:49Z main,
    # dispatch 28860288937) are proven to work with. A project-id env var is
    # unnecessary (verify uses GraphQL) and was present in a failed
    # configuration; whether it CAUSED that failure is unproven (the dead-shim
    # CLI confounded it) -- so simply do not reintroduce unproven variables.
    assert "RAILWAY_PROJECT_ID" not in _text()


def test_no_stderr_silencing_anywhere() -> None:
    # A silenced stderr hid the root cause across five failed deploys
    # (2026-07-07). Never again -- errors must reach the log.
    assert "2>/dev/null" not in _text()


def test_deploy_uses_the_sha_stamping_wrapper_with_branch() -> None:
    text = _text()
    assert "scripts/deploy_live_overlay.sh" in text
    # Pass the ref so the stamp records "main", not CI's detached "HEAD".
    assert "DEPLOY_GIT_BRANCH: ${{ github.ref_name }}" in text


def test_checkout_action_is_sha_pinned() -> None:
    assert "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd" in _text()


def test_railway_cli_install_is_version_pinned() -> None:
    # SC-02: exact pin, no floating range.
    assert "@railway/cli@5.23.3" in _text()


# --- the gate, executed rather than described --------------------------------
#
# `Check Railway token presence` decides `run`, and the deploy step hangs on it.
# Measured 2026-08-04 with a value-preserving arm swap (the `true`/`false` token
# multiset left unchanged, so any substring assertion is blind by construction):
# swapping the two arms left all 72 tests across the two files that name this
# workflow green -- while a run WITH the secret would skip the deploy and a run
# WITHOUT it would attempt one.
#
# The empty-secret direction is the one with history: an absent GitHub Actions
# secret arrives as "", never as an unset variable, so `-z` is the only test
# that sees it. The same shape produced a Railway `Not Authorized` that took
# four wrong diagnoses to pin down.

from tests._workflow_step_shell import run_step

_GATE_STEP = "Check Railway token presence"


def _gate(tmp_path: Path, token: str):
    return run_step(
        "deploy-live-overlay-daemon.yml", _GATE_STEP, tmp_path, env={"RAILWAY_TOKEN": token}
    )


def test_the_deploy_runs_when_the_token_is_present(tmp_path: Path) -> None:
    result = _gate(tmp_path, "railway-token")
    assert result.returncode == 0, result.stderr
    assert result.outputs["run"] == "true", (
        f"a configured RAILWAY_TOKEN must let the deploy run; got {result.outputs}"
    )


def test_a_missing_secret_skips_the_deploy_instead_of_attempting_it(tmp_path: Path) -> None:
    """An unset Actions secret is the empty string, and must skip, not deploy.

    Skipping is the safe direction: an attempted deploy without credentials
    fails somewhere inside Railway, where the error reads as an outage rather
    than as a missing secret.
    """
    result = _gate(tmp_path, "")
    assert result.returncode == 0, result.stderr
    assert result.outputs["run"] == "false", (
        f"a missing RAILWAY_TOKEN must not arm the deploy; got {result.outputs}"
    )
    assert "Missing secret RAILWAY_TOKEN" in result.stdout, (
        "the skip must say why, or an unconfigured repository looks identical "
        "to a repository with nothing to deploy"
    )
