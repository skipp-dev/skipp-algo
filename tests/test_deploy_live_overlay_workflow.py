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
    # Absent secret -> notice + exit 0, so the file is inert until configured.
    assert "Missing secret RAILWAY_TOKEN" in text
    assert "secrets.RAILWAY_TOKEN" in text
    # Both the install and deploy steps are guarded on the token being present.
    assert text.count("env.RAILWAY_TOKEN != ''") >= 2


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
