"""Static coupling guard: Cisco self-probe metrics <-> Grafana alert rules.

The 2026-06/07 blind-spot class (metric exported, zero alert rules reference
it) and its inverse (rule references a series the exporter renamed) both fail
here: the expected series names are BUILT from the exporter's constants in
``open_prep/cisco_probe.py``, so a rename on either side breaks this test.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from open_prep.cisco_probe import METRIC_LAST_SUCCESS_AGE

_RULES_PATH = (
    Path(__file__).resolve().parents[1]
    / "services"
    / "live_overlay_daemon"
    / "infra"
    / "grafana"
    / "alert-rules.yaml"
)

_AGE_SERIES = f"signals_producer_{METRIC_LAST_SUCCESS_AGE}"


def _rules_by_uid() -> dict[str, dict[str, Any]]:
    doc = yaml.safe_load(_RULES_PATH.read_text(encoding="utf-8"))
    rules: dict[str, dict[str, Any]] = {}
    for group in doc["groups"]:
        for rule in group.get("rules", []):
            rules[str(rule.get("uid"))] = rule
    return rules


def _prom_exprs(rule: dict[str, Any]) -> list[str]:
    return [
        str(item.get("model", {}).get("expr", ""))
        for item in rule.get("data", [])
        if item.get("datasourceUid") != "__expr__"
    ]


def test_stale_rule_watches_the_exported_age_series() -> None:
    rule = _rules_by_uid().get("sp-cisco-probe-stale")
    assert rule is not None, "sp-cisco-probe-stale rule missing from alert-rules.yaml"
    exprs = "\n".join(_prom_exprs(rule))
    assert f'{_AGE_SERIES}{{job="signals_producer"}}' in exprs
    assert rule["labels"]["severity"] == "warning"
    assert rule["for"] == "30m"


def test_stale_rule_threshold_exceeds_two_probe_intervals() -> None:
    rule = _rules_by_uid()["sp-cisco-probe-stale"]
    thresholds = [
        cond["evaluator"]["params"][0]
        for item in rule["data"]
        if item.get("datasourceUid") == "__expr__"
        for cond in item["model"]["conditions"]
    ]
    assert thresholds == [7200], "stale threshold must stay >= 2x RT_CISCO_PROBE_SECS default (3600)"


def test_missing_rule_guards_series_absence_with_nodata_ok() -> None:
    rule = _rules_by_uid().get("sp-cisco-probe-missing")
    assert rule is not None, "sp-cisco-probe-missing rule missing from alert-rules.yaml"
    exprs = "\n".join(_prom_exprs(rule))
    assert f'absent({_AGE_SERIES}{{job="signals_producer"}})' in exprs
    # absent() yields an empty vector when healthy; NoData must stay quiet or
    # the rule pages on every healthy evaluation.
    assert rule["noDataState"] == "OK"
    assert rule["labels"]["severity"] == "warning"


def test_exporter_emits_the_series_the_rules_watch() -> None:
    exporter = (
        Path(__file__).resolve().parents[1] / "open_prep" / "cisco_probe.py"
    ).read_text(encoding="utf-8")
    assert 'METRIC_LAST_SUCCESS_AGE = "cisco_probe_last_success_age_seconds"' in exporter
    collector = (
        Path(__file__).resolve().parents[1] / "open_prep" / "realtime_signals.py"
    ).read_text(encoding="utf-8")
    assert '_prefix = "signals_producer"' in collector
    assert "_prober.metrics_lines(_prefix)" in collector
