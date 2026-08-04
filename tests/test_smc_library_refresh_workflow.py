from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

from scripts.check_tv_unattested_sources import RESOLUTION
from scripts.smc_r1_rollout_contract import EXECUTION_EVIDENCE
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
from tests._workflow_step_shell import run_step, step_by_name

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
        "Restore sufficiently deep Databento production export bundle",
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
    # 2026-07-22 (issue #3872 aftermath): provider-enriched again — the
    # static flip (#3790) removed universe/VIX/event-risk/trust from the
    # published library while the runtime sidecar does not carry them yet.
    assert "--enrich-all" in generate_block
    assert "--static-only" not in generate_block
    assert "FMP_API_KEY" in generate_block
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
    assert 'TV_STEP_TIMEOUT_MS: "240000"' in publish_block, (
        "The mutating publish step needs a LARGER budget than the readonly "
        "preflight: it writes a ~83 KB provider-enriched library into the Pine "
        "editor and adds it to a chart (6x the static library's content). Two "
        "enriched publishes died at exactly the old 90 s budget (2026-07-22). "
        "Failures still surface on the first attempt — no retry wrapper."
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
    # 2026-08-03: the NewsAPI probe is now skipped UNCONDITIONALLY (retired
    # 2026-07-08). The former conditional skip only fired when the secret was
    # absent, which let a present-but-401 key hard-block the refresh — see
    # test_preflight_does_not_gate_on_retired_newsapi for the full mechanism.
    assert '--skip-newsapi' in workflow_text
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


def test_preflight_does_not_gate_on_retired_newsapi() -> None:
    """Mirror of the Benzinga guard for a RETIRED provider: NewsAPI.ai must not
    be able to hard-block generation.

    NewsAPI.ai was retired 2026-07-08 (subscription cancelled). The 2026-07-10
    truth-audit demoted it to critical=False in scripts/probe_providers.py and
    skipped it in credential-health-check.yml — but THIS workflow was missed and
    kept probing it at severity=error. The dead key still answered HTTP 200
    until 2026-08-01, so the miss stayed invisible for ~3 weeks; it then went
    401 and permanently blocked the daily refresh (run 30805042119).

    The asymmetry was the defect: an ABSENT key was skipped with a warning,
    while a PRESENT-but-invalid key aborted the whole run — so an optional
    provider blocked harder when broken than when removed. Nothing here can
    consume it either way: ENABLE_NEWSAPI_AI defaults OFF and this workflow
    never sets it, so newsstack_fmp.config never adds newsapi_ai to sources.
    """
    block = _step_block(_read(WORKFLOW_PATH), "Provider credential preflight")
    assert "--skip-newsapi" in block, (
        "retired NewsAPI probe must be skipped; a cancelled subscription's key 401s forever"
    )
    assert "secrets.NEWSAPI_KEY" not in block, (
        "preflight step must not wire the retired NewsAPI secret — a present-but-dead "
        "key is what turned this into a hard block"
    )
    # Unconditional skip: the old conditional only skipped when the key was
    # ABSENT, which is precisely the branch that never fired here.
    assert "newsapi_arg" not in block, (
        "skip must be unconditional, not gated on the secret being absent"
    )


def test_refresh_workflow_never_wires_retired_newsapi_secret() -> None:
    """Whole-file guard mirroring the existing "must not be re-added" pins in
    tests/test_workflow_predictive_review_guards.py and
    tests/test_smc_live_newsapi_refresh_structural_pin.py.

    #4335 stopped the preflight from gating on the retired provider, but the
    Generate step kept passing the secret. That was already dead weight — every
    consumption site is gated on ``enable_newsapi_ai AND newsapi_ai_key``
    (newsstack_fmp/pipeline.py:850,1032) and ENABLE_NEWSAPI_AI defaults OFF —
    and a configured-but-dead secret is exactly what let a retired provider
    reach a gate in the first place. Keep it out of the whole file so the next
    reader cannot mistake it for a live dependency.
    """
    workflow_text = _read(WORKFLOW_PATH)
    assert "secrets.NEWSAPI_KEY" not in workflow_text, (
        "NEWSAPI_KEY must not be re-added (NewsAPI.ai retired 2026-07-08); "
        "re-granting means flipping ENABLE_NEWSAPI_AI on as well"
    )
    # The YAML-key form only — prose may name the flag (the comments above the
    # preflight and Generate steps explain the retirement and cite it).
    assert "ENABLE_NEWSAPI_AI:" not in workflow_text, (
        "enabling the retired provider needs an explicit decision, not a silent env flip"
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


def test_refresh_reports_r1_attestation_drift_it_causes() -> None:
    """A refresh that un-attests an R1 source must SAY so — loudly, and in the PR.

    The bump step repins every pine consumer, and ``SMC_Event_Overlay.pine`` is
    both a consumer and one of the two sources
    ``scripts/smc_r1_rollout_contract.py`` hashes into the R1 rollout contract.
    So the refresh can invalidate the registered evidence, and twice did:
    #4284 (2026-08-01, repaired four hours later by the manual re-attestation
    PR #4290) and #4371 (2026-08-04, unnoticed — ``main`` stayed red on
    ``tests/test_check_tv_unattested_sources.py`` for the next unrelated PR).

    The notice is deliberately NOT a hard failure: the library bump is
    legitimate and must still produce its PR. The ``run_pine_guard`` arm in
    ``smc-fast-pr-gates.yml`` (#4376, covered by
    ``tests/test_fast_gates_attested_pine_coverage.py``) is what stops that PR
    merging silently. This test pins the reporting half, which nothing else
    reads — a step no guard observes can be deleted in a green PR.
    """
    workflow_text = _read(WORKFLOW_PATH)
    block = _step_block(workflow_text, "Report R1 attestation drift caused by this refresh")

    # Derived, never hand-listed: the roster comes from the contract, so a
    # third attested source joins the notice automatically.
    assert "from scripts.smc_r1_rollout_contract import" in block
    assert "build_rollout_contract" in block
    assert "EXECUTION_EVIDENCE" in block
    for literal in ("SMC_Event_Overlay.pine", "SMC_Exit_Signal.pine"):
        assert literal not in block, (
            f"{literal} is hard-coded in the notice step; derive it from "
            "build_rollout_contract() so a third attested source is covered "
            "automatically"
        )
    # Unfiltered, matching tests/test_fast_gates_attested_pine_coverage.py.
    # Filtering to *.pine here would silently drop a future attested target
    # under a path the fast-gates data-only exemption already covers.
    assert ".endswith" not in block, (
        "the notice step filters the derived roster; every contract target is "
        "hashed and un-attests the rollout when it changes, whatever its "
        "extension — keep the derivation unfiltered, as the coverage guard is"
    )

    # The all-clear must rest on a HASH COMPARISON, not on an empty
    # `git diff HEAD`. Those answer different questions, and the step used to
    # publish the answer to the second as if it were the answer to the first.
    # Imported from the guard that owns it — re-deriving the comparison here
    # would compare one implementation against another instead of against the
    # evidence, which is the reason check_tv_unattested_sources exists at all.
    assert "drifted_attested_targets" in block, (
        "the notice step reaches its all-clear from `git diff HEAD` alone, so "
        "it states that the registered evidence still describes sources whose "
        "hashes it never read. Import drifted_attested_targets from "
        "scripts/check_tv_unattested_sources and gate the all-clear on it."
    )
    assert "sha256" not in block, (
        "the notice step hashes sources itself; call "
        "drifted_attested_targets() instead, so one comparison is measured "
        "against the evidence rather than two against each other"
    )

    # Non-vacuity witness, and it must read the floor from the contract rather
    # than carrying a second unlinked copy of the number.
    assert "refusing to report a vacuous R1 all-clear" in block
    assert "MIN_ATTESTED_SOURCES" in block
    assert "< 2" not in block, (
        "the non-vacuity floor is hard-coded in the notice step; import "
        "MIN_ATTESTED_SOURCES from scripts/smc_r1_rollout_contract.py so a "
        "legitimate roster change cannot leave this copy behind"
    )

    # The remedy prose is IMPORTED, not re-typed — a third hand-copy would go
    # stale the first time a resolution path changes.
    #
    # Asserted as "imported from that module", not as one exact line: the step
    # legitimately grew a parenthesised multi-line import when it began pulling
    # drifted_attested_targets alongside RESOLUTION, and a pin on the one-line
    # spelling fails on a change that satisfies everything it cares about. What
    # matters is the source of the name, so both halves are checked separately.
    assert "from scripts.check_tv_unattested_sources import" in block
    assert re.search(r"^\s*RESOLUTION,?\s*$", block, re.MULTILINE) or (
        "import RESOLUTION" in block
    ), (
        "the notice step does not import RESOLUTION from "
        "scripts/check_tv_unattested_sources; the remedy prose has one owner "
        "and re-typing it is how the four hand-copies drifted apart"
    )
    assert "RESOLUTION.format(evidence=evidence)" in block
    assert "Re-attest" not in block, (
        "the notice step re-types the resolution prose that "
        "scripts/check_tv_unattested_sources.RESOLUTION already owns; import "
        "it instead"
    )
    assert "GITHUB_STEP_SUMMARY" in block

    # …and the imported constant must still carry the semantics the notice
    # promises. Pinning only the import would let the shared prose lose the
    # prohibition without any test noticing.
    resolution = RESOLUTION.format(evidence="EVIDENCE_PATH")
    assert "Re-attest" in resolution
    assert "NEW dated evidence artifact" in resolution
    assert "Revert the source change" in resolution
    assert "never rewritten" in resolution
    assert "replaces a measurement with a fabrication" in resolution
    assert "EVIDENCE_PATH" in resolution, (
        "the resolution text must name the evidence artifact it is talking about"
    )

    # Rendered width. The evidence path is ~66 characters, so interpolating it
    # mid-sentence produced a 189-character line: it broke the 80-column stderr
    # block on the save path and forced horizontal scrolling inside the fenced
    # block in this PR body. Measured against the REAL path, not a short stub,
    # because a stub would not reproduce the defect.
    real = RESOLUTION.format(evidence=EXECUTION_EVIDENCE.relative_to(ROOT).as_posix())
    widest = max(len(line) for line in real.splitlines())
    assert widest <= 80, (
        f"the rendered resolution has a {widest}-character line; keep the "
        "{evidence} placeholder on a line of its own so both consumers stay "
        "inside 80 columns"
    )

    # A notice, not a gate — and now NO verdict fails the step at all. Step
    # order in job `refresh`: publish-to-TradingView (37) < this notice (45) <
    # 'Commit and push changes' (46), whose `if:` implies success(). A fatal
    # exit here would therefore leave the library published with the repo pins
    # never committed — the 2026-07-13 divergence class, worse than losing the
    # PR. GitHub runs `run:` under `bash -e`, so the handling is what makes
    # that true.
    assert "except Exception:" in block
    assert "SystemExit" not in block, (
        "the notice step can still fail on a verdict it reached; route every "
        "such path through the 'could not run' report instead. A red step here "
        "skips 'Commit and push changes' and strands a PUBLISHED library on "
        "uncommitted pins."
    )
    assert "could not run" in block, (
        "a check that reached no verdict must say so in the PR body — silence "
        "there is indistinguishable from 'no drift'"
    )
    # The vacuity floor stays loud, and shares the crash report rather than
    # printing an all-clear: def + the crash call site + the vacuity call site.
    assert "refusing to report a vacuous R1 all-clear" in block
    assert block.count("cannot_run(") >= 3, (
        "the short-roster path must render the same 'could not run' report as "
        "a raised exception; printing 'Checked 0 attested source(s)' is a green "
        "all-clear that would survive indefinitely"
    )
    # Written once, outside every branch, so no report path can be skipped —
    # and counted on the actual write, not on prose that happens to name the
    # file.
    assert block.count('os.environ["GITHUB_STEP_SUMMARY"]') == 1
    assert block.count('os.environ["GITHUB_OUTPUT"]') == 1
    assert 'os.environ["GITHUB_ENV"]' not in block, (
        "the notice publishes through $GITHUB_ENV again. An env write leaks "
        "into every later step in the job, while an output is addressed; "
        "tv-save-consumer-source.yml documents the same rule, and zizmor "
        "rates the env form a github-env HIGH — one it cannot see here, "
        "because the write sits inside a Python heredoc (measured 2026-08-04 "
        "with the pinned zizmor 1.25.2: four github-env HIGHs in this file, "
        "none of them this step)."
    )

    # It must run BEFORE the commit step that consumes its output.
    notice_idx = workflow_text.index("      - name: Report R1 attestation drift caused by this refresh")
    commit_idx = workflow_text.index("      - name: Commit and push changes")
    assert notice_idx < commit_idx

    # The notice reaches a reviewer who never opens the run log — asserted as an
    # agreement between the two steps, not as three substrings that can all hold
    # while the wiring is severed. Measured 2026-08-04 on the landed PR: renaming
    # the variable the guarded branch ASSIGNS (so the augmented body is built and
    # then dropped, and `--body` still ships the un-augmented one) left every
    # substring present and all 43 tests green.
    commit_block = _step_block(workflow_text, "Commit and push changes")

    # The chain has FOUR links now that the notice travels as a step output
    # rather than as an env var, and every one of them is derived from the
    # workflow rather than re-typed here. Any single break makes the PR ship
    # without the drift verdict, which is the thing #4371 proved matters.
    written = re.search(r'handle\.write\(f"(\w+)<<\{(\w+)\}\\n"\)', block)
    assert written, (
        "the notice step no longer writes a heredoc-delimited step OUTPUT, so "
        "nothing can carry it into the PR body"
    )
    output_name = written.group(1)

    step_id = re.search(r"^        id: (\S+)$", block, re.M)
    assert step_id, (
        "the notice step has no `id:`, so no later step can address its output"
    )

    bound = re.search(
        rf"^\s*(\w+): \$\{{\{{ steps\.{step_id.group(1)}\.outputs\.{output_name} \}}\}}$",
        commit_block,
        re.M,
    )
    assert bound, (
        f"the commit step does not bind steps.{step_id.group(1)}.outputs."
        f"{output_name} into its `env:` block, so the notice never reaches the "
        "shell that builds the PR body"
    )
    notice_var = bound.group(1)

    guard = f'if [ -n "${{{notice_var}:-}}" ]; then'
    assert guard in commit_block, (
        f"the commit step does not read {notice_var}, which is the variable the "
        f"notice step publishes. Expected: {guard}"
    )

    appended = re.search(
        rf'^\s*(\w+)=.*\$\{{{notice_var}\}}', commit_block, re.M
    )
    assert appended, (
        f"nothing in the commit step assigns {notice_var} into another variable, "
        "so the notice is read and discarded"
    )
    body_var = appended.group(1)

    assert f'--body "${body_var}"' in commit_block, (
        f"the commit step appends the notice into ${body_var}, but passes a "
        f"different variable to `gh pr ... --body`. The augmented body is built "
        f"and thrown away, and the PR ships without the drift verdict.\n"
        f"  notice variable : {notice_var}\n  appended into   : {body_var}"
    )


# ── Executing the notice step ────────────────────────────────────────────────
# Everything above matches SOURCE TEXT. #4377 settled what that is worth, one
# day earlier and in this same subsystem: deleting the single line that raised
# fast-gates' pine flag left all fourteen source-matching tests green while the
# guard went blind. Its title is "execute the pine gate instead of reading it".
#
# The argument binds harder here than it did there. This step's entire job is to
# SPEAK UP. If it silently stops working, the failure mode is a drift that goes
# unannounced — which is the exact defect the step was added to fix, restored
# without a trace and under a green suite. A reporting step nobody executes has
# the same shape as a guard that observes nothing.
#
# So the four branches below run the step's real `run:` block. The source-text
# assertions are kept, because they pin what execution cannot see: that the step
# exists at all, that it is ordered before the commit step, that it derives the
# roster instead of hand-listing it, and that it renders RESOLUTION instead of a
# hand-typed copy — a re-typed copy of today's prose would execute identically.

NOTICE_STEP = "Report R1 attestation drift caused by this refresh"


def test_every_pytest_node_id_the_workflow_prints_actually_resolves() -> None:
    """A remedy naming a test that no longer exists is worse than no remedy.

    The notice step prints `GUARD` — a hand-typed pytest node ID — into the job
    summary AND the PR body on all three non-clean branches: "Run <GUARD>
    against this branch before merging." Nothing anywhere asserted that it
    resolves. It is a re-typed reference to a moving target, which is the
    defect class this whole seam exists to close, one line above an IMPORTED
    `RESOLUTION`.

    Not hypothetical in this repository, and not slow-moving either: on
    2026-08-04 a test harness was renamed and moved (#4383), a PR written
    against its old location merged (#4385), and `main` went red on the
    ImportError. Under that kind of churn a hand-typed node ID is a promise
    nobody keeps. The operator reading it is, by construction, someone who has
    just been told the attestation is broken — handing them a command that
    errors with "no tests ran" is the worst possible moment for it.

    So COLLECT it. `--collect-only` resolves the file, the class and the test
    name without executing anything, and fails loudly on any of the three.
    """
    node_ids = sorted(
        set(re.findall(r"tests/[\w/]+\.py::[\w:]+", _read(WORKFLOW_PATH)))
    )
    assert node_ids, (
        "no pytest node ID found in the workflow. If the notice step stopped "
        "naming the guard to run, an operator told the attestation is UNKNOWN "
        "is left without the command that checks it — and this test is now "
        "observing nothing, which is the failure it was written against."
    )

    for node_id in node_ids:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", node_id],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTEST_ADDOPTS": "", "PY_COLORS": "0", "NO_COLOR": "1"},
        )
        assert result.returncode == 0, (
            f"{WORKFLOW_PATH.name} prints {node_id!r} as the command to run, and "
            f"pytest cannot collect it (rc={result.returncode}). The workflow "
            "publishes that string into the job summary and the PR body, so the "
            "operator it is written for would get an error instead of a check.\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
        assert " 1 test collected" in result.stdout or "\n1 test" in result.stdout, (
            f"{node_id!r} collected something other than exactly one test:\n"
            f"{result.stdout}"
        )

# #4377's `_run_gate` was evaluated for reuse and does NOT fit, for three
# reasons rather than by preference: it stubs `gh` onto PATH and sets the gate's
# EVENT_NAME/HEAD_REF/PR_NUMBER/REPO/GH_TOKEN contract (this step reads none of
# them); it runs in the repository root, whereas these branches are induced
# through the working tree `git diff` sees, so cwd has to be controllable; and
# it parses `key=value` out of $GITHUB_OUTPUT, while this step publishes a job
# summary plus a heredoc-delimited output block. What IS reused is its
# form: the same bash invocation, so a bashism cannot pass here and fail in CI.


def _refresh_step(name: str) -> dict:
    """One step of job ``refresh``, parsed — not sliced out of the raw text."""
    import yaml

    doc = yaml.safe_load(_read(WORKFLOW_PATH))
    for step in doc["jobs"]["refresh"]["steps"]:
        if isinstance(step, dict) and step.get("name") == name:
            return step
    raise AssertionError(
        f"{WORKFLOW_PATH.name}: no step named {name!r} in job 'refresh'. "
        "Either it was renamed (update the constant in the same PR) or the "
        "notice was deleted — in which case a refresh un-attests R1 in silence "
        "again, and these tests must not report green."
    )


def _notice_run_block() -> str:
    """The notice step's own shell, read out of the parsed workflow."""
    return str(_refresh_step(NOTICE_STEP)["run"])


def _conjuncts(condition: str) -> set[str]:
    """The ``&&``-separated terms of a workflow ``if:`` expression."""
    return {term.strip() for term in condition.split("&&") if term.strip()}


def test_the_notice_step_runs_whenever_the_publish_that_causes_the_drift_runs() -> None:
    """The step's ``if:`` is load-bearing, and nothing else here reads it.

    Every executed branch below lifts ``step["run"]`` out of the YAML and runs
    it directly, so the gating condition is invisible to all of them. Measured
    2026-08-04 on the landed PR: setting this step's ``if:`` to ``false`` — the
    step can then never run in CI, which is #4371 restored in full — left all 43
    tests in this file GREEN. A reporting step that cannot execute reports
    nothing, and the suite could not tell.

    Two relations, both asserted rather than a literal copy of today's
    expression:

    * **Equal to the publish step's.** ``Publish library to TradingView`` is
      what pushes the bumped library and therefore what causes the drift this
      step announces. Any run that can drift R1 must reach the announcement.
    * **A subset of the commit step's.** ``Commit and push changes`` opens the
      PR the notice is written into. Were the notice's condition ever the wider
      one, a run could publish a PR body referring to a notice that never ran.
    """
    notice = _refresh_step(NOTICE_STEP)
    publish = _refresh_step("Publish library to TradingView")
    commit = _refresh_step("Commit and push changes")

    condition = notice.get("if")
    assert condition, (
        f"the {NOTICE_STEP!r} step has no `if:`. It would then run on every "
        "event this job accepts, including the pull_request runs where nothing "
        "is published and there is no drift to announce."
    )

    assert _conjuncts(condition) == _conjuncts(str(publish["if"])), (
        "the notice no longer runs exactly when the publish that causes the "
        f"drift runs.\n  notice : {condition}\n  publish: {publish['if']}\n"
        "A narrower condition here means a refresh can un-attest R1 in silence "
        "— the defect this step exists to close."
    )

    missing = _conjuncts(condition) - _conjuncts(str(commit["if"]))
    assert not missing, (
        f"the notice step gates on {sorted(missing)}, which 'Commit and push "
        "changes' does not require. The commit step would then open a PR whose "
        "body interpolates a notice that never ran."
    )


def _attested_roster() -> list[str]:
    """The roster the step derives, derived the same way for the fixture."""
    from scripts.smc_r1_rollout_contract import build_rollout_contract

    return sorted({str(t["path"]) for t in build_rollout_contract()["targets"]})


def _evidence_matching_the_repository() -> dict[str, dict[str, str]]:
    """An evidence ``sources`` map that attests exactly what the repo holds.

    The step's all-clear is a real comparison of the contract's hashes against
    the REGISTERED evidence, and it reads that evidence out of the repository
    under test. A fixture that injected nothing would therefore make the clean
    branch depend on whether main happens to be attested today: green for the
    wrong reason while it is, and flipped to the drift branch the next time a
    refresh lands. That state dependence is the vacuity #4267 spent a PR
    removing, and it is exactly what the seeded git repo already avoids for the
    other input.

    Only the EVIDENCE side is injected. ``drifted_attested_targets`` still runs
    its real comparison against the real ``build_rollout_contract()`` hashes,
    so a step that stopped comparing fails these tests.
    """
    from scripts.smc_r1_rollout_contract import build_rollout_contract

    return {
        str(target["scriptName"]): {"repositorySha256": str(target["sha256"])}
        for target in build_rollout_contract()["targets"]
    }


# Git's own environment variables OUTRANK ``cwd``. A `git commit` launched with
# cwd=<sandbox> still writes to $GIT_DIR / $GIT_INDEX_FILE when those are set,
# because git resolves its repository from the environment first and only falls
# back to searching upward from the working directory.
#
# Git EXPORTS them into every hook it runs — which is exactly where this repo's
# guard suite executes (the pre-push hook). Measured 2026-08-04: the first
# version of these fixtures passed `cwd=` and nothing else, so under the hook
# `git add -A` + `git commit -qm seed` retargeted the REAL repository. It landed
# a commit subject "seed", author "t <t@example.invalid>", on the contributor's
# working branch, with 156 tracked files showing as deleted because the temp
# tree was committed against the real HEAD. It also broke an unrelated guard
# (test_mutable_defaults_and_loads_pins.py) by mutating the index underneath it,
# and recovery needed a manual branch reset. Every contributor who pushed would
# have hit it: deterministic, not a flake, and worse than the defect these tests
# guard against.
#
# So no git subprocess in this file — and no subprocess that may itself SHELL
# OUT to git, which includes the workflow step under test — may inherit the
# ambient environment.
#
# The scrub drops the whole GIT_* namespace rather than a curated list, so a
# variable git adds later cannot reopen this. These are the ones that would do
# the damage today, named so the intent is greppable and so
# test_the_git_fixtures_cannot_be_hijacked_by_an_ambient_git_dir can assert the
# scrub actually covers them:
_GIT_ENV_OVERRIDES = (
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_WORK_TREE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_CEILING_DIRECTORIES",
    "GIT_NAMESPACE",
    "GIT_PREFIX",
    "GIT_INDEX_VERSION",
)


# Identity passed per-invocation with `-c`, never `git config`. `git config`
# WRITES, and under the hijack above it wrote into the real repository's
# config — which is what turned a one-off bad commit into persistent damage:
# the checkout kept the fixture's identity, and every later commit was authored
# `t <t@example.invalid>`, an address scripts/check_commit_authors.py does not
# approve. Two real commits on two unrelated branches were stamped that way
# before it was noticed, one of them already pushed. `-c` writes nothing, so
# even a total isolation failure could not outlive the process.
_COMMIT_IDENTITY = (
    "-c",
    "user.email=fixture@example.invalid",
    "-c",
    "user.name=fixture",
    "-c",
    "commit.gpgsign=false",
)


def _isolated_env(sandbox: Path, **extra: str) -> dict[str, str]:
    """``os.environ`` with git's repository-selecting variables removed.

    ``GIT_CEILING_DIRECTORIES`` is then set POSITIVELY to ``sandbox`` rather
    than merely cleared: it stops git's upward search at the sandbox, so a
    fixture that expects "this directory is not a repository" cannot instead
    discover some real repository above ``$TMPDIR``. That is what the crash
    branch depends on, and leaving it to the layout of the temp directory would
    make the branch environment-dependent.
    """
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env["GIT_CEILING_DIRECTORIES"] = str(sandbox)
    env.update(extra)
    return env


def _seed_repo(work: Path) -> Path:
    """A throwaway git repo holding the attested roster at its real paths.

    The step asks ``git diff --name-only HEAD -- <roster>`` about the tree it
    runs in. Running that against the developer's own checkout would make the
    clean branch pass or fail on whatever happens to be edited locally — the
    state-dependent vacuity #4267 spent a PR removing. A seeded repo makes the
    diff an input instead of an accident.

    The ROSTER is still the real one: the step imports
    scripts.smc_r1_rollout_contract from the repository under test, so a target
    added to the contract shows up here without this fixture being touched.

    Every git call below passes ``env=_isolated_env(...)``. ``cwd=`` alone is
    NOT isolation — see the comment block above.
    """
    work.mkdir(parents=True, exist_ok=True)
    env = _isolated_env(work)
    repo = work / "repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, env=env)
    for rel in _attested_roster():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"// stub for {rel}\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    subprocess.run(
        ["git", *_COMMIT_IDENTITY, "commit", "-qm", "seed"],
        cwd=repo,
        check=True,
        env=env,
    )
    return repo


