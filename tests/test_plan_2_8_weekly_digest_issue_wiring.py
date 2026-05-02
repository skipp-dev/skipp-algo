"""Pin-tests for the drift-alert issue creation wiring in the weekly digest."""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"
)


def _wf() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return {"on": data.get("on", data.get(True)), **{
        k: v for k, v in data.items() if k not in ("on", True)
    }}


def test_permissions_include_issues_write() -> None:
    perms = _wf()["permissions"]
    assert perms["issues"] == "write"


def test_digest_step_also_renders_issue_body_and_alerts_file() -> None:
    steps = _wf()["jobs"]["weekly-digest"]["steps"]
    digest = next(s for s in steps if s.get("id") == "digest")
    run = digest["run"]
    assert "--format             issue" in run
    assert "--output             artifacts/plan_2_8_digest/issue_body.md" in run
    assert "--alerts-file        artifacts/plan_2_8_digest/alerts.json" in run
    # Also emits a JSON digest for the snooze step.
    assert "digest.json" in run


def test_issue_creation_step_present_and_conditional() -> None:
    steps = _wf()["jobs"]["weekly-digest"]["steps"]
    issue = next(s for s in steps if s.get("name") == "Open drift-alert issue")
    assert issue["if"] == "steps.resolve_alerts.outputs.has_alerts == 'True'"
    run = issue["run"]
    assert "gh issue create" in run
    assert "--body-file artifacts/plan_2_8_digest/issue_body.md" in run
    # Bug-Hunt 2026-05-01 F-04: only the existing 'cron-failure' label is
    # used; previous labels 'plan-2.8' and 'drift-alert' do not exist in the
    # repo and silently broke `gh issue create`.
    assert "--label cron-failure" in run


def test_issue_step_dedups_via_existing_open_issue() -> None:
    steps = _wf()["jobs"]["weekly-digest"]["steps"]
    issue = next(s for s in steps if s.get("name") == "Open drift-alert issue")
    run = issue["run"]
    assert "gh issue list" in run
    # Bug-Hunt 2026-05-01 F-04: dedup query uses the same 'cron-failure'
    # label as the create call.
    assert "--label cron-failure" in run
    assert "--state open" in run
    assert "gh issue comment" in run


def test_issue_step_threads_run_url_into_body() -> None:
    steps = _wf()["jobs"]["weekly-digest"]["steps"]
    issue = next(s for s in steps if s.get("name") == "Open drift-alert issue")
    assert "RUN_URL" in issue["env"]
    assert "github.run_id" in issue["env"]["RUN_URL"]
    run = issue["run"]
    assert "--run-url" in run
    assert "${RUN_URL}" in run


def test_auto_close_step_present_and_conditional() -> None:
    steps = _wf()["jobs"]["weekly-digest"]["steps"]
    close = next(s for s in steps
                 if s.get("name") == "Close drift-alert issues when alerts cleared")
    assert close["if"] == "steps.resolve_alerts.outputs.has_alerts == 'False'"
    run = close["run"]
    assert "gh issue list" in run
    assert "--state open" in run
    assert "gh issue close" in run
    assert "--reason completed" in run
    assert "RUN_URL" in close["env"]


def test_history_diff_step_present_and_fail_soft() -> None:
    steps = _wf()["jobs"]["weekly-digest"]["steps"]
    diff = next(s for s in steps
                if s.get("name") == "Plan 2.8 history snapshot diff (last two)")
    assert diff["if"].strip() == "always()"
    run = diff["run"]
    assert "scripts/plan_2_8_history_diff.py" in run
    assert "set +e" in run
    assert run.rstrip().endswith("true")
    assert "GITHUB_STEP_SUMMARY" in run


def test_top_movers_step_present_and_fail_soft() -> None:
    steps = _wf()["jobs"]["weekly-digest"]["steps"]
    movers = next(s for s in steps
                  if s.get("name") == "Plan 2.8 top movers (30-day window)")
    assert movers["if"].strip() == "always()"
    run = movers["run"]
    assert "scripts/plan_2_8_top_movers.py" in run
    assert "--lookback-days 30" in run
    assert "--top-n         5" in run
    assert "set +e" in run
    assert run.rstrip().endswith("true")
    assert "GITHUB_STEP_SUMMARY" in run


def test_snooze_step_present_and_always_runs() -> None:
    steps = _wf()["jobs"]["weekly-digest"]["steps"]
    snooze = next(s for s in steps if s.get("id") == "snooze")
    assert snooze["if"].strip() == "always()"
    run = snooze["run"]
    assert "scripts/plan_2_8_alert_snooze.py" in run
    assert "configs/plan_2_8_snoozes.json" in run
    assert "digest.snoozed.json" in run
    assert "render_issue_body" in run


