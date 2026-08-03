from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/pre-a0-mlflow-health.yml")


def test_health_workflow_is_read_only_scheduled_and_fail_loud() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    parsed = yaml.safe_load(text)
    triggers = parsed.get(True) or parsed["on"]
    assert {item["cron"] for item in triggers["schedule"]} == {"17,47 * * * *"}
    assert "workflow_dispatch" in triggers
    assert parsed["permissions"] == {"contents": "read"}
    assert parsed["concurrency"]["cancel-in-progress"] is False
    assert "# live-window: off-hours-only" in "\n".join(text.splitlines()[:5])
    assert "python scripts/check_pre_a0_mlflow_health.py" in text
    assert "exit \"$PROBE_RC\"" in text
    assert "continue-on-error" not in text


def test_health_workflow_expected_artifact_id_matches_the_script_default() -> None:
    """Anti-drift pin between the two places the artifact id is written.

    2026-08-03: the retrain PR (#4358) repinned DEFAULT_ARTIFACT_ID in the
    script and the governance bundle but missed the workflow's hard-coded
    --expected-artifact-id — CI then reported tag_mismatch against a live,
    correct MLflow registration while the local probe (using the script
    default) said healthy. Two writers, one value: pin them together.
    """
    from scripts.check_pre_a0_mlflow_health import DEFAULT_ARTIFACT_ID

    text = WORKFLOW.read_text(encoding="utf-8")
    assert f"--expected-artifact-id {DEFAULT_ARTIFACT_ID}" in text, (
        "workflow --expected-artifact-id disagrees with "
        "scripts/check_pre_a0_mlflow_health.DEFAULT_ARTIFACT_ID — update both "
        "in the same PR (the daily retrain job seds exactly these two files)"
    )


def test_health_workflow_uses_pinned_actions_and_dedicated_secrets() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6" in text
    assert "actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405 # v6" in text
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7" in text
    assert "secrets.PRE_A0_MLFLOW_MONITOR_USERNAME" in text
    assert "secrets.PRE_A0_MLFLOW_MONITOR_PASSWORD" in text