class _Notice(NamedTuple):
    rc: int
    log: str
    summary: str
    pr_body: str


def _run_notice(
    work: Path,
    *,
    cwd: Path,
    floor: int | None = None,
    sources: dict[str, dict[str, str]] | None = None,
    roster: list[str] | None = None,
) -> _Notice:
    """Execute the step's real `run:` block; return what it published.

    Two inputs are injected through a ``sitecustomize`` shim, which the
    interpreter imports at startup — so the step's own imports read the
    injected values. Nothing in the repository is mutated to induce any branch,
    and only these two names are touched: the derivation, the comparison and
    the reporting are all the shipped code.

    ``floor`` raises MIN_ATTESTED_SOURCES for the short-roster branch.

    ``sources`` is the registered evidence the hash comparison reads. It
    defaults to a map that attests the repository as it stands (see
    :func:`_evidence_matching_the_repository`), which is what makes the clean
    branch a controlled input rather than a property of today's main; pass a
    map with a wrong hash to drive the already-drifted branch.
    """
    work.mkdir(parents=True, exist_ok=True)
    summary = work / "step_summary.md"
    output_file = work / "github_output"
    summary.write_text("", encoding="utf-8")
    output_file.write_text("", encoding="utf-8")

    if sources is None:
        sources = _evidence_matching_the_repository()
    shim_lines = [
        "import scripts.check_tv_unattested_sources as _c\n",
        f"_c.attested_sources = lambda: {sources!r}\n",
    ]
    if floor is not None:
        shim_lines.append(
            "import scripts.smc_r1_rollout_contract as _m\n"
            f"_m.MIN_ATTESTED_SOURCES = {floor}\n"
        )
    if roster is not None:
        # Replaces the contract's TARGET LIST, which is what the step derives
        # its roster from. Used to drive the collapsed-roster branch without
        # editing the contract, the only way to reach the empty pathspec.
        shim_lines.append(
            "import scripts.smc_r1_rollout_contract as _r\n"
            f"_r.build_rollout_contract = lambda: {{'targets': [{{'path': p}} for p in {roster!r}]}}\n"
        )
    shim = work / "shim"
    shim.mkdir()
    (shim / "sitecustomize.py").write_text("".join(shim_lines), encoding="utf-8")
    path_entries = [str(shim), str(ROOT)]

    result = subprocess.run(
        # The shell GitHub gives this step: the workflow sets
        # `defaults.run.shell: bash`, which is `bash --noprofile --norc -eo
        # pipefail`. Under -e any uncaught non-zero exit fails the step, which
        # is precisely the property the rc assertions below measure.
        ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", _notice_run_block()],
        cwd=cwd,
        # The step under test SHELLS OUT TO GIT itself
        # (`git diff --name-only HEAD -- <roster>`), so it needs the same scrub
        # as the fixture's own git calls — arguably more, because this one is
        # the measurement. With an ambient $GIT_DIR the step would diff the
        # REAL repository instead of the seeded sandbox: the clean and drift
        # branches would report whatever the contributor happened to have
        # edited, and the crash branch would find a valid repository and never
        # crash. Every verdict these tests read would be about the wrong tree.
        env=_isolated_env(
            cwd.parent,
            SMC_PYTHON_BIN=sys.executable,
            GITHUB_STEP_SUMMARY=str(summary),
            GITHUB_OUTPUT=str(output_file),
            PYTHONPATH=os.pathsep.join(path_entries),
        ),
        capture_output=True,
        text=True,
    )

    raw = output_file.read_text(encoding="utf-8")
    # Name and delimiter DERIVED from the step, never re-typed here: the
    # delimiter is grown at run time until it cannot occur in the value, so a
    # harness carrying a fixed copy would silently stop finding the block on
    # exactly the inputs that made growing it necessary.
    match = re.search(r"^(\w+)<<(\S+)$", raw, re.M)
    assert match is not None, (
        "the step did not write a well-formed heredoc block to $GITHUB_OUTPUT, "
        f"so the PR body would carry nothing (or garbage): {raw!r}"
    )
    body = re.search(
        rf"^{match.group(1)}<<{re.escape(match.group(2))}\n(.*)\n{re.escape(match.group(2))}$",
        raw,
        re.S | re.M,
    )
    assert body is not None, (
        f"the {match.group(1)!r} block is never terminated by its own "
        f"delimiter {match.group(2)!r}: {raw!r}"
    )
    return _Notice(
        result.returncode,
        result.stdout + result.stderr,
        summary.read_text(encoding="utf-8"),
        body.group(1),
    )


