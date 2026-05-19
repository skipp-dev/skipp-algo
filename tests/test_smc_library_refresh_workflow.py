from __future__ import annotations

from pathlib import Path

from smc_integration.release_policy import (
    DRIFT_CLASS_GITIGNORED,
    DRIFT_CLASS_RESTORE_ON_COMMIT,
    DRIFT_CLASS_STAGE_ONLY,
    DRIFT_CLASSES,
    RESTORE_ON_COMMIT_PATHS,
    STAGE_ONLY_PATHS,
    VOLATILE_ARTIFACT_POLICY,
    classify_artifact_drift,
)

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
    # Workflow `git add` step was expanded by PR #13 into a multi-line continuation
    # listing all 14 Pine consumers. Pin each required path individually instead of a
    # single concatenated substring so further consumer additions don't silently break
    # the assertion form.
    assert 'git add pine/generated/ \\' in workflow_text
    for path in (
        'SMC_Core_Engine.pine',
        'SMC_Dashboard.pine',
        'SMC_Mobile_Dashboard.pine',
        'SMC_Long_Strategy.pine',
        'SkippALGO_Confluence.pine',
        'SMC_Structure_Context.pine',
        'SMC_Session_Context.pine',
        'SMC_Profile_Context.pine',
        'SMC_Orderflow_Overlay.pine',
        'SMC_Liquidity_Structure.pine',
        'SMC_Liquidity_Context.pine',
        'SMC_Imbalance_Context.pine',
        'SMC_HTF_Confluence.pine',
        'SMC_Event_Overlay.pine',
        'artifacts/tradingview/library_release_manifest.json',
    ):
        assert path in workflow_text, f"workflow git add step missing: {path}"
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


def test_refresh_commit_step_uses_bot_pr_auto_merge_pattern() -> None:
    """The refresh workflow no longer pushes directly to main (blocked by the
    `main-governance` ruleset / required `fast-gates` check). Instead it opens
    a `bot/library-refresh-${run_id}` PR with the `automated` label and arms
    auto-merge — same pattern as `run-open-prep-daily.yml` and
    `open-prep-outcome-backfill.yml`. Pin the new mechanism so the next
    refactor doesn't silently regress us back to direct-push (which would
    fail at runtime with GH013)."""
    workflow_text = _read(WORKFLOW_PATH)

    # Bot/* branch naming pinned to the workflow run id for traceability.
    assert 'BRANCH="bot/library-refresh-${GITHUB_RUN_ID}"' in workflow_text
    assert 'git checkout -b "$BRANCH"' in workflow_text
    assert 'git push -u origin "$BRANCH"' in workflow_text
    # PR creation with the automated label so CI skip-pattern short-circuits
    # heavy steps (validation already happened inside the refresh workflow).
    assert 'gh pr create \\' in workflow_text
    assert '--label automated \\' in workflow_text
    assert '--head "$BRANCH" \\' in workflow_text
    # Auto-merge arming + branch cleanup.
    assert 'gh pr merge "$BRANCH" --auto --squash --delete-branch' in workflow_text
    # Reason for the indirection must remain documented inline so the next
    # editor knows not to "simplify" back to direct push.
    assert 'main-governance' in workflow_text
    assert "Required status check 'fast-gates' is expected" in workflow_text


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

    assert '--strict-measurement-shadow' not in workflow_text
    assert '- name: Run TradingView post-release validation' in workflow_text
    assert '- name: Normalize TradingView post-release validation' in workflow_text
    assert '- name: Refresh gate evidence summary after post-release validation' in workflow_text
    assert 'TV_STORAGE_STATE_MAX_AGE_HOURS: "72"' in workflow_text
    assert 'tv_post_release_validation.json' in workflow_text
    assert '"$SMC_PYTHON_BIN" scripts/run_smc_post_release_validation.py' in workflow_text
    assert '--ci-mode' in workflow_text
    assert 'smc_post_release_validation_report.json' in workflow_text
    assert 'TradingView post-release validation' in workflow_text
    assert 'TradingView post-release validation failed' in workflow_text
    assert "steps.tv_post_release.outcome == 'success'" in workflow_text
    assert "steps.release_gates.outcome == 'success'" in workflow_text


