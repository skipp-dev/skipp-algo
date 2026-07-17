from pathlib import Path


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
    ):
        assert alert in text