def test_resolve_alerts_step_emits_final_has_alerts() -> None:
    steps = _wf()["jobs"]["weekly-digest"]["steps"]
    resolve = next(s for s in steps if s.get("id") == "resolve_alerts")
    assert resolve["if"].strip() == "always()"
    run = resolve["run"]
    assert "alerts.json" in run
    assert "has_alerts=" in run
    assert "$GITHUB_OUTPUT" in run


def test_snooze_config_file_exists_and_is_valid_json() -> None:
    import json as _json
    cfg = Path(__file__).resolve().parents[1] / "configs" / "plan_2_8_snoozes.json"
    assert cfg.exists()
    data = _json.loads(cfg.read_text(encoding="utf-8"))
    assert isinstance(data.get("snoozes"), list)


def test_issue_step_uses_github_token() -> None:
    steps = _wf()["jobs"]["weekly-digest"]["steps"]
    issue = next(s for s in steps if s.get("name") == "Open drift-alert issue")
    assert issue["env"]["GH_TOKEN"] == "${{ secrets.GITHUB_TOKEN }}"


def test_issue_step_runs_after_upload() -> None:
    steps = _wf()["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert names.index("Upload weekly digest") < names.index("Open drift-alert issue")


def test_coverage_step_wired_fail_soft() -> None:
    steps = _wf()["jobs"]["weekly-digest"]["steps"]
    cov = next(s for s in steps if s.get("name") == "Plan 2.8 slice coverage")
    assert cov["if"].strip() == "always()"
    run = cov["run"]
    assert "scripts/plan_2_8_coverage.py" in run
    assert "set +e" in run
    assert run.rstrip().endswith("true")
    # Runs after top-movers so the summary flow reads coverage last.
    names = [s.get("name", "") for s in steps]
    assert names.index("Plan 2.8 top movers (30-day window)") \
        < names.index("Plan 2.8 slice coverage")


def test_stability_step_wired_fail_soft() -> None:
    steps = _wf()["jobs"]["weekly-digest"]["steps"]
    stab = next(s for s in steps
                if s.get("name") == "Plan 2.8 slice stability (last 8 snapshots)")
    assert stab["if"].strip() == "always()"
    run = stab["run"]
    assert "scripts/plan_2_8_history_stability.py" in run
    assert "set +e" in run
    assert run.rstrip().endswith("true")
    names = [s.get("name", "") for s in steps]
    assert names.index("Plan 2.8 slice coverage") \
        < names.index("Plan 2.8 slice stability (last 8 snapshots)")


def test_alert_history_append_step_wired() -> None:
    steps = _wf()["jobs"]["weekly-digest"]["steps"]
    ah = next(s for s in steps if s.get("name") == "Append alerts to history log")
    assert ah["if"].strip() == "always()"
    run = ah["run"]
    assert "plan_2_8_alert_history.py" in run
    assert "alert_history.jsonl" in run
    assert "RUN_URL" in ah["env"]
    assert run.rstrip().endswith("true")


def test_alert_history_uploaded_with_long_retention() -> None:
    steps = _wf()["jobs"]["weekly-digest"]["steps"]
    up = next(s for s in steps
              if s.get("name") == "Upload alert history log")
    assert up["uses"].startswith("actions/upload-artifact@v4")
    assert up["with"]["retention-days"] == 365
    assert up["with"]["name"] == "plan-2-8-alert-history"
    assert up["with"]["if-no-files-found"] == "ignore"


def test_snooze_lint_step_wired() -> None:
    steps = _wf()["jobs"]["weekly-digest"]["steps"]
    li = next(s for s in steps if s.get("name") == "Lint snooze config")
    assert li["if"].strip() == "always()"
    run = li["run"]
    assert "scripts/plan_2_8_snooze_lint.py" in run
    assert "--warn-only" in run
    assert run.rstrip().endswith("true")
    # Must precede the snooze apply step so operators see findings
    # *before* their config is consumed.
    names = [s.get("name", "") for s in steps]
    assert names.index("Lint snooze config") \
        < names.index("Apply alert snooze config")


def test_alert_history_summary_step_wired() -> None:
    steps = _wf()["jobs"]["weekly-digest"]["steps"]
    su = next(s for s in steps
              if s.get("name") == "Plan 2.8 alert-history summary (90-day window)")
    assert su["if"].strip() == "always()"
    run = su["run"]
    assert "scripts/plan_2_8_alert_history_summary.py" in run
    assert "--lookback-days 90" in run
    assert run.rstrip().endswith("true")
    # Must run after the upload step so the artifact is guaranteed on disk.
    names = [s.get("name", "") for s in steps]
    assert names.index("Upload alert history log") \
        < names.index("Plan 2.8 alert-history summary (90-day window)")
