"""Deduplicate Grafana's macOS APFS free-space alerts.

Grafana's stock macOS integration evaluates every writable filesystem. APFS
reports the same container-level free space on the Data, VM, Update and Preboot
volumes, so one nearly-full container pages four times. This idempotent patch
keeps the canonical Data-volume signal and external filesystems while excluding
the three synthetic system mountpoints from the warning and critical rules.
"""

from __future__ import annotations

import argparse
import copy
from typing import Any

from scripts import grafana_alert_rules_upsert as grafana

FOLDER_UID = "integration---macos-node"
RULE_GROUP = "darwin-filesystem-alerts"
GROUP_PATH = f"/api/v1/provisioning/folder/{FOLDER_UID}/rule-groups/{RULE_GROUP}"
TARGET_RULES = {
    "918f2f3c-70a2-566e-8acc-51d54c2accd7": "warning",
    "328b9506-6a89-5d4a-ba5c-715ab4f55abf": "critical",
}
EXCLUSION_MATCHER = 'mountpoint!~"/System/Volumes/(VM|Update|Preboot)"'
_SELECTOR_SUFFIX = 'mountpoint!=""}'


def patch_rule(rule: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Return a validated rule with synthetic APFS mountpoints excluded."""
    uid = str(rule.get("uid") or "")
    severity = TARGET_RULES.get(uid)
    if severity is None:
        raise ValueError(f"unsupported macOS filesystem alert uid: {uid or '<missing>'}")
    if rule.get("title") != "NodeFilesystemAlmostOutOfSpace":
        raise ValueError(f"unexpected title for {uid}: {rule.get('title')!r}")
    if (rule.get("labels") or {}).get("severity") != severity:
        raise ValueError(f"unexpected severity for {uid}: {rule.get('labels')!r}")

    patched = copy.deepcopy(rule)
    expressions: list[dict[str, Any]] = []
    for query in patched.get("data") or []:
        model = query.get("model") if isinstance(query, dict) else None
        if isinstance(model, dict) and isinstance(model.get("expr"), str):
            expressions.append(model)
    if len(expressions) != 1:
        raise ValueError(f"expected exactly one PromQL expression for {uid}")

    model = expressions[0]
    expression = model["expr"]
    if EXCLUSION_MATCHER in expression:
        return patched, False
    if expression.count(_SELECTOR_SUFFIX) != 3:
        raise ValueError(f"unexpected filesystem selector shape for {uid}")
    replacement = f'mountpoint!="",{EXCLUSION_MATCHER}' + "}"
    model["expr"] = expression.replace(_SELECTOR_SUFFIX, replacement)
    return patched, True


def provisioned_payload(rule: dict[str, Any]) -> dict[str, Any]:
    """Strip read-only response fields before a per-rule provisioning PUT."""
    required = (
        "uid",
        "title",
        "condition",
        "data",
        "for",
        "folderUID",
        "ruleGroup",
        "orgID",
        "noDataState",
        "execErrState",
        "isPaused",
    )
    missing = [key for key in required if key not in rule]
    if missing:
        raise ValueError(f"Grafana rule payload is missing fields: {missing}")
    payload = {key: rule[key] for key in required}
    for optional in ("annotations", "labels"):
        if isinstance(rule.get(optional), dict):
            payload[optional] = rule[optional]
    return payload


def provisioned_group_payload(group: dict[str, Any]) -> dict[str, Any]:
    """Strip read-only response fields from an alert-rule group."""
    if group.get("title") != RULE_GROUP:
        raise ValueError(f"unexpected rule group title: {group.get('title')!r}")
    if group.get("folderUid") != FOLDER_UID:
        raise ValueError(f"unexpected rule group folder: {group.get('folderUid')!r}")
    if not isinstance(group.get("interval"), int):
        raise ValueError("Grafana rule group is missing its interval")
    rules = group.get("rules")
    if not isinstance(rules, list):
        raise ValueError("Grafana rule group is missing its rules")
    return {
        "title": group["title"],
        "folderUid": group["folderUid"],
        "interval": group["interval"],
        "rules": [provisioned_payload(rule) for rule in rules],
    }


def reconcile(*, dry_run: bool) -> int:
    """Patch both stock rules atomically and verify the desired matcher."""
    token = grafana._api_key()
    group = grafana._request("GET", GROUP_PATH, token)
    if not isinstance(group, dict):
        raise RuntimeError("Grafana returned no macOS filesystem rule group")
    original_rules = group.get("rules")
    if not isinstance(original_rules, list):
        raise RuntimeError("Grafana returned an invalid macOS filesystem rule group")

    patched_group = copy.deepcopy(group)
    patched_rules = patched_group["rules"]
    positions = {
        str(rule.get("uid") or ""): index
        for index, rule in enumerate(patched_rules)
        if isinstance(rule, dict)
    }
    missing = sorted(set(TARGET_RULES) - positions.keys())
    if missing:
        raise RuntimeError(f"Grafana rule group is missing target rules: {missing}")

    changed = 0
    statuses: list[tuple[str, bool]] = []
    for uid, severity in TARGET_RULES.items():
        rule = patched_rules[positions[uid]]
        patched, did_change = patch_rule(rule)
        patched_rules[positions[uid]] = patched
        if did_change:
            changed += 1
        statuses.append((severity, did_change))

    if changed and not dry_run:
        # Grafana's stock integration stores this group with
        # ``converted_prometheus`` provenance. Per-rule PUTs cannot retain or
        # clear that provenance and fail with HTTP 409. A group PUT with
        # X-Disable-Provenance performs the supported atomic transition while
        # preserving all six rules in the group.
        grafana._request(
            "PUT",
            GROUP_PATH,
            token,
            payload=provisioned_group_payload(patched_group),
            extra_headers={"X-Disable-Provenance": "true"},
        )
        current_group = grafana._request("GET", GROUP_PATH, token)
        if not isinstance(current_group, dict):
            raise RuntimeError("Grafana returned no rule group after update")
        current_rules = current_group.get("rules")
        if not isinstance(current_rules, list):
            raise RuntimeError("Grafana returned invalid rules after update")
        current_by_uid = {
            str(rule.get("uid") or ""): rule
            for rule in current_rules
            if isinstance(rule, dict)
        }
        if list(current_by_uid) != [str(rule.get("uid") or "") for rule in original_rules]:
            raise RuntimeError("Grafana rule set changed during APFS reconciliation")
        for uid in TARGET_RULES:
            _, still_changed = patch_rule(current_by_uid[uid])
            if still_changed:
                raise RuntimeError(f"Grafana did not persist APFS matcher for {uid}")
        for rule in original_rules:
            uid = str(rule.get("uid") or "")
            if uid not in TARGET_RULES and provisioned_payload(rule) != provisioned_payload(
                current_by_uid[uid]
            ):
                raise RuntimeError(f"Grafana changed non-target rule {uid}")

    for severity, did_change in statuses:
        print(f"{severity}: {'would patch' if dry_run and did_change else 'patched' if did_change else 'current'}")
    print(f"macOS APFS alert reconciliation complete: changed={changed} dry_run={dry_run}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        return reconcile(dry_run=args.dry_run)
    except Exception as exc:
        print(f"macOS APFS alert reconciliation failed: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
