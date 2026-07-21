from __future__ import annotations

import copy

import pytest

from scripts import grafana_macos_node_filesystem_alert_patch as patcher


def _rule(uid: str, severity: str) -> dict:
    selector = 'job="integrations/macos-node",fstype!="",mountpoint!=""'
    expression = (
        f"(node_filesystem_avail_bytes{{{selector}}} / "
        f"node_filesystem_size_bytes{{{selector}}} * 100 < 5 and "
        f"node_filesystem_readonly{{{selector}}} == 0)"
    )
    return {
        "uid": uid,
        "title": "NodeFilesystemAlmostOutOfSpace",
        "condition": "A",
        "data": [{"model": {"expr": expression}}],
        "for": "30m",
        "folderUID": patcher.FOLDER_UID,
        "ruleGroup": patcher.RULE_GROUP,
        "orgID": 1,
        "noDataState": "OK",
        "execErrState": "Error",
        "isPaused": False,
        "labels": {"severity": severity},
        "annotations": {"summary": "filesystem low"},
        "id": 123,
        "updated": "read-only",
    }


@pytest.mark.parametrize("uid,severity", patcher.TARGET_RULES.items())
def test_patch_rule_excludes_all_three_synthetic_apfs_series(
    uid: str, severity: str
) -> None:
    original = _rule(uid, severity)
    patched, changed = patcher.patch_rule(original)
    assert changed is True
    expression = patched["data"][0]["model"]["expr"]
    assert expression.count(patcher.EXCLUSION_MATCHER) == 3
    assert patcher.EXCLUSION_MATCHER not in original["data"][0]["model"]["expr"]

    current, changed_again = patcher.patch_rule(patched)
    assert changed_again is False
    assert current == patched


def test_patch_rule_rejects_contract_drift() -> None:
    rule = _rule(next(iter(patcher.TARGET_RULES)), "warning")
    rule["title"] = "DifferentRule"
    with pytest.raises(ValueError, match="unexpected title"):
        patcher.patch_rule(rule)


def test_provisioned_payload_drops_read_only_fields() -> None:
    rule = _rule(next(iter(patcher.TARGET_RULES)), "warning")
    payload = patcher.provisioned_payload(rule)
    assert "id" not in payload
    assert "updated" not in payload
    assert payload["annotations"] == rule["annotations"]


def test_reconcile_dry_run_never_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    rules = {
        uid: _rule(uid, severity) for uid, severity in patcher.TARGET_RULES.items()
    }
    calls: list[str] = []

    monkeypatch.setattr(patcher.grafana, "_api_key", lambda: "token")

    def request(method: str, path: str, _token: str, **_kwargs: object) -> dict:
        calls.append(method)
        uid = path.rsplit("/", 1)[-1]
        return copy.deepcopy(rules[uid])

    monkeypatch.setattr(patcher.grafana, "_request", request)
    assert patcher.reconcile(dry_run=True) == 0
    assert calls == ["GET", "GET"]