# Language that would read as "the attestation is fine". Any branch that did
# NOT reach that conclusion must contain none of it: an unnoticed drift is the
# defect, and a false all-clear is an unnoticed drift with reassurance on top.
#
# This tuple is hand-typed BY NECESSITY — it states a prohibition on meaning,
# and no mechanical derivation from the implementation can express "wording a
# reader would take as reassurance". What it must never be is UNANCHORED:
# test_the_all_clear_vocabulary_is_anchored_to_the_clean_branch below asserts
# every phrase really is the clean branch's own language. Measured 2026-08-04
# on the landed PR, without that anchor: rewording only the clean branch left
# all 43 tests green, and the tuple then described text that existed nowhere —
# a prohibition on nothing, which is the vacuity this file is about.
#
# Known limit, stated rather than implied: the anchor keeps these phrases
# honest, it cannot catch a `cannot_run()` that invents NEW reassuring wording
# ("the evidence still covers them"). That direction needs a reader, and
# test_the_executed_branches_are_distinguishable_from_each_other is the only
# mechanical check standing near it.
_ALL_CLEAR = ("unaffected", "still describes", "none changed")


def _unwrapped(text: str) -> str:
    """``text`` with every run of whitespace collapsed to one space.

    Matched against the UNWRAPPED summary because the step hard-wraps its
    prose, and a phrase that straddles a line break matches nothing. That is
    not hypothetical: #4393 reflowed the all-clear to "so it still\ndescribes
    them", which silently killed "still describes" in all three leak checks
    below — a third of this vocabulary was dead on `main` and no test said so.
    Rewrapping is an editing accident, not a decision to allow reassuring
    language, so it must not be able to disarm the checks.
    """
    return " ".join(text.split())


