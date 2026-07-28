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
def workflow(workflow_text: str) -> dict[object, object]:
    parsed = yaml.safe_load(workflow_text)
    assert isinstance(parsed, dict), f"expected workflow YAML mapping, got {type(parsed).__name__}"
    return parsed


def workflow_text_after(workflow_text: str, marker: str) -> str:
    assert marker in workflow_text, f"expected workflow marker {marker!r}"
    return workflow_text.split(marker, 1)[1]


def test_workflow_name_referenced(workflow_text: str) -> None:
    assert "name: tradingview-storage-refresh" in workflow_text


def test_schedule_pinned_48h(workflow: dict[object, object]) -> None:
    on = workflow.get("on") if "on" in workflow else workflow.get(True)
    assert isinstance(on, dict), f"expected workflow 'on' mapping, got {type(on).__name__}"
    schedule = on.get("schedule")
    assert isinstance(schedule, list), f"expected schedule list, got {type(schedule).__name__}"
    crons = []
    for entry in schedule:
        assert isinstance(entry, dict), f"expected schedule entry mapping, got {entry!r}"
        cron = entry.get("cron")
        assert isinstance(cron, str), f"expected schedule cron string, got {cron!r}"
        crons.append(cron)
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


def test_manual_dispatch_exposes_safe_fresh_login_controls(workflow: dict) -> None:
    on = workflow.get("on") if "on" in workflow else workflow.get(True)
    assert isinstance(on, dict)
    dispatch = on["workflow_dispatch"]
    inputs = dispatch["inputs"]
    assert inputs["force_fresh_login"]["type"] == "boolean"
    assert inputs["force_fresh_login"]["default"] is False
    assert inputs["dry_run"]["type"] == "boolean"
    assert inputs["dry_run"]["default"] is True
    assert inputs["confirm_session_disconnect"]["default"] is False


def test_fresh_login_ignores_bootstrap_and_requires_explicit_ack(
    workflow_text: str,
) -> None:
    assert "capture_args+=(--force-fresh-login)" in workflow_text
    assert "if: env.TV_FORCE_FRESH_LOGIN != 'true'" in workflow_text
    assert "force_fresh_login requires confirm_session_disconnect=true" in workflow_text
    assert "for variable_name in TV_USERNAME TV_PASSWORD TV_TOTP_SECRET" in workflow_text
    assert "${variable_name} is required for force_fresh_login" in workflow_text


def test_dry_run_validates_without_writing_or_filing_an_issue(
    workflow_text: str,
) -> None:
    write_block = workflow_text_after(workflow_text, "Write refreshed secret back to GitHub")
    assert "if: env.TV_REFRESH_DRY_RUN != 'true'" in write_block
    failure_block = workflow_text_after(workflow_text, "File failure issue")
    assert "if: failure() && env.TV_REFRESH_DRY_RUN != 'true'" in failure_block
    assert workflow_text.index("Validate captured storage state") < workflow_text.index(
        "Write refreshed secret back to GitHub"
    )
    assert r"existing \`TV_STORAGE_STATE\` is unchanged" in workflow_text


def test_success_summary_reports_observed_auth_path(workflow_text: str) -> None:
    report_block = workflow_text_after(workflow_text, "Report success")
    assert ".meta.authMode" in report_block
    assert ".meta.totpEntered" in report_block
    assert ".meta.totpSubmitted" in report_block
    assert "captured headlessly with TOTP" not in report_block


def test_capture_script_supports_headless_bootstrap_without_login_secrets() -> None:
    text = CAPTURE_SCRIPT.read_text(encoding="utf-8")
    assert "inputStorageState" in text
    assert "TV_STORAGE_STATE_INPUT" in text
    assert "storageState: existingStorageStatePath" in text
    assert "Headless TradingView storage-state capture requires TV_STORAGE_STATE_INPUT" in text
    assert "cli.persistentProfileDir || existingStorageStatePath ? cli.chartUrl : cli.loginUrl" in text


def test_capture_script_has_owner_lock_and_private_atomic_write() -> None:
    text = CAPTURE_SCRIPT.read_text(encoding="utf-8")
    assert "acquireExclusiveFileLock(cli.sessionLockFile, cli.sessionOwner)" in text
    assert "writePrivateJsonAtomic(cli.out, storageStateToWrite)" in text
    assert "authMode: authenticationMode" in text
    assert "totpEntered: twoFactorState.totpEntered" in text
    assert "totpSubmitted: twoFactorState.totpSubmitted" in text


