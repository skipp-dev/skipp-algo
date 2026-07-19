from __future__ import annotations

import re
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


def _step_block(workflow_text: str, step_name: str) -> str:
    start = workflow_text.index(f"      - name: {step_name}")
    next_step = workflow_text.find("\n      - name: ", start + 1)
    return workflow_text[start:] if next_step == -1 else workflow_text[start:next_step]


def test_refresh_workflow_restores_databento_bundle_before_generation() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    ordered_steps = [
        "Restore Databento production export bundle (today)",
        "Restore Databento production export bundle (latest fallback)",
        "Reject stale Databento fallback on automated refresh",
        "Flatten downloaded Databento export bundle",
        "Verify Databento production export bundle is present",
        "Generate SMC library with v5 enrichment",
    ]
    positions = [workflow_text.index(f"      - name: {step}") for step in ordered_steps]
    assert positions == sorted(positions)
    assert positions[-1] < workflow_text.index("      - name: Run evidence gate tests")

    restore_region = workflow_text[positions[0]:positions[-1]]
    assert "steps.diff.outputs.changed" not in restore_region

    stale_guard_block = _step_block(workflow_text, "Reject stale Databento fallback on automated refresh")
    assert "github.event_name != 'workflow_dispatch'" in stale_guard_block
    assert "Refusing to generate from a stale producer bundle" in stale_guard_block


def test_refresh_workflow_generates_from_restored_producer_bundle() -> None:
    workflow_text = _read(WORKFLOW_PATH)
    generate_block = _step_block(workflow_text, "Generate SMC library with v5 enrichment")

    assert "--bundle artifacts/smc_microstructure_exports" in generate_block
    assert "--static-only" in generate_block
    assert "--enrich-all" not in generate_block
    assert "--export-dir artifacts/smc_microstructure_exports" in generate_block
    assert "--run-scan" not in generate_block
    assert "--incremental-base-only" not in generate_block
    assert "DATABENTO_API_KEY" not in generate_block
    assert "SMC_INCREMENTAL_BASE_SEED_CACHE_VERSION" not in workflow_text
    assert "Restore incremental base seed" not in workflow_text
    assert "Save incremental base seed" not in workflow_text