def test_the_notice_step_reports_a_clean_run_as_clean(tmp_path: Path) -> None:
    """Executed baseline: nothing attested changed AND the hashes still match.

    Both halves are supplied: the seeded repo makes ``git diff HEAD`` empty,
    and the injected evidence attests the repository's real hashes. The
    all-clear is only honest when both hold, which is why the fixture now
    controls both rather than the diff alone.
    """
    work = tmp_path
    notice = _run_notice(work, cwd=_seed_repo(work))

    assert notice.rc == 0, notice.log
    assert "## R1 attestation unaffected" in notice.summary
    for path in _attested_roster():
        assert path in notice.summary, (
            f"the all-clear does not name {path}, so it is not a statement "
            "about the roster it claims to have checked"
        )
    # It must name the artifact it claims still describes them — an all-clear
    # that never mentions the evidence is not a statement about the evidence.
    assert EXECUTION_EVIDENCE.relative_to(ROOT).as_posix() in notice.summary
    assert "::notice::" in notice.log
    # Nothing to carry into the PR body when there is nothing to report.
    assert notice.pr_body.strip() == ""


def test_a_clean_diff_is_not_an_attestation_the_step_never_measured(
    tmp_path: Path,
) -> None:
    """The all-clear must be a MEASUREMENT, not the absence of one.

    The step used to reach its all-clear from a single observation — ``git diff
    --name-only HEAD -- <roster>`` came back empty — and then publish
    "``<evidence>`` still describes them". Those are different claims. "Nothing
    changed in this run" says nothing whatsoever about an attestation that was
    already dead when the run started.

    Reachable, narrowly but really: it needs (a) an evidence artifact already
    drifted on main and (b) a refresh whose repin is a no-op for every attested
    target. (b) is not hypothetical — the bump ``sed``s a version pin, and
    ``SMC_Exit_Signal.pine`` carries no ``libraryPin`` at all, so a republish at
    an unchanged ``library.publishedVersion`` touches neither target.

    Driven here by injecting one wrong hash into the registered evidence, over
    a seeded repo whose diff is empty: exactly (a) plus (b). The real
    comparison runs against the real contract hashes.
    """
    from scripts.smc_r1_rollout_contract import build_rollout_contract

    work = tmp_path
    target = sorted(build_rollout_contract()["targets"], key=lambda t: str(t["path"]))[0]
    sources = _evidence_matching_the_repository()
    sources[str(target["scriptName"])] = {"repositorySha256": "0" * 64}

    notice = _run_notice(work, cwd=_seed_repo(work), sources=sources)

    assert notice.rc == 0, notice.log
    leaked = [phrase for phrase in _ALL_CLEAR if phrase in _unwrapped(notice.summary)]
    assert not leaked, (
        f"the step published all-clear language {leaked} while the registered "
        f"evidence does not attest {target['path']}. `git diff HEAD` came back "
        "empty, which is a different measurement from the one the sentence "
        f"makes:\n{notice.summary}"
    )
    assert "## R1 attestation was already invalid before this refresh" in notice.summary
    assert str(target["path"]) in notice.summary
    assert "::warning::" in notice.log
    # Same reach as a drift this run caused: nobody opens the run log.
    assert notice.pr_body.strip(), "the verdict never reached the PR body"
    assert str(target["path"]) in notice.pr_body
    assert "replaces a measurement with a fabrication" in notice.pr_body
