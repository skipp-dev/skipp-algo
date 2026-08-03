"""Structural pin for ``.github/workflows/credential-health-check.yml``.

Same pattern as ``tests/test_f2_workflow_yaml_contract.py`` — assert the
load-bearing pieces are present so that an accidental refactor can't
silently break the contract.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "credential-health-check.yml"


@pytest.fixture(scope="module")
def workflow_text() -> str:
    assert WORKFLOW.exists(), f"missing workflow: {WORKFLOW}"
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow(workflow_text: str) -> dict:
    if yaml is None:
        pytest.skip("PyYAML not available")
    return yaml.safe_load(workflow_text)


def test_workflow_runs_daily_at_06_utc(workflow: dict) -> None:
    on = workflow.get(True) or workflow.get("on")  # PyYAML quirk: 'on' → True
    assert on is not None, "workflow has no triggers"
    schedule = on.get("schedule")
    assert schedule, "must have a schedule trigger"
    crons = [entry.get("cron") for entry in schedule]
    assert "0 6 * * *" in crons, f"expected daily 06:00 UTC cron, got {crons!r}"


def test_workflow_live_window_marker_is_first_line(workflow_text: str) -> None:
    first_line = workflow_text.splitlines()[0]
    assert first_line.startswith("# live-window: mutating-on-cron"), first_line


def test_workflow_supports_manual_dispatch(workflow: dict) -> None:
    on = workflow.get(True) or workflow.get("on")
    assert "workflow_dispatch" in on, "must allow manual operator runs"


def test_workflow_permissions_are_minimal(workflow: dict) -> None:
    perms = workflow.get("permissions") or {}
    assert perms.get("contents") == "read", "contents must be read-only"
    assert perms.get("issues") == "write", "needs issues:write to file cron-failure issue"
    # No more than the two declared — defense against scope creep.
    assert set(perms.keys()) <= {"contents", "issues"}, f"unexpected extra permissions: {perms}"
    job_perms = workflow["jobs"]["probe"].get("permissions") or {}
    assert job_perms.get("contents") == "write", (
        "probe job needs contents:write to publish bot/live-tv-credential-snapshot"
    )
    assert job_perms.get("issues") == "write", (
        "job-level permissions override workflow defaults, so issues:write must be repeated"
    )
    assert set(job_perms.keys()) <= {"contents", "issues"}, (
        f"unexpected probe job permissions: {job_perms}"
    )


def test_workflow_probe_step_invokes_the_script(workflow_text: str) -> None:
    assert "python scripts/credential_health_check.py" in workflow_text, (
        "workflow must call scripts/credential_health_check.py"
    )
    assert "--tv-max-age-hours 72" in workflow_text, (
        "TV TTL must stay in sync with smc-library-refresh.yml (72h)"
    )


def test_workflow_exposes_all_vendor_secrets(workflow_text: str) -> None:
    # The probe step must pass every vendor secret through env: so the
    # script can run all probes. Missing one would silently skip it.
    # NewsAPI.ai retired 2026-07-08 — its probe is skipped (--skip-newsapi),
    # so NEWSAPI_KEY is intentionally no longer passed through env.
    # Benzinga added 2026-07-08 (Core News lane + hourly live-news cron).
    for env_line in (
        "TV_STORAGE_STATE: ${{ secrets.TV_STORAGE_STATE }}",
        "GH_PAT: ${{ secrets.GH_PAT }}",
        "DATABENTO_API_KEY: ${{ secrets.DATABENTO_API_KEY }}",
        "FMP_API_KEY: ${{ secrets.FMP_API_KEY }}",
        "BENZINGA_API_KEY: ${{ secrets.BENZINGA_API_KEY }}",
    ):
        assert env_line in workflow_text, f"probe step missing env: {env_line}"


def test_workflow_does_not_silently_swallow_probe_failure(workflow_text: str) -> None:
    # Bundle A lesson: never lose a non-zero rc behind ``|| true`` / ``; true``.
    # We allow ``set +e`` because the workflow captures $? immediately after.
    assert "rc=$?" in workflow_text, "probe step must capture and surface $?"
    forbidden = [
        re.compile(r"python\s+scripts/credential_health_check\.py[^\n]*\|\|\s*true"),
        re.compile(r"python\s+scripts/credential_health_check\.py[^\n]*;\s*true"),
    ]
    for pat in forbidden:
        assert not pat.search(workflow_text), f"probe step must not swallow failures: {pat.pattern}"


def test_workflow_surfaces_annotations(workflow_text: str) -> None:
    # Must emit GitHub annotations so failures appear in run summary.
    assert "::warning title=credential-health::" in workflow_text
    assert "::error title=credential-health::" in workflow_text


def test_workflow_opens_cron_failure_issue_with_dedup(workflow_text: str) -> None:
    assert "gh issue list" in workflow_text, "must search for existing open issue"
    assert "gh issue comment" in workflow_text, "must comment on the existing issue"
    assert "gh issue create" in workflow_text, "must open a new issue when none exists"
    assert "--label cron-failure" in workflow_text, "must use the cron-failure label for triage"


def test_workflow_fails_job_on_overall_error(workflow_text: str) -> None:
    # The final hard-fail must check overall == 'error'. Pure 'warn' should
    # NOT fail the build — only annotate + file an issue.
    assert "steps.probe.outputs.overall == 'error'" in workflow_text, (
        "the fail-the-job gate must key off overall == 'error'"
    )


def test_workflow_uploads_report_artifact(workflow_text: str) -> None:
    assert "actions/upload-artifact" in workflow_text
    assert "credential_health.json" in workflow_text


def test_workflow_preflights_snapshot_push_permission(workflow_text: str) -> None:
    """Snapshot publish should skip cleanly when the job token cannot push the bot branch."""
    # The preflight must use a real git push --dry-run against the target
    # ref, not ``gh api .permissions.push`` which only reflects repository
    # membership/role, not branch ruleset or PAT scope reality. It also needs
    # the same force-with-lease shape as the real rolling-branch publish; a
    # plain dry-run push can falsely reject valid non-fast-forward snapshot
    # updates.
    # Explicit --force-with-lease=<ref>:<expected> — the no-expected form is
    # rejected client-side ("stale info") in a fresh CI checkout.
    dry_run = (
        "git push --dry-run --force-with-lease=refs/heads/bot/live-tv-credential-snapshot:${_lease_expected} "
        '"${_remote_url}" "HEAD:refs/heads/bot/live-tv-credential-snapshot"'
    )
    lease_fetch = (
        'git fetch "${_remote_url}" '
        '"+refs/heads/bot/live-tv-credential-snapshot:refs/remotes/origin/bot/live-tv-credential-snapshot"'
    )
    skip_warning = "dry-run push to bot/live-tv-credential-snapshot failed; skipping publish"
    assert "GH_TOKEN: ${{ github.token }}" in workflow_text
    assert dry_run in workflow_text
    assert lease_fetch in workflow_text
    assert skip_warning in workflow_text
    # No commit or push may happen before the dry-run proves the token works.
    assert workflow_text.index(lease_fetch) < workflow_text.index(dry_run)
    assert workflow_text.index(dry_run) < workflow_text.index('git add -f "${stable_dir}"')
    assert workflow_text.index(dry_run) < workflow_text.index('git commit -m "[skip ci]')
    assert workflow_text.index(dry_run) < workflow_text.index("git push --force-with-lease")
    # If the dry-run fails we must skip before staging/committing.
    assert workflow_text.index(skip_warning) < workflow_text.index('git add -f "${stable_dir}"')
    assert workflow_text.index(skip_warning) < workflow_text.index('git commit -m "[skip ci]')


def test_workflow_checks_snapshot_branch_ruleset_assumption(workflow_text: str) -> None:
    """The bot snapshot branch must remain outside main-governance push rules."""
    rules_api = (
        'gh api \\\n'
        '            -H "Accept: application/vnd.github+json" \\\n'
        '            -H "X-GitHub-Api-Version: 2022-11-28" \\\n'
        '            "repos/${GITHUB_REPOSITORY}/rules/branches/bot%2Flive-tv-credential-snapshot"'
    )
    dry_run = (
        "git push --dry-run --force-with-lease=refs/heads/bot/live-tv-credential-snapshot:${_lease_expected} "
        '"${_remote_url}" "HEAD:refs/heads/bot/live-tv-credential-snapshot"'
    )
    assert "Ruleset assumption guard" in workflow_text
    assert rules_api in workflow_text
    assert "BRANCH_RULES_JSON" in workflow_text
    assert "requires only repository Metadata read for fine-grained tokens" in workflow_text
    assert "Keep this guard on github.token" in workflow_text
    assert "instead of requiring GH_PAT for a read-only inspection" in workflow_text
    assert "except json.JSONDecodeError" in workflow_text
    assert "if not isinstance(rules, list):" in workflow_text
    assert 'blocking = {"non_fast_forward", "pull_request", "required_status_checks"}' in workflow_text
    assert "if isinstance(rule, dict)" in workflow_text
    assert "A detected blocking rule is intentional ruleset drift" in workflow_text
    assert "fail this job loudly" in workflow_text
    assert "no longer excluded " in workflow_text
    assert "from blocking branch rules" in workflow_text
    assert "continuing to dry-run push preflight" in workflow_text
    assert workflow_text.index(rules_api) < workflow_text.index(dry_run)


def test_workflow_uses_gh_pat_with_token_fallback(workflow_text: str) -> None:
    # Mirror the existing repo-wide pattern so the issue-opening step
    # works even when GH_PAT is unset (e.g. forks, first install).
    assert "secrets.GH_PAT != '' && secrets.GH_PAT || github.token" in workflow_text


def test_workflow_has_step_timeout(workflow: dict) -> None:
    job = workflow["jobs"]["probe"]
    assert job.get("timeout-minutes") is not None, "job must have a timeout-minutes guard"
    assert job["timeout-minutes"] <= 10, "credential probes should finish in well under 10 min"


def _probe_step(workflow: dict) -> dict:
    steps = workflow["jobs"]["probe"]["steps"]
    return next(s for s in steps if s.get("id") == "probe")


def test_probe_step_passes_every_declared_composio_account(workflow: dict) -> None:
    """Without these env entries the Composio probes see nothing and pass.

    2026-08-03: composio-publish failed every run from 2026-07-20 because
    connected account ca_t1SW1B3NFDA3 was EXPIRED, and this workflow stayed
    green for two weeks because it probed no Composio surface. Dropping an
    env line here would silently restore that blind spot, so pin all of them
    against the repo's own auth policy rather than a hand-written list.
    """
    import json as _json

    policy = _json.loads(
        (Path(__file__).resolve().parents[1] / "configs" / "composio_auth_policy.json").read_text(
            encoding="utf-8"
        )
    )
    env = _probe_step(workflow).get("env") or {}
    assert env.get("COMPOSIO_PROD_API_KEY"), "probe step must receive the Composio project key"
    assert env.get("COMPOSIO_ENVIRONMENT") == "prod"
    for key in policy["auth_configs"]:
        toolkit, _, access = str(key).rpartition("_")
        name = f"COMPOSIO_{toolkit.upper()}_{access.upper()}_ACCOUNT_ID"
        assert name in env, f"{name} is declared in the auth policy but not passed to the probe"
        assert name in str(env[name]), f"{name} must be wired to the repo variable of the same name"


def test_composio_probe_is_not_skipped(workflow_text: str) -> None:
    # --skip-newsapi is deliberate (NewsAPI retired 2026-07-08); a
    # --skip-composio would re-open the blind spot this coverage closes.
    assert "--skip-newsapi" in workflow_text
    assert "--skip-composio" not in workflow_text
