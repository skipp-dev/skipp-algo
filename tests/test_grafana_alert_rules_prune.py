"""Regression tests for WP-C5 (pipeline/data/ops audit, MED).

The upsert script's per-group PUT cannot see groups removed from the YAML.
``reconcile_orphan_groups`` reports (default) or prunes (--prune) live groups
absent from the YAML, restricted to folders the YAML manages.
"""

from __future__ import annotations

from unittest.mock import patch

import scripts.grafana_alert_rules_upsert as mod

_GROUPS = [
    {"folder": "SMC Live Overlay", "name": "live-overlay-critical", "rules": []},
    {"folder": "SMC Live Overlay", "name": "live-overlay-warning", "rules": []},
]


def _fake_request(method, path, key, payload=None, extra_headers=None):
    if method == "GET" and path == "/api/v1/provisioning/alert-rules":
        return [
            {"folderUID": "uid-slo", "ruleGroup": "live-overlay-critical"},
            {"folderUID": "uid-slo", "ruleGroup": "live-overlay-warning"},
            {"folderUID": "uid-slo", "ruleGroup": "stale-orphan-group"},
            {"folderUID": "uid-other", "ruleGroup": "unrelated-group"},
        ]
    return None


def test_orphan_group_warned_not_pruned_by_default() -> None:
    with (
        patch.object(mod, "resolve_folder_uid", return_value="uid-slo"),
        patch.object(mod, "_request", side_effect=_fake_request),
        patch.object(mod, "delete_rule_group") as del_mock,
    ):
        orphans = mod.reconcile_orphan_groups(_GROUPS, "k", prune=False)

    assert orphans == ["SMC Live Overlay/stale-orphan-group"]
    del_mock.assert_not_called()


def test_orphan_group_pruned_when_requested() -> None:
    with (
        patch.object(mod, "resolve_folder_uid", return_value="uid-slo"),
        patch.object(mod, "_request", side_effect=_fake_request),
        patch.object(mod, "delete_rule_group") as del_mock,
    ):
        orphans = mod.reconcile_orphan_groups(_GROUPS, "k", prune=True)

    assert orphans == ["SMC Live Overlay/stale-orphan-group"]
    del_mock.assert_called_once_with("uid-slo", "stale-orphan-group", "k")


def test_unmanaged_folder_groups_never_touched() -> None:
    # uid-other holds "unrelated-group"; it must never be reported/pruned
    # because that folder is not in the YAML.
    with (
        patch.object(mod, "resolve_folder_uid", return_value="uid-slo"),
        patch.object(mod, "_request", side_effect=_fake_request),
        patch.object(mod, "delete_rule_group"),
    ):
        orphans = mod.reconcile_orphan_groups(_GROUPS, "k", prune=True)

    assert "unrelated-group" not in " ".join(orphans)