def test_the_all_clear_vocabulary_is_anchored_to_the_clean_branch(tmp_path: Path) -> None:
    """``_ALL_CLEAR`` must be the clean branch's real language, not a memory of it.

    The leak checks in the crash and floor branches are only as good as this
    tuple. Re-typed and never compared against anything, it decays into a
    prohibition on text no branch produces: the step gets reworded, the tuple
    keeps matching nothing, and both leak assertions pass vacuously forever.

    So: execute the clean branch and require every phrase to be in what it
    actually published. Reword the step and this fails, in the same PR, naming
    the phrase that went stale.
    """
    clean = _run_notice(tmp_path, cwd=_seed_repo(tmp_path)).summary

    stale = [phrase for phrase in _ALL_CLEAR if phrase not in _unwrapped(clean)]
    assert not stale, (
        f"{stale} no longer appear in the clean branch's own summary, so the "
        "leak checks in the crash and floor branches are searching for text "
        "that cannot occur. Update _ALL_CLEAR to the step's current all-clear "
        "wording — the tuple exists to describe THAT text.\n"
        f"--- clean summary ---\n{clean}"
    )


def test_the_notice_step_announces_a_drift_it_caused(tmp_path: Path) -> None:
    """#4371's shape, executed: an attested source changed in this run.

    This is the branch the whole step exists for. #4371 merged green because
    nothing said this out loud, and a source-text assertion cannot tell a step
    that says it from a step that would crash, print nothing, or write to the
    wrong file.

    Run once PER ATTESTED SOURCE, never for ``roster[0]`` alone. Measured
    2026-08-04 on the landed PR: with only the first entry exercised, narrowing
    the step's own ``git diff ... -- <roster>`` to ``<roster>[:1]`` — blind to
    ``SMC_Exit_Signal.pine`` — left all 43 tests green. A guard that checks one
    of two sources cannot see the source it does not check.
    """
    for drifted in _attested_roster():
        _assert_drift_is_announced(tmp_path / f"drift-{Path(drifted).stem}", drifted)


