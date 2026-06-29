"""Structural pins for TradingView storage-state auto-renewal."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tradingview-storage-refresh.yml"
CAPTURE_SCRIPT = REPO_ROOT / "scripts" / "create_tradingview_storage_state.ts"


def test_refresh_workflow_bootstraps_from_current_storage_state_secret() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Prepare current storage state bootstrap" in text
    assert "TV_STORAGE_STATE_SECRET: ${{ secrets.TV_STORAGE_STATE }}" in text
    assert "automation/tradingview/auth/bootstrap-storage-state.json" in text
    assert "gzip.decompress(base64.b64decode(raw))" in text


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
