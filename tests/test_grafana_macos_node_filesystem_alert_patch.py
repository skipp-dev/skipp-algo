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


def _group() -> dict:
    return {
        "title": patcher.RULE_GROUP,
        "folderUid": patcher.FOLDER_UID,
        "interval": 60,
        "rules": [
            _rule(uid, severity) for uid, severity in patcher.TARGET_RULES.items()
        ],
    }


@pytest.mark.parametrize("uid,severity", sorted(patcher.TARGET_RULES.items()))  # sorted: xdist-deterministic collection
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


def test_provisioned_group_payload_preserves_all_rules() -> None:
    group = _group()
    payload = patcher.provisioned_group_payload(group)
    assert payload["title"] == patcher.RULE_GROUP
    assert [rule["uid"] for rule in payload["rules"]] == list(patcher.TARGET_RULES)
    assert all("id" not in rule and "updated" not in rule for rule in payload["rules"])


def test_reconcile_dry_run_never_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    group = _group()
    calls: list[str] = []

    monkeypatch.setattr(patcher.grafana, "_api_key", lambda: "token")

    def request(method: str, path: str, _token: str, **_kwargs: object) -> dict:
        calls.append(method)
        assert path == patcher.GROUP_PATH
        return copy.deepcopy(group)

    monkeypatch.setattr(patcher.grafana, "_request", request)
    assert patcher.reconcile(dry_run=True) == 0
    assert calls == ["GET"]


def test_reconcile_updates_converted_group_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _group()
    calls: list[tuple[str, dict | None, dict | None]] = []
    monkeypatch.setattr(patcher.grafana, "_api_key", lambda: "token")

    def request(
        method: str,
        path: str,
        _token: str,
        *,
        payload: dict | None = None,
        extra_headers: dict | None = None,
    ) -> dict:
        assert path == patcher.GROUP_PATH
        calls.append((method, copy.deepcopy(payload), extra_headers))
        if method == "PUT":
            stored.clear()
            stored.update(copy.deepcopy(payload))
        return copy.deepcopy(stored)

    monkeypatch.setattr(patcher.grafana, "_request", request)
    assert patcher.reconcile(dry_run=False) == 0
    assert [method for method, _, _ in calls] == ["GET", "PUT", "GET"]
    assert calls[1][2] == {"X-Disable-Provenance": "true"}
    for rule in stored["rules"]:
        expression = rule["data"][0]["model"]["expr"]
        assert expression.count(patcher.EXCLUSION_MATCHER) == 3