def test_refresh_commit_step_restores_runtime_artifacts_before_commit() -> None:
    workflow_text = _read(WORKFLOW_PATH)
    commit_block = _step_block(workflow_text, "Commit and push changes")

    assert 'for runtime_path in \\' in commit_block
    assert 'git ls-files --error-unmatch "$runtime_path"' in commit_block
    assert 'restore --source=HEAD --worktree --staged -- "$runtime_path"' in commit_block
    assert 'artifacts/databento_volatility_cache/' in commit_block
    assert 'artifacts/monitoring/provider_usage.json' in commit_block
    assert 'artifacts/smc_microstructure_exports/smc_live_news_snapshot.json' in commit_block
    assert 'artifacts/smc_microstructure_exports/smc_live_news_state.json' in commit_block
    # Workflow `git add` step was expanded by PR #13 into a multi-line continuation
    # listing all 14 Pine consumers. Pin each required path individually instead of a
    # single concatenated substring so further consumer additions don't silently break
    # the assertion form.
    assert 'git add pine/generated/ \\' in commit_block
    for path in (
        'SMC_Long_Dip_Suite.pine',
        'SMC_Long_Dip_Dashboard.pine',
        'SMC_Long_Dip_Mobile.pine',
        'SMC_Long_Dip_Strategy.pine',
        'SMC_Confluence_Hub.pine',
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
        assert path in commit_block, f"workflow git add step missing: {path}"
    assert 'Unexpected tracked changes remain unstaged before refresh commit.' in commit_block


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
    a `bot/library-refresh-${run_id}-${attempt}` PR with the `automated` label and arms
    auto-merge — same pattern as `run-open-prep-daily.yml` and
    `open-prep-outcome-backfill.yml`. Pin the new mechanism so the next
    refactor doesn't silently regress us back to direct-push (which would
    fail at runtime with GH013)."""
    workflow_text = _read(WORKFLOW_PATH)

    # Bot/* branch naming pinned to run id + attempt for re-run safety.
    assert 'BRANCH="bot/library-refresh-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"' in workflow_text
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
    assert '- name: Best-effort normalize TradingView post-release validation' in workflow_text
    assert '- name: Refresh gate evidence summary after post-release validation' in workflow_text
    assert 'TV_STORAGE_STATE_MAX_AGE_HOURS: "72"' in workflow_text
    assert 'tv_post_release_validation.json' in workflow_text
    assert '"$SMC_PYTHON_BIN" scripts/run_smc_post_release_validation.py' in workflow_text
    assert '--ci-mode' in workflow_text
    assert 'smc_post_release_validation_report.json' in workflow_text
    assert 'TradingView post-release validation' in workflow_text
    assert 'TradingView post-release validation failed' in workflow_text
    assert "steps.release_gates.outcome == 'success'" in workflow_text


def test_refresh_workflow_commit_gates_on_policy_not_raw_validation_outcome() -> None:
    """Incident 2026-07-13: the commit step gated on the RAW post-release
    validation outcome AND the normalizer exit — both fail on the explicitly
    TOLERATED external_tv_drift class (surface_drift Playwright flakes), which
    dead-lettered the release_gates carve-out and silently skipped the commit
    for ~6 weeks (committed ASOF 2026-05-27 vs published 2026-07-13) while the
    run stayed green. The commit must gate on the PUBLISH outcome plus the
    policy-aware strict release gates ONLY; a genuine blocking verdict fails
    release_gates (no continue-on-error) and turns the job red — never a
    silent skip."""
    workflow_text = _read(WORKFLOW_PATH)

    commit_idx = workflow_text.index('- name: Commit and push changes')
    commit_end = workflow_text.index('- name: ', commit_idx + 10)
    commit_block = workflow_text[commit_idx:commit_end]

    # Policy-aware gates the commit MUST keep.
    assert "steps.publish.outcome == 'success'" in commit_block
    assert "steps.release_gates.outcome == 'success'" in commit_block
    assert "steps.publish_gate.outputs.publish_allowed == 'true'" in commit_block
    # Raw/normalizer outcomes must NOT gate the commit (they fail on the
    # tolerated external_tv_drift class that release_gates deliberately allows).
    assert "steps.tv_post_release_raw.outcome == 'success'" not in commit_block
    assert "steps.tv_post_release.outcome == 'success'" not in commit_block
    # The release_gates step itself must stay hard-failing (no continue-on-error),
    # so a genuine blocking verdict reds the job instead of silently skipping.
    gates_idx = workflow_text.index('- name: Run strict release gates')
    gates_end = workflow_text.index('- name: ', gates_idx + 10)
    assert 'continue-on-error' not in workflow_text[gates_idx:gates_end]


def test_refresh_workflow_restores_optional_runtime_artifacts_individually() -> None:
    """One absent optional cache path must not block every tracked restore."""
    workflow_text = _read(WORKFLOW_PATH)
    commit_idx = workflow_text.index('- name: Commit and push changes')
    commit_end = workflow_text.index('- name: ', commit_idx + 10)
    commit_block = workflow_text[commit_idx:commit_end]

    assert 'for runtime_path in' in commit_block
    assert 'git ls-files --error-unmatch "$runtime_path"' in commit_block
    assert 'restore --source=HEAD --worktree --staged -- "$runtime_path"' in commit_block
    assert 'artifacts/monitoring/provider_usage.json' in commit_block
    assert 'artifacts/smc_microstructure_exports/smc_live_news_snapshot.json' in commit_block
    assert 'artifacts/smc_microstructure_exports/smc_live_news_state.json' in commit_block


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
    assert workflow_text.index('- name: Best-effort normalize TradingView post-release validation') < workflow_text.index('- name: Run strict release gates')


def test_refresh_workflow_normalizes_soft_failed_post_release_validation() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    normalize_idx = workflow_text.index('- name: Best-effort normalize TradingView post-release validation')
    gates_idx = workflow_text.index('- name: Run strict release gates', normalize_idx)
    normalize_block = workflow_text[normalize_idx:gates_idx]

    assert 'continue-on-error: true' in normalize_block
    assert "steps.tv_post_release_raw.outcome == 'success'" not in normalize_block
    assert 'scripts/run_smc_post_release_validation.py' in normalize_block
    assert '--output artifacts/ci/smc_post_release_validation_report.json' in normalize_block
    assert 'if "$SMC_PYTHON_BIN" scripts/run_smc_post_release_validation.py' in normalize_block
    assert '_normalizer_rc=$?' in normalize_block
    assert 'Post-release validation normalized status:' in normalize_block
    assert 'Post-release validation primary blocker:' in normalize_block
    assert 'Post-release validation failure codes:' in normalize_block
    assert 'GITHUB_STEP_SUMMARY' in normalize_block
    assert 'exit "${_normalizer_rc}"' in normalize_block


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


# -- F-V8-N1: Surface blocked-publish state on breaking-change classification ---
# Regression guard for 2026-04-13 -> 2026-05-28 silent publish-skip incident
# (TradingView publishedVersion stuck at v1 while v5.5c/v6.0a/v7.0a stacked
# unpublished). Pins three escape hatches: ::error annotation + summary block,
# auto-opened release-pending PR, operator-override dispatch input.


def test_breaking_change_emits_error_annotation_not_warning() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    assert "::error file=.github/workflows/smc-library-refresh.yml,title=Breaking change blocks publish::" in workflow_text
    # Silent ::warning::-only path was the bug — must not regress.
    assert "::warning::Breaking change detected" not in workflow_text


def test_breaking_change_writes_step_summary_block() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    assert "Library publish blocked — breaking change" in workflow_text
    assert '>> "$GITHUB_STEP_SUMMARY"' in workflow_text
    # Sticky artifact channel — surfaces blocked state even after run scrolls off list.
    assert "artifacts/ci/release_pending.flag" in workflow_text


def test_workflow_dispatch_allow_breaking_publish_input_exists() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    assert "allow_breaking_publish:" in workflow_text
    assert "Only honored on workflow_dispatch against refs/heads/main" in workflow_text


def test_publish_gate_combines_breaking_with_operator_override() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    # Single source of truth for the publish gate.
    assert "- name: Compute publish gate" in workflow_text
    assert "id: publish_gate" in workflow_text
    # Override is only honored on workflow_dispatch against main (defence in depth).
    assert 'IS_DISPATCH: ${{ github.event_name == \'workflow_dispatch\' }}' in workflow_text
    assert 'IS_MAIN: ${{ github.ref == \'refs/heads/main\' }}' in workflow_text
    assert "ALLOW_BREAKING: ${{ inputs.allow_breaking_publish }}" in workflow_text
    # Loud notification when override is in effect.
    assert "Operator override active" in workflow_text


def test_publish_steps_consume_publish_gate_not_raw_breaking_flag() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    # All publish/bump/commit gates flow through publish_gate so the
    # operator-override path can never be skipped piecemeal.
    publish_gate_refs = workflow_text.count("steps.publish_gate.outputs.publish_allowed == 'true'")
    assert publish_gate_refs >= 9, (
        f"expected >=9 publish-gate references (one per publish/bump/commit/validation step), "
        f"got {publish_gate_refs}"
    )
    # The raw breaking-flag conditional must NOT be used on any publish step —
    # everything routes through publish_gate so the override input takes effect.
    assert "steps.breaking.outputs.breaking != 'true'" not in workflow_text


def test_workflow_opens_release_pending_pr_on_breaking() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    assert "- name: Open release-pending PR (on breaking change)" in workflow_text
    assert "id: release_pending_pr" in workflow_text
    assert "bot/library-release-pending-${GITHUB_RUN_ID}" in workflow_text
    assert "--label release-pending" in workflow_text
    assert "--label breaking-change" in workflow_text
    assert "--label automated" in workflow_text
    # Must use GH_PAT-with-fallback pattern so downstream checks fire.
    # The auto-PR step is the first user of that pattern *after* the gate;
    # an exact match would over-constrain — assert the substring instead.
    assert "secrets.GH_PAT != '' && secrets.GH_PAT || github.token" in workflow_text
    # MUST NOT silently swallow PR-creation failure (F-V6-I2.1 lesson).
    assert "gh pr create failed for release-pending branch" in workflow_text


def test_release_pending_pr_step_only_runs_when_publish_blocked() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    # Auto-PR must NOT open when override is active (we're publishing instead).
    # The if: condition must reference publish_allowed != 'true' as the gate.
    assert "steps.publish_gate.outputs.publish_allowed != 'true'" in workflow_text
    # Never on pull_request triggers (no write perms / would loop).
    assert "github.event_name != 'pull_request'" in workflow_text


def test_readonly_preflight_has_retry_wrapper() -> None:
    """Pin the retry wrapper added in PR #2418.

    The readonly TradingView preflight failed in run 26588691660 with a
    transient Playwright timeout in ``addCurrentScriptToChart`` (45s),
    blocking the v1→v2 publish even though PR #2415's override gate was
    correct. PR #2418 wrapped the step in a bash retry loop with
    exponential backoff. Without this pin the wrapper could be silently
    reverted by an unrelated edit and the publish path becomes fragile
    again.

    Scope: ONLY the readonly preflight gets retries — the actual publish
    and post-release validation must still surface their failures
    immediately (no auto-retry on the mutating step).
    """
    workflow_text = _read(WORKFLOW_PATH)

    # Env vars driving the wrapper.
    assert 'TV_PREFLIGHT_MAX_ATTEMPTS: "3"' in workflow_text, (
        "Readonly preflight must declare TV_PREFLIGHT_MAX_ATTEMPTS=3 so the "
        "step retries known-flaky TV/Playwright timeouts before failing the "
        "publish job (PR #2418)."
    )
    assert 'TV_STEP_TIMEOUT_MS: "90000"' in workflow_text, (
        "Readonly preflight must bump TV_STEP_TIMEOUT_MS to 90000 (vs the "
        "shared 45000 default) so CI's slower chart hydration does not "
        "trip a single-attempt timeout (PR #2418)."
    )

    # Loop structure.
    assert "max_attempts=" in workflow_text and 'TV_PREFLIGHT_MAX_ATTEMPTS' in workflow_text
    assert "while [ \"$attempt\" -le \"$max_attempts\" ]" in workflow_text
    # Final failure must surface as ::error::, not ::warning::.
    assert "::error title=TradingView preflight failed::" in workflow_text
    # Intermediate retries must surface as ::warning::, otherwise operators
    # have no signal that the flake is recurring.
    assert "::warning title=TradingView preflight flake::" in workflow_text

    # Scope guard: the retry env vars must NOT leak onto the mutating
    # publish step or the post-release validation. Those failures need to
    # surface immediately. We pin the wrapper inside the readonly preflight
    # by requiring the retry env var to appear ONLY between the readonly
    # preflight step header and the next step ("Publish library to TradingView").
    pre_idx = workflow_text.index("Run TradingView readonly preflight")
    publish_idx = workflow_text.index("Publish library to TradingView", pre_idx)
    post_idx = workflow_text.index("Run TradingView post-release validation", publish_idx)
    preflight_block = workflow_text[pre_idx:publish_idx]
    publish_block = workflow_text[publish_idx:post_idx]
    post_release_block = workflow_text[post_idx:]
    assert "preflight-smc-mainline-open-only.json" in preflight_block, (
        "Pre-publish readonly preflight must only prove reusable auth and "
        "private script visibility. Full chart/input binding validation belongs "
        "to post-release validation after the publish updates stale TV scripts."
    )
    assert "preflight-smc-mainline.json" in post_release_block, (
        "Post-release validation must keep the full SMC mainline preflight."
    )
    assert "TV_PREFLIGHT_MAX_ATTEMPTS" in preflight_block, (
        "TV_PREFLIGHT_MAX_ATTEMPTS must live inside the readonly preflight step block."
    )
    assert "TV_PREFLIGHT_MAX_ATTEMPTS" not in publish_block, (
        "Retry wrapper must NOT leak onto the mutating publish step — "
        "an actual publish failure must surface on the first attempt."
    )
    assert 'TV_STEP_TIMEOUT_MS: "90000"' in publish_block, (
        "The mutating publish step must keep the same CI-sized TV step budget "
        "as the readonly preflight, while still surfacing publish failures on "
        "the first attempt."
    )
    assert "TV_PREFLIGHT_MAX_ATTEMPTS" not in post_release_block, (
        "Retry wrapper must NOT leak onto post-release validation — that "
        "step already has continue-on-error: true semantics and additional "
        "retries would mask validator regressions."
    )


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
    assert classify_artifact_drift("SMC_Long_Dip_Suite.pine") == DRIFT_CLASS_STAGE_ONLY
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


# -- Phase 2: provider credential preflight gates generation ------------------
# Run #412 burned ~144min of generation before the runner was shut down while
# Databento was billing-delinquent (HTTP 402). A preflight that fails fast on
# missing/expired keys or a delinquent invoice must run BEFORE the expensive
# generation step, reusing scripts/credential_health_check.py.


def test_refresh_runs_provider_preflight_before_generation() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    assert '- name: Provider credential preflight' in workflow_text
    assert 'scripts/credential_health_check.py' in workflow_text
    assert '--skip-tv' in workflow_text
    assert '--skip-gh-pat' in workflow_text
    # NEWSAPI_KEY remains optional: if missing, the workflow explicitly skips
    # the NewsAPI probe instead of hard-failing preflight on an empty key.
    assert 'NEWSAPI_KEY not set — skipping optional NewsAPI preflight probe.' in workflow_text
    assert 'newsapi_arg+=(--skip-newsapi)' in workflow_text
    assert '--databento-key-env DATABENTO_API_KEY' in workflow_text
    # The script returns exit 2 for *both* warn and error, so the gate must
    # branch on overall_severity from the JSON report, not on the exit code.
    # Use the actual bash json-extraction expression as the anchor (not a comment).
    assert ".get('overall_severity'" in workflow_text
    assert '"$severity" = "error"' in workflow_text
    # Preflight must gate the generation step, not trail it. Anchor on the
    # step `- name:` markers (the comment header also mentions the phrase).
    assert '- name: Generate SMC library with v5 enrichment' in workflow_text
    assert workflow_text.index('- name: Provider credential preflight') < workflow_text.index(
        '- name: Generate SMC library with v5 enrichment'
    )


def test_preflight_step_wires_benzinga_key_and_provider() -> None:
    """The preflight probes Benzinga (no --skip-benzinga) and Benzinga is
    load-bearing (2026-07-08: open_prep Core News + live-news cron), so the
    preflight STEP env must inject the key AND transport. File-level presence
    (the later Generate step already has it) is not enough — the preflight
    aborts on an empty key long before generation, so the gate would always
    fail on Benzinga regardless of the secret (regression fixed 2026-07-09)."""
    block = _step_block(_read(WORKFLOW_PATH), "Provider credential preflight")
    assert "--skip-benzinga" not in block, (
        "preflight probes Benzinga; if that ever changes, retire this guard"
    )
    assert "BENZINGA_API_KEY: ${{ secrets.BENZINGA_API_KEY }}" in block, (
        "preflight step must pass BENZINGA_API_KEY into env or the probe sees an empty key"
    )
    assert "BENZINGA_PROVIDER:" in block, (
        "preflight step must pass BENZINGA_PROVIDER — a Massive key on the direct transport 401s"
    )


_PRODUCER_PATH = ROOT / ".github/workflows/smc-databento-production-export-sharded.yml"


def _earliest_producer_cron_hour() -> int:
    """Earliest weekday producer tick hour (UTC) parsed from the cron block.

    Cron format is ``"MIN HOUR DOM MON DOW"`` so the hour is the 2nd field.
    Parsed from raw text to sidestep the YAML 1.1 ``on:`` -> ``True`` gotcha.
    """
    hours = {
        int(hour)
        for _minute, hour in re.findall(
            r"-\s*cron:\s*[\"']?(\d+)\s+(\d+)", _read(_PRODUCER_PATH)
        )
    }
    assert hours, "producer workflow has no parseable cron ticks"
    return min(hours)


def test_stale_fallback_guard_disarmed_before_producer_first_tick() -> None:
    """Cross-midnight false-red guard (F-V8-C4.3, 2026-07-11).

    GitHub scheduler lag can push the last nightly consumer tick
    (cron ``0 23 * * 1-5``) past 00:00 UTC. ``REFRESH_DATE`` is stamped from
    the *execution*-time wall clock, so it then rolls to the next calendar day
    and the same-date producer match demands a bundle that does not exist yet
    (on a Fri->Sat crossing it can never exist — the producer runs Mon-Fri).
    The prior evening's bundle is ~1-2 h old and NOT stale, so the reject-stale
    guard must stay disarmed until a same-date producer bundle is actually due.
    """
    workflow_text = _read(WORKFLOW_PATH)

    # 'Set refresh date' computes the arm flag from the current UTC hour.
    date_block = _step_block(workflow_text, "Set refresh date")
    assert "id: set_refresh_date" in date_block
    assert 'echo "stale_guard_active=${GUARD}" >> "$GITHUB_OUTPUT"' in date_block
    # 10#-prefixed arithmetic so zero-padded 08/09 don't trip bash octal parsing.
    assert "10#$REFRESH_UTC_HOUR" in date_block

    # The reject-stale guard fires only when armed.
    stale_guard_block = _step_block(
        workflow_text, "Reject stale Databento fallback on automated refresh"
    )
    assert (
        "steps.set_refresh_date.outputs.stale_guard_active == 'true'"
        in stale_guard_block
    )
    # The original hard-fail contract is preserved for genuine daytime staleness.
    assert "github.event_name != 'workflow_dispatch'" in stale_guard_block
    assert "Refusing to generate from a stale producer bundle" in stale_guard_block

    # The disarmed (overnight) path is auditable, not silent.
    note_block = _step_block(workflow_text, "Note tolerated overnight Databento fallback")
    assert "stale_guard_active != 'true'" in note_block
    assert "::notice::" in note_block

    # The arm hour must equal the producer's earliest daily tick so the window
    # stays tied to the real schedule if the producer cron ever moves.
    arm_hour = int(
        re.search(r"PRODUCER_FIRST_TICK_UTC_HOUR=(\d+)", date_block).group(1)
    )
    assert arm_hour == _earliest_producer_cron_hour(), (
        "stale-fallback guard arm hour drifted from the producer's earliest cron tick"
    )

def test_refresh_workflow_repins_consumers_from_real_published_version() -> None:
    """Incident 2026-07-13 (CE10272): NEW_VERSION came from the generator
    manifest's hardcoded ``library_version: 1``, so the repin rewrote every
    consumer to the 2026-03 v1 library on each refresh while TradingView was at
    v164. The bump step must read the publisher's facade-verified
    ``library.publishedVersion`` from the release manifest, refuse non-integer
    values, and SKIP (not rewrite) on the stale sentinel 1."""
    workflow_text = _read(WORKFLOW_PATH)

    bump_idx = workflow_text.index('- name: Bump library version in all pine consumers')
    bump_end = workflow_text.index('- name: ', bump_idx + 10)
    bump_block = workflow_text[bump_idx:bump_end]

    assert "jq -r '.library.publishedVersion' artifacts/tradingview/library_release_manifest.json" in bump_block
    assert "jq -r '.library_version' pine/generated/smc_micro_profiles_generated.json" not in bump_block
    assert 'is not an integer' in bump_block
    assert 'stale-evidence sentinel' in bump_block
