"""Structural pin for ``.github/workflows/smc-live-newsapi-refresh.yml``.

Why this exists
===============

`smc-live-newsapi-refresh.yml` is a mutating cron workflow (writes snapshot
artifacts and force-updates `bot/live-news-snapshot`). Subtle structural drift
in trigger cadence, concurrency policy, runner wiring, or push failure
semantics can silently degrade freshness and state continuity.

This pin freezes the load-bearing workflow contract so accidental edits are
caught as test failures.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "smc-live-newsapi-refresh.yml"


@pytest.fixture(scope="module")
def workflow_doc() -> dict:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert isinstance(data, dict), "workflow must parse as a mapping"
    return data


@pytest.fixture(scope="module")
def refresh_job(workflow_doc: dict) -> dict:
    jobs = workflow_doc.get("jobs")
    assert isinstance(jobs, dict), "workflow must define jobs"
    assert "refresh" in jobs, "workflow must keep `refresh` job key"
    job = jobs["refresh"]
    assert isinstance(job, dict)
    return job


def test_triggers_pinned(workflow_doc: dict) -> None:
    # PyYAML may parse bare `on:` as boolean True; tolerate both shapes.
    on_block = workflow_doc.get("on") if "on" in workflow_doc else workflow_doc.get(True)
    assert isinstance(on_block, dict), "workflow must declare `on:` mapping"

    schedule = on_block.get("schedule")
    assert isinstance(schedule, list) and schedule, "workflow must declare a cron schedule"

    crons = [entry.get("cron") for entry in schedule if isinstance(entry, dict)]
    assert "2 * * * 1-5" in crons, (
        "smc-live-newsapi-refresh cadence pin drifted: expected hourly weekday cron "
        "`2 * * * 1-5`"
    )
    assert "workflow_dispatch" in on_block, "workflow must support manual workflow_dispatch"


def test_concurrency_contract_pinned(workflow_doc: dict) -> None:
    concurrency = workflow_doc.get("concurrency")
    assert isinstance(concurrency, dict), "workflow must declare `concurrency:`"
    assert concurrency.get("group") == "smc-live-newsapi-refresh", (
        "concurrency.group must stay pinned to smc-live-newsapi-refresh"
    )
    assert concurrency.get("cancel-in-progress") is False, (
        "cancel-in-progress must remain false to avoid killing in-flight mutable refresh runs"
    )


def test_job_wiring_pinned(workflow_doc: dict, refresh_job: dict) -> None:
    jobs = workflow_doc.get("jobs")
    assert isinstance(jobs, dict)
    assert "select-runner" in jobs, "workflow must keep select-runner job"

    needs = refresh_job.get("needs")
    assert needs == "select-runner", "refresh job must depend on select-runner"

    runs_on = refresh_job.get("runs-on")
    assert isinstance(runs_on, str)
    assert "fromJson(needs.select-runner.outputs.runs_on_json)" in runs_on, (
        "refresh.runs-on must remain wired to select-runner output"
    )


def test_publish_step_remains_fail_loud(refresh_job: dict) -> None:
    steps = refresh_job.get("steps")
    assert isinstance(steps, list) and steps, "refresh must define steps"

    publish = next(
        (
            step
            for step in steps
            if isinstance(step, dict)
            and step.get("name") == "Publish snapshot to rolling bot branch"
        ),
        None,
    )
    assert isinstance(publish, dict), "publish step missing"

    run = publish.get("run") or ""
    assert "if git push --force-with-lease=refs/heads/bot/live-news-snapshot" in run, (
        "publish step must keep explicit push success/failure branching"
    )
    assert "exit 1" in run, "publish step must remain fail-loud on push failure"


def test_ttl_env_pin_present(refresh_job: dict) -> None:
    steps = refresh_job.get("steps")
    assert isinstance(steps, list)

    refresh_step = next(
        (
            step
            for step in steps
            if isinstance(step, dict)
            and step.get("name") == "Refresh NewsAPI.ai live snapshot"
        ),
        None,
    )
    assert isinstance(refresh_step, dict), "Refresh NewsAPI.ai live snapshot step missing"

    env = refresh_step.get("env")
    assert isinstance(env, dict)
    assert env.get("NEWSAPI_AI_SHARED_CACHE_TTL_SECONDS") == "3900", (
        "NEWSAPI_AI_SHARED_CACHE_TTL_SECONDS pin drifted; expected 3900"
    )
