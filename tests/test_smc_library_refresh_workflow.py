from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/smc-library-refresh.yml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_refresh_commit_step_restores_runtime_artifacts_before_commit() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    assert 'GIT_LFS_SKIP_SMUDGE=1 git -c filter.lfs.smudge= -c filter.lfs.process= -c filter.lfs.required=false restore --source=HEAD --worktree --staged -- \\' in workflow_text
    assert 'artifacts/databento_volatility_cache/' in workflow_text
    assert 'artifacts/smc_microstructure_exports/smc_live_news_snapshot.json' in workflow_text
    assert 'artifacts/smc_microstructure_exports/smc_live_news_state.json' in workflow_text
    assert 'git add pine/generated/ SMC_Core_Engine.pine artifacts/tradingview/library_release_manifest.json' in workflow_text
    assert 'Unexpected tracked changes remain unstaged before refresh commit.' in workflow_text


def test_refresh_workflow_surfaces_first_failing_gate_test() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    assert 'tee artifacts/ci/smc_refresh_gate_pytest.log' in workflow_text
    assert "grep -m1 '^FAILED ' artifacts/ci/smc_refresh_gate_pytest.log || true" in workflow_text
    assert 'echo "first_failed_test<<EOF"' in workflow_text
    assert 'Evidence gates failed on ${{ steps.gates.outputs.first_failed_test }}' in workflow_text
    assert 'FIRST_FAILED_GATE_TEST: ${{ steps.gates.outputs.first_failed_test }}' in workflow_text
    assert 'echo "| First failing gate test | $FIRST_FAILED_GATE_TEST |"' in workflow_text
    assert '### First Failing Gate Test' in workflow_text


def test_refresh_commit_step_keeps_non_fast_forward_retry_loop() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    assert 'for attempt in 1 2 3; do' in workflow_text
    assert 'if git push origin HEAD:main; then' in workflow_text
    assert 'git fetch origin main' in workflow_text
    assert 'if ! git rebase origin/main; then' in workflow_text
    assert 'Refresh commit conflicts with newer origin/main. Re-run the workflow on the latest main.' in workflow_text


def test_refresh_workflow_surfaces_provider_health_signals_in_summary_and_notification() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    assert '- name: Extract provider health signals' in workflow_text
    assert 'PROVIDER_DOMAIN_ALERT_COUNT=' in workflow_text
    assert 'PROVIDER_HEALTH_WARNING_COUNT=' in workflow_text
    assert '### Provider Domain Alerts' in workflow_text
    assert '### Provider Health Warnings' in workflow_text
    assert 'Library published with provider warnings' in workflow_text
    assert 'Library published with fallback alerts' in workflow_text
    assert 'Provider domain alerts: ${ALERT_COUNT} (${ALERT_WARN} warn / ${ALERT_INFO} info)' in workflow_text
    assert 'Provider health warnings: ${PROVIDER_WARNING_COUNT}' in workflow_text


def test_refresh_workflow_runs_post_release_validation_before_commit() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    assert '--strict-measurement-shadow' in workflow_text
    assert '- name: Run TradingView post-release validation' in workflow_text
    assert '- name: Refresh gate evidence summary after post-release validation' in workflow_text
    assert 'TV_STORAGE_STATE_MAX_AGE_HOURS: "72"' in workflow_text
    assert 'tv_post_release_validation.json' in workflow_text
    assert 'python scripts/run_smc_post_release_validation.py' in workflow_text
    assert 'smc_post_release_validation_report.json' in workflow_text
    assert 'TradingView post-release validation' in workflow_text
    assert 'TradingView post-release validation failed' in workflow_text