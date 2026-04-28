"""Pin-tests for the Plan 2.8 monthly digest workflow."""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github" / "workflows" / "plan-2-8-monthly-digest.yml"
)


def _wf() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return {"on": data.get("on", data.get(True)),
            **{k: v for k, v in data.items() if k not in ("on", True)}}


def test_scheduled_monthly_and_dispatch() -> None:
    on = _wf()["on"]
    assert "workflow_dispatch" in on
    cron = on["schedule"][0]["cron"]
    assert cron == "0 13 1 * *"


def test_dispatch_inputs_have_sensible_defaults() -> None:
    inputs = _wf()["on"]["workflow_dispatch"]["inputs"]
    assert inputs["lookback_days"]["default"] == "30"
    assert inputs["min_events"]["default"] == "30"
    assert inputs["alert_threshold_pp"]["default"] == "0.05"


def test_permissions_are_read_only() -> None:
    perms = _wf()["permissions"]
    assert perms["contents"] == "read"
    assert perms["actions"] == "read"
    assert "issues" not in perms


def test_download_latest_bench_artifact_regexp() -> None:
    steps = _wf()["jobs"]["monthly-digest"]["steps"]
    dl = next(s for s in steps if "Download latest rolling bench" in s.get("name", ""))
    assert dl["with"]["name"] == "^smc-measurement-benchmark-rolling-.*$"
    assert dl["with"]["name_is_regexp"] is True


def test_monthly_digest_step_uses_30d_lookback_default() -> None:
    steps = _wf()["jobs"]["monthly-digest"]["steps"]
    digest = next(s for s in steps if s.get("id") == "digest")
    run = digest["run"]
    assert "scripts/plan_2_8_trend_digest.py" in run
    assert "inputs.lookback_days || '30'" in run
    assert "monthly_digest.md" in run


def test_monthly_top_movers_step_present_fail_soft() -> None:
    steps = _wf()["jobs"]["monthly-digest"]["steps"]
    mv = next(s for s in steps
              if s.get("name") == "Plan 2.8 top movers (monthly)")
    run = mv["run"]
    assert "scripts/plan_2_8_top_movers.py" in run
    assert "--top-n         10" in run
    assert "set +e" in run
    assert run.rstrip().endswith("true")


def test_upload_artifact_has_one_year_retention() -> None:
    steps = _wf()["jobs"]["monthly-digest"]["steps"]
    up = next(s for s in steps if s.get("name") == "Upload monthly digest")
    assert up["with"]["name"] == "plan-2-8-monthly-digest"
    assert up["with"]["retention-days"] == 365


def test_monthly_rollup_step_wired_fail_soft() -> None:
    data = _wf()
    steps = data["jobs"]["monthly-digest"]["steps"]
    rl = next(s for s in steps
              if s.get("name") == "Plan 2.8 rolling HR trend (8 weeks)")
    assert rl["if"].strip() == "always()"
    run = rl["run"]
    assert "scripts/plan_2_8_digest_rollup.py" in run
    assert "--weeks      8" in run
    assert "set +e" in run
    assert run.rstrip().endswith("true")
