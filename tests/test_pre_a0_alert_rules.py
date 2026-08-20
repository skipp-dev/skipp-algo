"""PRE-A0 fail-closed states must be alerted by the DEPLOYED rule file.

See tests/test_a0_fast_alert_rules.py for the history: the previous version of
this file asserted rule NAMES against
``services/a0_fast_detector/pre-a0-alert-rules.yml``, which nothing deployed,
and asserted UIDs against the published file, which is why
``pre-a0-shadow-data-missing`` could carry a title about snapshots while its
expression only looked at ``a0_fast_evidence_ready``. Both halves are now
expression-based.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
DEPLOYED_RULES = REPO / "services/live_overlay_daemon/infra/grafana/alert-rules.yaml"

# uid -> metric names the expression MUST reference.
_REQUIRED_PRE_A0_RULES: dict[str, tuple[str, ...]] = {
    "pre-a0-scrape-missing": ("pre_a0_enabled",),
    "pre-a0-model-unavailable": ("pre_a0_model_ready",),
    "pre-a0-calibration-invalid": ("pre_a0_calibration_valid",),
    "pre-a0-runtime-errors": ("pre_a0_persistence_errors_total",),
    "pre-a0-input-drift": ("pre_a0_feature_out_of_range_total",),
    "pre-a0-alert-budget-exceeded": ("pre_a0_alert_budget_exceeded_total",),
    # The rule the old title merely promised. PRE-A0 scoring while
    # snapshots_recorded stays flat means the promotion evidence base has
    # stopped growing -- and lost snapshot days cannot be reconstructed.
    #
    # 2026-08-20: the load guard was a0_fast_records_processed_total, which runs
    # pre- and post-market while the snapshot counter only moves 13-20 UTC. The
    # pair compared unlike things and the CRITICAL rule was true 23.2% of the
    # week. pre_a0_scores_total shares the snapshots' window exactly, so the
    # guard needs no clock and survives DST.
    "pre-a0-snapshots-not-recorded": (
        "pre_a0_scores_total",
        "pre_a0_snapshots_recorded_total",
    ),
}


def _pre_a0_group() -> dict:
    document = yaml.safe_load(DEPLOYED_RULES.read_text(encoding="utf-8"))
    return next(
        group for group in document["groups"] if group["name"] == "pre-a0-shadow"
    )


def _rules() -> dict[str, dict]:
    return {rule["uid"]: rule for rule in _pre_a0_group()["rules"]}


def _expressions(rule: dict) -> str:
    return "\n".join(node["model"].get("expr", "") for node in rule["data"])


def test_every_pre_a0_fail_closed_state_has_a_deployed_rule() -> None:
    rules = _rules()
    missing = sorted(uid for uid in _REQUIRED_PRE_A0_RULES if uid not in rules)
    assert not missing, (
        f"PRE-A0 fail-closed states without a deployed rule: {missing}"
    )


@pytest.mark.parametrize("uid", sorted(_REQUIRED_PRE_A0_RULES))
def test_deployed_rule_measures_what_its_name_claims(uid: str) -> None:
    rule = _rules()[uid]
    expressions = _expressions(rule)
    absent = [
        metric for metric in _REQUIRED_PRE_A0_RULES[uid] if metric not in expressions
    ]
    assert not absent, (
        f"rule {uid} no longer references {absent} -- expression drifted away "
        "from the state the uid names."
    )


def test_scrape_missing_rule_stays_fail_closed() -> None:
    """absent() + a bool comparison is what makes the group fail closed."""
    expressions = "\n".join(_expressions(rule) for rule in _rules().values())
    assert 'absent(pre_a0_enabled{job="a0_fast"})' in expressions
    assert "== bool 0" in expressions