def _assert_drift_is_announced(work: Path, drifted: str) -> None:
    """One attested source, rewritten in the sandbox: the step must name it."""
    repo = _seed_repo(work)
    (repo / drifted).write_text("// rewritten by this refresh\n", encoding="utf-8")

    notice = _run_notice(work, cwd=repo)

    assert notice.rc == 0, notice.log
    assert "## R1 attestation invalidated by this refresh" in notice.summary
    assert drifted in notice.summary
    assert "::warning::" in notice.log
    # The remedy actually renders — the import is not enough, the format() has
    # to succeed and the {evidence} placeholder has to be substituted.
    assert "replaces a measurement with a fabrication" in notice.summary
    assert EXECUTION_EVIDENCE.relative_to(ROOT).as_posix() in notice.summary
    assert "{evidence}" not in notice.summary
    # …and all of it reaches the PR body, not only the job summary. That is the
    # half #4371 proved matters: nobody opens the run.
    assert notice.pr_body.strip(), "the drift verdict never reached the PR body"
    assert drifted in notice.pr_body
    assert "replaces a measurement with a fabrication" in notice.pr_body


def test_a_crash_in_the_notice_step_is_reported_and_still_exits_zero(tmp_path: Path) -> None:
    """The derivation raises: report UNKNOWN, never fail the step.

    Induced by running where ``git diff`` cannot work, so the real
    ``subprocess.run(..., check=True)`` inside the step's own try block raises —
    no repository file is mutated to produce it.

    rc==0 is the load-bearing assertion. In job ``refresh``,
    publish-to-TradingView is step 37, this notice is 45, and ``Commit and push
    changes`` is 46 with an implied success(). Under ``bash -e`` a non-zero exit
    here leaves the library PUBLISHED to TradingView with the repository pins
    never committed — the 2026-07-13 divergence class.
    """
    work = tmp_path
    not_a_repo = work / "loose"
    not_a_repo.mkdir()

    notice = _run_notice(work, cwd=not_a_repo)

    assert notice.rc == 0, (
        "the notice step went RED on a crash. That skips 'Commit and push "
        f"changes' and strands a published library on uncommitted pins:\n{notice.log}"
    )
    assert "## R1 attestation check could not run" in notice.summary
    assert "UNKNOWN, not as intact" in notice.summary
    assert "::error::" in notice.log
    leaked = [phrase for phrase in _ALL_CLEAR if phrase in _unwrapped(notice.summary)]
    assert not leaked, (
        f"a crashed check published all-clear language {leaked}. Silence and "
        "reassurance are the same failure here."
    )
    # The reviewer must see it without opening the run log.
    assert "could not run" in notice.pr_body
    # …but the TRACEBACK stays out of the PR body. It carries the runner's
    # absolute checkout path and whatever a frame interpolated, and the PR body
    # is public and unbounded in width, while the summary and the run log are
    # neither. The verdict travels; the internals do not.
    assert "Traceback (most recent call last)" in notice.summary, (
        "the job summary lost the traceback, which is where it belongs and the "
        "only place an operator can debug this from"
    )
    assert "Traceback (most recent call last)" not in notice.pr_body, (
        "the traceback reached the PUBLIC PR body:\n" + notice.pr_body
    )
    assert "/home/runner" not in notice.pr_body and str(ROOT) not in notice.pr_body, (
        "an absolute runner path reached the PR body:\n" + notice.pr_body
    )


def test_a_roster_below_the_floor_never_reads_as_an_all_clear(tmp_path: Path) -> None:
    """A vacuous roster is the one failure that would survive forever.

    "Checked 0 attested source(s) … still describes them" is indistinguishable
    from success, so it would print green every run for as long as the
    derivation stayed broken. It must render the same UNKNOWN report as a crash
    — and, exactly like a crash, without failing the step.
    """
    work = tmp_path
    notice = _run_notice(work, cwd=_seed_repo(work), floor=99)

    assert notice.rc == 0, notice.log
    assert "## R1 attestation check could not run" in notice.summary
    assert "vacuous R1 all-clear" in notice.log
    assert "expected at least 99" in notice.summary
    leaked = [phrase for phrase in _ALL_CLEAR if phrase in _unwrapped(notice.summary)]
    assert not leaked, (
        f"a roster below the floor published all-clear language {leaked}; that "
        "is the report that would survive indefinitely because it looks like "
        "success"
    )
    assert "could not run" in notice.pr_body


