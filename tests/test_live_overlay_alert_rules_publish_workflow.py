"""Structural pin for ``.github/workflows/live-overlay-alert-rules-publish.yml``.

References the exact hyphenated basename ``live-overlay-alert-rules-publish`` so
the orphan-workflow inventory (tests/test_workflow_orphan_inventory.py) stays
closed. Mirrors tests/test_live_overlay_dashboard_publish_workflow.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "live-overlay-alert-rules-publish.yml"
ALERT_RULES = "services/live_overlay_daemon/infra/grafana/alert-rules.yaml"


@pytest.fixture(scope="module")
def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow_doc(workflow_text: str) -> dict:
    data = yaml.safe_load(workflow_text)
    assert isinstance(data, dict), "workflow must parse as a mapping"
    return data


def test_trigger_contract_pinned(workflow_doc: dict) -> None:
    # PyYAML may parse bare `on:` as boolean True; tolerate both shapes.
    on_block = workflow_doc.get("on") if "on" in workflow_doc else workflow_doc.get(True)
    assert isinstance(on_block, dict), "workflow must declare `on:` mapping"

    push = on_block.get("push")
    assert isinstance(push, dict), "workflow must define push trigger"
    assert push.get("branches") == ["main"], "push trigger must remain pinned to main"
    assert push.get("paths") == [ALERT_RULES], "push path filter must be exactly alert-rules.yaml"

    dispatch = on_block.get("workflow_dispatch")
    assert isinstance(dispatch, dict), "workflow must support workflow_dispatch"
    dry_run = (dispatch.get("inputs") or {}).get("dry_run")
    assert isinstance(dry_run, dict), "dry_run input missing"
    assert dry_run.get("default") in (True, "true"), "dry_run must default to true for manual runs"


def test_permissions_and_concurrency_pinned(workflow_doc: dict) -> None:
    assert workflow_doc.get("permissions") == {"contents": "read"}, "must stay read-only at workflow scope"
    concurrency = workflow_doc.get("concurrency")
    assert isinstance(concurrency, dict)
    assert "${{ github.workflow }}" in concurrency.get("group", "")
    assert "${{ github.ref }}" in concurrency.get("group", "")
    assert concurrency.get("cancel-in-progress") is False, "publishes must not cancel each other"


def test_upsert_step_contract(workflow_text: str) -> None:
    # The token the upsert script reads (GRAFANA_API_KEY) must be mapped from the
    # existing GRAFANA_API_TOKEN secret, and a real (non-dry-run) upsert must
    # fail loud if it is absent.
    assert "GRAFANA_API_KEY: ${{ secrets.GRAFANA_API_TOKEN }}" in workflow_text
    assert "scripts/grafana_alert_rules_upsert.py --dry-run" in workflow_text, (
        "must preflight-validate with --dry-run before any network upsert"
    )
    assert 'test -n "${GRAFANA_API_KEY:-}"' in workflow_text, "real upsert must require the token"
    # No --prune: this workflow must never auto-delete rule groups absent from the file.
    assert "--prune" not in workflow_text, "auto-prune is unsafe for a push-triggered upsert"
    # Dry-run preflight must precede the mutating upsert.
    assert workflow_text.index("--dry-run") < workflow_text.rindex(
        "python scripts/grafana_alert_rules_upsert.py"
    ), "preflight dry-run must come before the real upsert"


def test_runner_and_python_pinned(workflow_text: str) -> None:
    assert "${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest' }}" in workflow_text
    assert "./.github/actions/setup-python-pinned" in workflow_text
    assert "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd" in workflow_text


def test_pyyaml_installed_before_upsert(workflow_text: str) -> None:
    """The upsert script parses alert-rules.yaml with PyYAML — set-up-python does
    NOT install it, so the workflow must `pip install pyyaml` before the upsert or
    it dies on `No module named 'yaml'` (regression guard for the 2026-07-11
    silent auto-publish failure)."""
    install_at = workflow_text.find("pip install")
    assert install_at != -1 and "pyyaml" in workflow_text, (
        "workflow must install PyYAML (the upsert's only third-party dep)"
    )
    # Anchor on the actual invocation, not the header comment that also names the script.
    upsert_at = workflow_text.index("python scripts/grafana_alert_rules_upsert.py")
    assert install_at < upsert_at, "PyYAML must be installed before the upsert step runs"
