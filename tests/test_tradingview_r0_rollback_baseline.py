"""Contract tests for the immutable TradingView Phase-R0 rollback baseline."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = (
    ROOT
    / "artifacts"
    / "monitoring"
    / "tradingview_r0_rollback_baseline_2026-07-27.json"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def _baseline() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def test_r0_baseline_is_self_consistent_and_rollback_ready() -> None:
    baseline = _baseline()
    source_baseline = baseline["sourceBaseline"]
    binding_baseline = baseline["bindingBaseline"]
    alerts = baseline["alertInventory"]
    rollback = baseline["rollbackTarget"]

    assert baseline["schemaVersion"] == 1
    assert baseline["baselineKind"] == "tradingview_phase_r0_rollback"
    assert COMMIT_RE.fullmatch(baseline["repository"]["commit"])
    assert baseline["repository"]["inputsMatchCommit"] is True

    assert source_baseline["expected"] == source_baseline["checked"] == 8
    assert source_baseline["drifted"] == 0
    assert len(source_baseline["sources"]) == source_baseline["expected"]
    assert len({item["scriptName"] for item in source_baseline["sources"]}) == 8
    assert all(
        SHA256_RE.fullmatch(item["sha256"])
        for item in source_baseline["sources"]
    )

    assert binding_baseline["expectedConsumers"] == 7
    assert binding_baseline["checkedConsumers"] == 7
    assert binding_baseline["checkedBindings"] == sum(
        item["checkedBindings"] for item in binding_baseline["consumers"]
    )
    assert binding_baseline["checkedBindings"] == 108
    assert binding_baseline["mismatches"] == 0
    assert binding_baseline["runtimeErrors"] == 0

    assert alerts["inventoryCompleteness"] == "complete_no_scroll_overflow"
    assert alerts["historicalAlertCount"] == len(alerts["alerts"]) == 2
    assert alerts["activeAlertCount"] == 0
    assert all(item["status"] == "stopped_manually" for item in alerts["alerts"])

    assert rollback["repositoryCommit"] == baseline["repository"]["commit"]
    assert rollback["libraryVersion"] == baseline["libraryRelease"]["publishedVersion"]
    assert rollback["layoutId"] == baseline["layout"]["id"]
    assert rollback["bindingCountToRestore"] == binding_baseline["checkedBindings"]
    assert rollback["activeAlertCountToRestore"] == alerts["activeAlertCount"]


def test_r0_inventory_was_read_only_and_raw_evidence_is_hash_addressed() -> None:
    baseline = _baseline()

    assert set(baseline["inventorySessionMutations"].values()) == {0}
    for evidence_name in ("activationReport", "freshReadOnlyVerification"):
        evidence = baseline["evidence"][evidence_name]
        assert evidence["availability"] == "operator_local_not_repository_tracked"
        assert evidence["operatorLocalPathAtCapture"].startswith("/private/tmp/")
        assert SHA256_RE.fullmatch(evidence["sha256"])