def test_refresh_workflow_prefers_priority_cron_runner_with_portable_python() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    assert '- name: Resolve worker runner' in workflow_text
    assert '--custom-label "${{ vars.SMC_PRIORITY_CRON_SELF_HOSTED_LABEL || vars.SMC_SELF_HOSTED_LABEL }}"' in workflow_text
    assert '- name: Set up pinned Python (GitHub-hosted)' in workflow_text
    assert '- name: Resolve Python 3.12 interpreter' in workflow_text
    assert 'SMC_PYTHON_BIN=python' in workflow_text
    assert 'py -3.12' in workflow_text
    # F-V8-cutover follow-up: main switched to uv-managed installs
    # (`uv pip install --python "$SMC_PYTHON_BIN"`) for cold-cache speed.
    # Pin the new contract; the legacy `python -m pip install --upgrade pip`
    # surface is gone.
    assert 'uv pip install --python "$SMC_PYTHON_BIN"' in workflow_text
    assert 'SMC_REFRESH_RUNNER_LABEL' not in workflow_text


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


# -- WP8: Drift-safe artifact policy tests ----------------------------------

def test_drift_classes_are_bounded() -> None:
    assert DRIFT_CLASSES == ("restore_on_commit", "stage_only", "gitignored")


def test_volatile_artifact_policy_entries_have_valid_drift_class() -> None:
    for entry in VOLATILE_ARTIFACT_POLICY:
        assert entry["drift_class"] in DRIFT_CLASSES, (
            f"entry {entry['path']} has unknown drift_class {entry['drift_class']}"
        )
        assert "reason" in entry, f"entry {entry['path']} missing reason"
        assert "path" in entry, "entry missing path key"


def test_restore_on_commit_paths_match_workflow_restore_step() -> None:
    """Every restore-on-commit path must appear in the workflow's restore step."""
    workflow_text = _read(WORKFLOW_PATH)
    for path in RESTORE_ON_COMMIT_PATHS:
        assert path in workflow_text, (
            f"RESTORE_ON_COMMIT path '{path}' not found in workflow restore step"
        )


def test_stage_only_paths_match_workflow_git_add_step() -> None:
    """Every stage-only path must appear in the workflow's git add step."""
    workflow_text = _read(WORKFLOW_PATH)
    for path in STAGE_ONLY_PATHS:
        assert path in workflow_text, (
            f"STAGE_ONLY path '{path}' not found in workflow git add step"
        )


def test_classify_artifact_drift_returns_correct_class() -> None:
    assert classify_artifact_drift("artifacts/databento_volatility_cache/foo.json") == DRIFT_CLASS_RESTORE_ON_COMMIT
    assert classify_artifact_drift("pine/generated/smc_micro.pine") == DRIFT_CLASS_STAGE_ONLY
    assert classify_artifact_drift("SMC_Core_Engine.pine") == DRIFT_CLASS_STAGE_ONLY
    assert classify_artifact_drift("artifacts/tradingview/library_release_manifest.json") == DRIFT_CLASS_STAGE_ONLY
    assert classify_artifact_drift("automation/tradingview/auth/storage-state.json") == DRIFT_CLASS_GITIGNORED
    assert classify_artifact_drift("src/main.py") is None


def test_restore_and_stage_paths_are_disjoint() -> None:
    overlap = RESTORE_ON_COMMIT_PATHS & STAGE_ONLY_PATHS
    assert not overlap, f"paths in both restore and stage: {overlap}"


def test_artifact_strategy_doc_mentions_drift_classification() -> None:
    doc = (ROOT / "docs/ARTIFACT_STRATEGY.md").read_text(encoding="utf-8")
    assert "Drift Classification" in doc
    assert "restore_on_commit" in doc
    assert "stage_only" in doc
    assert "gitignored" in doc
    assert "VOLATILE_ARTIFACT_POLICY" in doc