def test_secret_write_uses_dedicated_token(workflow_text: str) -> None:
    write_block = workflow_text_after(workflow_text, "Write refreshed secret back to GitHub")
    assert "GH_TOKEN: ${{ secrets.TV_STORAGE_STATE_WRITE_TOKEN }}" in write_block
    assert "GH_TOKEN: ${{ secrets.GH_PAT }}" not in write_block
    assert "gh secret set TV_STORAGE_STATE" in write_block
    assert 'printf \'%s\' "$PAYLOAD" | gh secret set TV_STORAGE_STATE' in write_block
    assert "--body -" not in write_block


def test_secret_write_token_preflight_runs_before_capture(workflow_text: str) -> None:
    assert "Preflight GitHub secret write token" in workflow_text
    assert "TV_STORAGE_STATE_WRITE_TOKEN is not configured" in workflow_text
    assert 'gh api "repos/${GITHUB_REPOSITORY}/actions/secrets/public-key"' in workflow_text
    assert workflow_text.index("Preflight GitHub secret write token") < workflow_text.index(
        "Capture TradingView storage state"
    )
    assert workflow_text.index("Preflight GitHub secret write token") < workflow_text.index(
        "Write refreshed secret back to GitHub"
    )


def test_capture_and_validate_steps_are_fail_loud(workflow_text: str) -> None:
    forbidden = [
        re.compile(r"set\s+\+e"),
        re.compile(r"\|\|\s*true"),
        re.compile(r";\s*true"),
    ]
    critical_tail = workflow_text_after(workflow_text, "Capture TradingView storage state")
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
    write_block = workflow_text_after(workflow_text, "Write refreshed secret back to GitHub")
    assert "force-with-lease" not in write_block


def test_failure_issue_gives_a_working_secret_write_command(workflow_text: str) -> None:
    """The pasted recovery command must target THIS repo and carry a payload.

    #3640 hardcoded ``skippALGO/skipp-algo`` -- the org's pre-rename name. It
    still resolves, but only because GitHub redirects renamed orgs; that
    redirect lapses the moment anyone registers the old name, and this command
    uploads a live TradingView session cookie. Pin it to the real repo.

    Without a redirect ``gh secret set`` reads the value from stdin, so the
    flow never connects the JSON that ``npm run tv:storage-state`` just wrote
    to the command that uploads it.
    """
    issue_block = workflow_text_after(workflow_text, "File failure issue")
    assert "skippALGO" not in issue_block
    assert "gh secret set TV_STORAGE_STATE --repo ${{ github.repository }}" in issue_block
    assert "< automation/tradingview/auth/storage-state.json" in issue_block


def test_failure_issue_does_not_claim_the_current_state_is_still_valid(
    workflow_text: str,
) -> None:
    """A job that never established a session cannot vouch for the secret.

    #3640: "still valid until its 72 h TTL expires" told the operator to stand
    down while TradingView was already rejecting the stored bootstrap session.
    """
    issue_block = workflow_text_after(workflow_text, "File failure issue")
    assert "is still valid until" not in issue_block
    assert "UNKNOWN" in issue_block
    assert "tv_storage_state_age" in issue_block


def test_failure_issue_warns_against_re_uploading_a_stale_capture(
    workflow_text: str,
) -> None:
    """The #3640 root cause was an OLD local capture pushed over a live secret."""
    issue_block = workflow_text_after(workflow_text, "File failure issue")
    assert "re-upload an older local" in issue_block
    assert "docs/tradingview-storage-state-capture-runbook.md" in issue_block


def test_failure_issue_body_renders_as_markdown(workflow_text: str) -> None:
    """Body must go via --body-file, never a ``--body "$(cat <<'EOF' ...)"``.

    Inside that command substitution bash still parses backticks, so every
    code span had to be written escaped -- and a quoted heredoc emits the
    backslash verbatim. The shipped #3640 issue therefore showed a literal
    escaped fence instead of a ```bash block, and no inline span rendered.
    """
    issue_block = workflow_text_after(workflow_text, "File failure issue")
    assert "--body-file" in issue_block
    assert '--body "$(cat' not in issue_block
    assert "\\`" not in issue_block, "escaped backticks ship verbatim into the issue body"