def test_a_collapsed_roster_never_asks_git_about_the_whole_repository(
    tmp_path: Path,
) -> None:
    """An empty pathspec is "every file", not "no files".

    ``git diff --name-only HEAD -- *attested`` with an empty ``attested``
    degenerates to ``git diff --name-only HEAD --``, and git then answers about
    the entire working tree. The step would publish every modified file in the
    repository as an R1-attested source this refresh rewrote — a drift report
    made of noise, on the one run where the derivation had already failed.

    Reachable only with the floor at 0, which is why it was left alone once:
    the floor branch wins first. That is a guarantee held by a constant someone
    can lower, not by this step, so the guard is on ``attested`` itself.

    Driven with a genuinely dirty tree, or the assertion would hold for the
    wrong reason.
    """
    work = tmp_path
    repo = _seed_repo(work)
    # TRACKED files, modified. `git diff HEAD` never reports untracked ones, so
    # seeding new files here would make this test pass without the empty
    # pathspec ever being able to fail it — measured: with untracked files the
    # guard mutation below stayed green, which is the vacuity this file is
    # about, committed into its own regression test.
    dirtied = _attested_roster()
    assert dirtied, "the fixture needs at least one tracked file to dirty"
    for rel in dirtied:
        (repo / rel).write_text("// rewritten\n", encoding="utf-8")

    notice = _run_notice(work, cwd=repo, roster=[], floor=0)

    assert notice.rc == 0, notice.log
    for path in dirtied:
        assert path not in notice.summary, (
            f"the step named {path!r} as an R1-attested source while its "
            "roster was EMPTY. It asked git about the whole repository instead "
            f"of about nothing:\n{notice.summary}"
        )
        assert path not in notice.pr_body, (
            f"{path!r} reached the PR body as an attested source"
        )


def test_the_executed_branches_are_distinguishable_from_each_other(tmp_path: Path) -> None:
    """Witness: the five runs above are not all producing the same text.

    Without this, a step that wrote one constant string would satisfy every
    ``in`` assertion that happened to be a substring of it, and the suite would
    be measuring a fixed output. Five executions, five distinct summaries.
    """
    from scripts.smc_r1_rollout_contract import build_rollout_contract

    work = tmp_path
    clean_repo = _seed_repo(work / "a")
    drift_repo = _seed_repo(work / "b")
    (drift_repo / _attested_roster()[0]).write_text("// rewritten\n", encoding="utf-8")
    loose = work / "c"
    loose.mkdir(parents=True)
    dead = _evidence_matching_the_repository()
    dead[str(build_rollout_contract()["targets"][0]["scriptName"])] = {
        "repositorySha256": "0" * 64
    }

    summaries = [
        _run_notice(work / "ra", cwd=clean_repo).summary,
        _run_notice(work / "rb", cwd=drift_repo).summary,
        _run_notice(work / "rc", cwd=loose).summary,
        _run_notice(work / "rd", cwd=clean_repo, floor=99).summary,
        _run_notice(work / "re", cwd=clean_repo, sources=dead).summary,
    ]
    for summary in summaries:
        assert summary.strip(), "a branch published an EMPTY job summary"
    assert len({s.strip() for s in summaries}) == 5, (
        "two of the five branches published identical text, so at least one "
        "assertion above is satisfied by a constant rather than by a verdict:\n"
        + "\n---\n".join(summaries)
    )


