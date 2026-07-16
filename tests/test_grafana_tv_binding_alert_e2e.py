from __future__ import annotations

from pathlib import Path

import yaml

from scripts import grafana_tv_binding_alert_e2e as mod


def test_clone_is_silenced_labeled_and_does_not_modify_source() -> None:
    source = {
        "uid": "source",
        "title": "Production rule",
        "ruleGroup": "production",
        "for": "30m",
        "labels": {"severity": "critical"},
        "data": [{"refId": "A", "model": {"expr": "production_metric > bool 0"}}],
    }
    clone = mod.build_test_clone(source, "source-e2e", "run-1")
    assert source["data"][0]["model"]["expr"] == "production_metric > bool 0"
    assert clone["data"][0]["model"]["expr"] == "vector(1)"
    assert clone["uid"] == "source-e2e"
    assert clone["ruleGroup"] == mod.TEST_GROUP
    assert clone["for"] == "0s"
    assert clone["labels"] == {"severity": "info", "test_run": "run-1"}


def test_workflow_is_manual_and_execute_defaults_false() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/tv-binding-alert-e2e.yml").read_text())
    on_block = workflow.get("on") or workflow.get(True)
    assert set(on_block) == {"workflow_dispatch"}
    assert on_block["workflow_dispatch"]["inputs"]["execute"]["default"] is False
    steps = workflow["jobs"]["alert-e2e"]["steps"]
    execute = next(step for step in steps if step.get("name", "").startswith("Execute"))
    assert "execute == 'true'" in execute["if"]
    assert execute["env"]["GRAFANA_API_KEY"] == "${{ secrets.GRAFANA_API_TOKEN }}"
