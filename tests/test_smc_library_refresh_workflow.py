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
    assert '- name: Normalize TradingView post-release validation' in workflow_text
    assert '- name: Refresh gate evidence summary after post-release validation' in workflow_text
    assert 'TV_STORAGE_STATE_MAX_AGE_HOURS: "72"' in workflow_text
    assert 'tv_post_release_validation.json' in workflow_text
    assert 'python scripts/run_smc_post_release_validation.py' in workflow_text
    assert '--ci-mode' in workflow_text
    assert 'smc_post_release_validation_report.json' in workflow_text
    assert 'TradingView post-release validation' in workflow_text
    assert 'TradingView post-release validation failed' in workflow_text
    assert "steps.tv_post_release.outcome == 'success'" in workflow_text
    assert "steps.release_gates.outcome == 'success'" in workflow_text


def test_refresh_workflow_passes_post_release_report_to_release_gates() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    assert '- name: Run strict release gates' in workflow_text
    assert '--post-release-validation-report artifacts/ci/smc_post_release_validation_report.json' in workflow_text
    assert workflow_text.index('- name: Normalize TradingView post-release validation') < workflow_text.index('- name: Run strict release gates')


def test_refresh_workflow_separates_pre_and_post_release_gate_reports() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    assert '--output artifacts/ci/smc_pre_release_gates_report.json' in workflow_text
    assert '--output artifacts/ci/smc_post_release_gates_report.json' in workflow_text
    assert 'Path("artifacts/ci/smc_post_release_gates_report.json")' in workflow_text
    assert 'Path("artifacts/ci/smc_pre_release_gates_report.json")' in workflow_text


def test_refresh_workflow_uploads_ci_report_after_post_release() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    assert '- name: Upload gate evidence + library artifacts' in workflow_text
    assert 'artifacts/ci/' in workflow_text
    assert workflow_text.index('- name: Refresh gate evidence summary after post-release validation') < workflow_text.index('- name: Upload gate evidence + library artifacts')


def test_refresh_workflow_alert_step_consumes_post_release_report_even_after_failures() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    assert "if: always() && steps.diff.outputs.changed == 'true'" in workflow_text
    assert '--post-release-report artifacts/ci/smc_post_release_validation_report.json' in workflow_text