def _git_out(args: list[str], *, cwd: Path, sandbox: Path) -> str:
    """Read-only git, isolated the same way everything else here is."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=_isolated_env(sandbox),
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_the_git_fixtures_cannot_be_hijacked_by_an_ambient_git_dir(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """Isolation is PROVEN here, not asserted in a comment.

    This is the regression test for the incident described above
    ``_GIT_ENV_OVERRIDES``: fixtures that passed ``cwd=`` and nothing else
    wrote a commit into the real repository when run from the pre-push hook,
    because git exports ``GIT_DIR``/``GIT_INDEX_FILE`` into hook environments
    and those OUTRANK ``cwd``.

    So: poison the environment exactly the way a hook does, run the fixtures,
    and check both directions — the work landed in the sandbox AND the decoy
    was never touched. Checking only the first would pass even if the fixture
    had written to both.

    The decoy is a POPULATED repository with a commit of its own, and the
    poison sets ``GIT_DIR``/``GIT_INDEX_FILE`` but deliberately NOT
    ``GIT_WORK_TREE`` — which is the shape a pre-push hook actually exports.
    That combination is what made the incident destructive rather than merely
    noisy: with the git dir pointing at the real repository and the work tree
    defaulting to ``cwd``, ``git add -A`` staged every real tracked file as
    DELETED and the commit landed on the contributor's branch. An empty decoy
    would only reproduce a failed commit, which is the symptom, not the damage.
    """
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    # Built BEFORE the environment is poisoned, and itself isolated — this
    # helper has to work under the hook too, which is the whole point.
    decoy_env = _isolated_env(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=decoy, check=True, env=decoy_env)
    (decoy / "tracked.txt").write_text("real content\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=decoy, check=True, env=decoy_env)
    subprocess.run(
        ["git", *_COMMIT_IDENTITY, "commit", "-qm", "decoy base"],
        cwd=decoy,
        check=True,
        env=decoy_env,
    )
    before = _git_out(["rev-parse", "HEAD"], cwd=decoy, sandbox=tmp_path)
    assert before, "the decoy has no HEAD, so it cannot witness an unwanted write"

    for name, value in (
        ("GIT_DIR", str(decoy / ".git")),
        ("GIT_INDEX_FILE", str(decoy / ".git" / "index")),
    ):
        monkeypatch.setenv(name, value)  # type: ignore[attr-defined]

    work = tmp_path / "work"
    repo = _seed_repo(work)

    # 1. The decoy was NOT written to — the direction that actually catches the
    #    bug. HEAD must be the commit it had before, and its tree must be
    #    clean: the incident's signature was a new commit whose parent was the
    #    real HEAD, with every real tracked file staged as deleted.
    assert _git_out(["rev-parse", "HEAD"], cwd=decoy, sandbox=tmp_path) == before, (
        "the fixture committed into the repository named by $GIT_DIR instead "
        "of its sandbox. Under the pre-push hook that IS the contributor's "
        "checkout: this is the 2026-08-04 incident reproducing."
    )
    assert _git_out(["rev-list", "--count", "--all"], cwd=decoy, sandbox=tmp_path) == "1", (
        "the decoy gained commits it did not have before"
    )
    assert _git_out(["status", "--porcelain"], cwd=decoy, sandbox=tmp_path) == "", (
        "the fixture dirtied the working tree / index of the repository named "
        "by $GIT_DIR — the collateral that broke an unrelated ledger guard in "
        "the same run"
    )

    # 2. The seed landed in the sandbox instead. Checked second, because a
    #    fixture that wrote to BOTH would satisfy this one — it is the decoy
    #    above that carries the safety claim.
    assert (repo / ".git").is_dir(), "the fixture did not create its own repository"
    assert _git_out(["log", "--oneline", "-1"], cwd=repo, sandbox=tmp_path).endswith("seed"), (
        "the sandbox repo has no seed commit, so the commit went somewhere else"
    )

    # 3. …and the executed step, which runs `git diff` itself, is isolated too.
    #    Pointed at the decoy it would diff a tree that has none of the
    #    attested sources, and report drift or a crash instead of the truth
    #    about the sandbox.
    notice = _run_notice(work / "run", cwd=repo)
    assert notice.rc == 0, notice.log
    assert "## R1 attestation unaffected" in notice.summary, (
        "the executed step did not reach a clean verdict under a poisoned "
        f"$GIT_DIR, so it diffed the wrong repository:\n{notice.summary}"
    )
    assert _git_out(["rev-parse", "HEAD"], cwd=decoy, sandbox=tmp_path) == before
    assert _git_out(["status", "--porcelain"], cwd=decoy, sandbox=tmp_path) == ""

    # Finally the composition itself, as a supplement to the behaviour above —
    # deliberately LAST, so that removing the scrub fails this test on the
    # observable hijack (a commit in the decoy) rather than on an assertion
    # about a dictionary. The behaviour is the claim; this only names which
    # variable would have carried it.
    built = _isolated_env(tmp_path)
    leaked = [
        name
        for name in _GIT_ENV_OVERRIDES
        if name in built and name != "GIT_CEILING_DIRECTORIES"
    ]
    assert not leaked, (
        f"_isolated_env left {leaked} in place; those override cwd and would "
        "retarget the real repository"
    )


def test_an_evidence_artifact_missing_a_hash_never_produces_an_all_clear(
    tmp_path: Path,
) -> None:
    """The step must not attest over a hash the artifact never recorded.

    Found by review of #4393 on 2026-08-04 and reproduced here at the consumer.
    ``drifted_attested_targets`` used to skip a source whose evidence entry
    carried no ``repositorySha256``, so all four malformed shapes below reached
    this step's clean branch and published "every one still hashes to what
    ``<evidence>`` attests" -- an attestation over sources whose hashes had
    never been read. The repository's required guard,
    ``scripts/check_r1_attested_sources.py``, called the same input an offender,
    so two guards gave two answers to one question.

    Driven through the real ``run:`` block, over a seeded repository whose
    ``git diff`` is empty -- so the only thing that can produce a verdict here
    is the hash comparison itself.
    """
    attested = _evidence_matching_the_repository()
    victim = sorted(attested)[0]

    shapes = {
        "the key was deleted": {k: v for k, v in attested.items() if k != victim},
        "the entry is an empty object": {**attested, victim: {}},
        "the hash is explicitly null": {**attested, victim: {"repositorySha256": None}},
        "the entry itself is null": {**attested, victim: None},
    }

    for index, (description, sources) in enumerate(shapes.items()):
        work = tmp_path / f"shape{index}"
        work.mkdir()
        notice = _run_notice(work, cwd=_seed_repo(work), sources=sources)

        assert notice.rc == 0, f"{description}: {notice.log}"
        leaked = [phrase for phrase in _ALL_CLEAR if phrase in _unwrapped(notice.summary)]
        assert not leaked, (
            f"{description}: the step published all-clear language {leaked} while "
            f"the registered evidence records no hash for {victim!r}. Absence of a "
            f"measurement is not a measurement of agreement:\n{notice.summary}"
        )
        assert notice.pr_body.strip(), (
            f"{description}: the verdict never reached the PR body, which is the "
            "only surface anyone reads"
        )


# --- the publish gate, executed rather than described ------------------------
#
# `publish_gate` decides `publish_allowed`, and twelve later steps hang on it --
# including the one that publishes to the live TradingView account. Its contract
# above (test_publish_gate_combines_breaking_with_operator_override) pins the
# four env keys and the warning string; none of that constrains the logic.
#
# Measured 2026-08-04 with a value-preserving arm swap (the multiset of
# `name=value` tokens left unchanged, so every substring assertion is blind by
# construction): swapping the two `PUBLISH_ALLOWED=` arms left all 597 tests
# across the 32 files that name this workflow green -- while a breaking change
# would publish without an operator override, and a clean refresh would not
# publish at all.


PUBLISH_GATE_STEP = "Compute publish gate"


def _publish_gate(tmp_path, *, breaking, is_dispatch, is_main, allow_breaking):
    """Run the real step; return its outputs."""
    return run_step(
        "smc-library-refresh.yml",
        PUBLISH_GATE_STEP,
        tmp_path,
        env={
            "BREAKING": breaking,
            "IS_DISPATCH": is_dispatch,
            "IS_MAIN": is_main,
            "ALLOW_BREAKING": allow_breaking,
        },
    )


def test_publish_gate_harness_feeds_exactly_the_step_env(tmp_path) -> None:
    """The harness env must mirror the step's ``env:`` block, and nothing more.

    The step runs under ``-u``, but a future variable the workflow adds and this
    harness does not would still be the dangerous shape: the tests below would
    keep passing against a gate that no longer behaves as they describe. Pinning
    the key set makes that a named failure instead.
    """
    declared = set(step_by_name("smc-library-refresh.yml", PUBLISH_GATE_STEP)["env"])
    assert declared == {"BREAKING", "IS_DISPATCH", "IS_MAIN", "ALLOW_BREAKING"}


def test_a_clean_refresh_publishes(tmp_path) -> None:
    """No breaking change: publishing is the normal outcome, override irrelevant."""
    result = _publish_gate(
        tmp_path, breaking="false", is_dispatch="false", is_main="true", allow_breaking="false"
    )
    assert result.returncode == 0, result.stderr
    assert result.outputs["publish_allowed"] == "true"
    assert result.outputs["override_active"] == "false"


def test_a_breaking_change_does_not_publish_on_its_own(tmp_path) -> None:
    """The gate's reason for existing: breaking changes stop here."""
    result = _publish_gate(
        tmp_path, breaking="true", is_dispatch="false", is_main="true", allow_breaking="false"
    )
    assert result.outputs["publish_allowed"] == "false"
    assert result.outputs["override_active"] == "false"


def test_the_override_needs_all_three_conditions(tmp_path) -> None:
    """Defence in depth, checked exhaustively rather than by example.

    A breaking change may publish only on a manual dispatch, against main, with
    the operator input set. Any one of the three missing must block -- so all
    eight combinations are enumerated instead of trusting the happy path and one
    counter-example.
    """
    seen_allowed = 0
    for dispatch in ("true", "false"):
        for main in ("true", "false"):
            for allow in ("true", "false"):
                result = _publish_gate(
                    tmp_path,
                    breaking="true",
                    is_dispatch=dispatch,
                    is_main=main,
                    allow_breaking=allow,
                )
                expected = "true" if dispatch == main == allow == "true" else "false"
                seen_allowed += expected == "true"
                assert result.outputs["publish_allowed"] == expected, (
                    f"breaking change with dispatch={dispatch} main={main} "
                    f"allow_breaking={allow} must be publish_allowed={expected}"
                )
                assert result.outputs["override_active"] == expected
    # Without this the loop could assert eight identical "false"s and still pass
    # against a gate that never honours the override at all.
    assert seen_allowed == 1, "exactly one of the eight combinations may publish"


def test_the_override_announces_itself(tmp_path) -> None:
    """An override that publishes silently is the one nobody reviews."""
    overridden = _publish_gate(
        tmp_path, breaking="true", is_dispatch="true", is_main="true", allow_breaking="true"
    )
    assert "Operator override active" in overridden.stdout
    plain = _publish_gate(
        tmp_path, breaking="false", is_dispatch="true", is_main="true", allow_breaking="true"
    )
    assert "Operator override active" not in plain.stdout, (
        "a refresh with no breaking change must not claim an override was used"
    )
