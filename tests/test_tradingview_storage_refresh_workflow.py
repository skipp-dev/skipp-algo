"""Structural pins for TradingView storage-state auto-renewal."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tradingview-storage-refresh.yml"
CAPTURE_SCRIPT = REPO_ROOT / "scripts" / "create_tradingview_storage_state.ts"


@pytest.fixture(scope="module")
def workflow_text() -> str:
    assert WORKFLOW.exists(), f"missing workflow: {WORKFLOW}"
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow(workflow_text: str) -> dict:
    return yaml.safe_load(workflow_text)


def test_workflow_name_referenced(workflow_text: str) -> None:
    assert "name: tradingview-storage-refresh" in workflow_text


def test_schedule_pinned_48h(workflow: dict) -> None:
    on = workflow.get("on") if "on" in workflow else workflow.get(True)
    schedule = on.get("schedule", [])
    crons = [entry.get("cron") for entry in schedule]
    assert "0 3 */2 * *" in crons, f"expected 48 h cron, got {crons!r}"


def test_permissions_minimal(workflow: dict) -> None:
    perms = workflow.get("permissions") or {}
    assert perms.get("contents") == "read"
    assert perms.get("issues") == "write"
    assert set(perms.keys()) <= {"contents", "issues"}


def test_refresh_workflow_bootstraps_from_current_storage_state_secret() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Prepare current storage state bootstrap" in text
    assert "TV_STORAGE_STATE_SECRET: ${{ secrets.TV_STORAGE_STATE }}" in text
    assert "automation/tradingview/auth/bootstrap-storage-state.json" in text
    assert "gzip.decompress(base64.b64decode(raw))" in text
    assert "Preflight required login secrets" not in text


def test_refresh_workflow_passes_bootstrap_to_capture_script() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "TV_STORAGE_STATE_INPUT: automation/tradingview/auth/bootstrap-storage-state.json" in text
    assert "--input-storage-state automation/tradingview/auth/bootstrap-storage-state.json" in text
    assert text.index("Prepare current storage state bootstrap") < text.index("Capture TradingView storage state")
    assert text.index("--input-storage-state") < text.index("--out automation/tradingview/auth/storage-state.json")


def test_capture_script_supports_headless_bootstrap_without_login_secrets() -> None:
    text = CAPTURE_SCRIPT.read_text(encoding="utf-8")
    assert "inputStorageState" in text
    assert "TV_STORAGE_STATE_INPUT" in text
    assert "storageState: existingStorageStatePath" in text
    assert "Headless TradingView storage-state capture requires TV_STORAGE_STATE_INPUT" in text
    assert "cli.persistentProfileDir || existingStorageStatePath ? cli.chartUrl : cli.loginUrl" in text


def test_uses_gh_pat_for_secret_write(workflow_text: str) -> None:
    write_block = workflow_text.split("Write refreshed secret back to GitHub")[1]
    assert "GH_TOKEN: ${{ secrets.GH_PAT }}" in write_block
    assert "gh secret set TV_STORAGE_STATE" in write_block


def test_capture_and_validate_steps_are_fail_loud(workflow_text: str) -> None:
    forbidden = [
        re.compile(r"set\s+\+e"),
        re.compile(r"\|\|\s*true"),
        re.compile(r";\s*true"),
    ]
    critical_tail = workflow_text.split("Capture TradingView storage state")[1]
    for pattern in forbidden:
        assert not pattern.search(critical_tail), (
            f"capture/validate steps must be fail-loud, found {pattern.pattern!r}"
        )


def test_capture_step_invokes_expected_script(workflow_text: str) -> None:
    assert "npx tsx scripts/create_tradingview_storage_state.ts" in workflow_text
    assert "--headless" in workflow_text


def test_validate_step_invokes_credential_health_check(workflow_text: str) -> None:
    assert "python scripts/credential_health_check.py" in workflow_text
    assert "--tv-max-age-hours 72" in workflow_text


def test_failure_issues_use_cron_failure_label(workflow_text: str) -> None:
    assert "gh issue create" in workflow_text
    assert "cron-failure" in workflow_text


def test_force_with_lease_not_used_for_secret_write(workflow_text: str) -> None:
    write_block = workflow_text.split("Write refreshed secret back to GitHub")[1]
    assert "force-with-lease" not in write_block
