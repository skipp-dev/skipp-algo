from pathlib import Path

import yaml


def test_pre_a0_alert_rules_cover_fail_closed_states() -> None:
    text = (
        Path(__file__).parents[1]
        / "services"
        / "a0_fast_detector"
        / "pre-a0-alert-rules.yml"
    ).read_text(encoding="utf-8")
    for alert in (
        "PreA0ModelUnavailable",
        "PreA0CalibrationInvalid",
        "PreA0InferenceErrors",
        "PreA0FeatureMissingness",
        "PreA0AlertBudgetExceeded",
        "PreA0DuplicateDecisionId",
        "PreA0PersistenceErrors",
        "PreA0ShadowDataMissing",
    ):
        assert alert in text


def test_grafana_pre_a0_rules_cover_scrape_runtime_and_shadow_integrity() -> None:
    path = (
        Path(__file__).parents[1]
        / "services"
        / "live_overlay_daemon"
        / "infra"
        / "grafana"
        / "alert-rules.yaml"
    )
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    group = next(group for group in document["groups"] if group["name"] == "pre-a0-shadow")
    rules = {rule["uid"]: rule for rule in group["rules"]}

    assert {
        "pre-a0-scrape-missing",
        "pre-a0-model-unavailable",
        "pre-a0-calibration-invalid",
        "pre-a0-runtime-errors",
        "pre-a0-input-drift",
        "pre-a0-shadow-data-missing",
    } <= rules.keys()
    expressions = "\n".join(
        node["model"].get("expr", "")
        for rule in rules.values()
        for node in rule["data"]
    )
    assert 'absent(pre_a0_enabled{job="a0_fast"})' in expressions
    assert "pre_a0_model_ready" in expressions
    assert "pre_a0_calibration_valid" in expressions
    assert "pre_a0_persistence_errors_total" in expressions
    assert "a0_fast_records_received_total" in expressions
    assert "a0_fast_evidence_ready" in expressions
    assert "== bool 0" in expressions
