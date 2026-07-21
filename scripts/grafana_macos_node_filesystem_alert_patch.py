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


def reconcile(*, dry_run: bool) -> int:
    """Patch both stock rules and verify the desired matcher is present."""
    token = grafana._api_key()
    changed = 0
    for uid, severity in TARGET_RULES.items():
        path = f"/api/v1/provisioning/alert-rules/{uid}"
        rule = grafana._request("GET", path, token)
        if not isinstance(rule, dict):
            raise RuntimeError(f"Grafana returned no {severity} filesystem rule")
        patched, did_change = patch_rule(rule)
        if did_change:
            changed += 1
            if not dry_run:
                grafana._request(
                    "PUT",
                    path,
                    token,
                    payload=provisioned_payload(patched),
                    extra_headers={"X-Disable-Provenance": "true"},
                )
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
