#!/usr/bin/env python3
"""Upsert the SMC Live Overlay Grafana alert rules from the repo, idempotently.

Source of truth
---------------
``services/live_overlay_daemon/infra/grafana/alert-rules.yaml`` — Grafana's
*file-provisioning* format (``apiVersion: 1`` + ``groups:``).

Why this script exists
----------------------
The file-provisioning YAML is the format Grafana loads *from disk*. It is **not**
accepted by any single Grafana HTTP API endpoint: the previously documented
``POST /api/v1/provisioning/alert-rules`` curl only creates **one** rule and
silently ignores the ``groups:`` envelope, so a ``--data-binary @alert-rules.yaml``
call never actually provisioned the rule set. That mismatch is exactly how alerting
drifted from the repo.

This script bridges the gap. It parses the file format and upserts each rule
**group** via the idempotent endpoint::

    PUT /api/v1/provisioning/folder/{folderUID}/rule-groups/{group}

which overwrites the whole group (adds new rules, updates changed ones, removes
rules deleted from the repo). The result is a 1:1 reproducible deploy that cannot
silently drift from ``alert-rules.yaml``.

Auth
----
The Grafana API token is read from the ``GRAFANA_API_KEY`` environment variable
(for CI) or, as a fallback, the macOS Keychain entry ``skipp.grafana.api`` (same
entry the dashboard upsert uses). The token is never printed.

Usage
-----
Run from the repository root::

    python scripts/grafana_alert_rules_upsert.py            # validate + apply
    python scripts/grafana_alert_rules_upsert.py --dry-run  # validate only, no network
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ALERT_RULES_PATH = Path("services/live_overlay_daemon/infra/grafana/alert-rules.yaml")
GRAFANA_URL = os.environ.get("GRAFANA_URL", "https://bronzeporridge977.grafana.net")
KEYCHAIN_SERVICE = "skipp.grafana.api"
ENV_API_KEY = "GRAFANA_API_KEY"

# Grafana defaults preserved for rules that do not pin these explicitly.
DEFAULT_NO_DATA_STATE = "NoData"
DEFAULT_EXEC_ERR_STATE = "Error"
DEFAULT_ORG_ID = 1

_DURATION_RE = re.compile(r"^\s*(\d+)\s*([smhd]?)\s*$")
_DURATION_UNIT_SECONDS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}


# --------------------------------------------------------------------------- #
# Parsing / validation (pure, unit-testable, no network)
# --------------------------------------------------------------------------- #
def parse_interval_seconds(value: Any) -> int:
    """Convert a Grafana duration (``"1m"``, ``"30s"``, ``"1h"``, ``90``) to seconds."""
    if isinstance(value, bool):  # bool is an int subclass — reject explicitly
        raise ValueError(f"invalid interval: {value!r}")
    if isinstance(value, int):
        if value <= 0:
            raise ValueError(f"interval must be positive: {value!r}")
        return value
    if not isinstance(value, str):
        raise ValueError(f"invalid interval type: {value!r}")
    match = _DURATION_RE.match(value)
    if not match:
        raise ValueError(f"unparseable duration: {value!r}")
    magnitude = int(match.group(1))
    seconds = magnitude * _DURATION_UNIT_SECONDS[match.group(2)]
    if seconds <= 0:
        raise ValueError(f"interval must be positive: {value!r}")
    return seconds


def load_alert_groups(path: Path) -> list[dict[str, Any]]:
    """Load and return the ``groups`` list from a file-provisioning YAML document."""
    import yaml  # local import: keeps ``--help`` working without PyYAML installed

    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path}: top-level YAML must be a mapping")
    groups = document.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError(f"{path}: 'groups' must be a non-empty list")
    return groups


# --------------------------------------------------------------------------- #
# PromQL gating anti-pattern linter
# --------------------------------------------------------------------------- #
# Two production alerts have false-fired because a PromQL *set* operator
# (``and`` / ``unless`` / ``or``) was handed an operand that is *always a
# present series*, so it silently failed to gate:
#
#   * ``lo-request-rate-absent-open`` chained ``... and on(job) (rate < bool
#     0.001)``.  A ``bool`` comparison always yields a 0/1 series and ``and``
#     matches on series *presence*, not truth -> the guard never gated and the
#     alert fired through every US session.  Fix: multiply the 0/1 guards.
#   * ``sp-snapshot-missing`` used ``(1 - metric{labels}) or vector(1)``.  The
#     labelled left series never matches the empty-label ``vector(1)`` without
#     ``on()``, so the fallback ``{}=1`` was *always* appended and the alert
#     fired permanently.  Fix: ``or on() vector(1)``.
#
# Same class.  This linter encodes the invariant so neither the CI tests nor
# the deploy path can regress, and code review no longer has to reason about
# vector-matching semantics by hand.

_BOOL_CMP_RE = re.compile(r"\bbool\b")
# Left operands reduced to the empty label set ``{}`` (so an ``or vector()``
# fallback matches correctly without an explicit ``on()``).
_LABEL_FREE_LHS_RE = re.compile(
    r"^\(*\s*(?:sum|count|avg|min|max|group|stddev|stdvar|topk|bottomk|"
    r"quantile|count_values|histogram_quantile|scalar|vector)\b"
)
_MATCH_MODIFIER = r"(?:\s*(?:on|ignoring)\s*\([^)]*\))?"


def _top_level_setops(expr: str) -> list[tuple[str, int, int]]:
    """Return ``(op, start, end)`` for each set operator at paren depth 0."""
    ops: list[tuple[str, int, int]] = []
    depth = 0
    for m in re.finditer(r"\(|\)|\b(?:and|unless|or)\b", expr):
        tok = m.group(0)
        if tok == "(":
            depth += 1
        elif tok == ")":
            depth -= 1
        elif depth == 0:
            ops.append((tok, m.start(), m.end()))
    return ops


def _operand_start(expr: str, before: int) -> int:
    """Return the index where the left operand ending at ``before`` begins."""
    i = before - 1
    depth = 0
    while i >= 0:
        c = expr[i]
        if c == ")":
            depth += 1
        elif c == "(":
            if depth == 0:
                return i + 1
            depth -= 1
        i -= 1
    return 0


def find_promql_gating_antipatterns(expr: str) -> list[str]:
    """Return findings for set-operator gating anti-patterns (empty == clean)."""
    findings: list[str] = []
    ops = _top_level_setops(expr)

    # Detector A: ``and``/``unless`` whose right (gating) operand is a bool
    # comparison -- a bool result is always present, so it never gates.
    for idx, (op, _start, end) in enumerate(ops):
        if op not in ("and", "unless"):
            continue
        nxt = ops[idx + 1][1] if idx + 1 < len(ops) else len(expr)
        rhs = re.sub(r"^\s*(?:on|ignoring)\s*\([^)]*\)", "", expr[end:nxt])
        if _BOOL_CMP_RE.search(rhs):
            findings.append(
                f"`{op}` is gated by a `bool` comparison (`{rhs.strip()[:70]}`): "
                f"a bool result is always a present series, so `{op}` never "
                f"gates on it -- combine 0/1 guards with arithmetic (`*`)."
            )

    # Detector B: ``or vector()/scalar()`` fallback without ``on()``/``ignoring()``
    # over a label-retaining left operand -- the empty-label fallback never
    # matches, so it is always appended and the alert fires permanently.
    for m in re.finditer(r"\bor\b(" + _MATCH_MODIFIER + r")\s*(vector|scalar)\s*\(", expr):
        if m.group(1).strip():
            continue
        lhs = expr[_operand_start(expr, m.start()):m.start()].strip()
        if not _LABEL_FREE_LHS_RE.match(lhs):
            findings.append(
                f"`or {m.group(2)}(...)` fallback without `on()`/`ignoring()` over "
                f"a label-retaining left operand (`{lhs[:70]}`): the empty-label "
                f"fallback never matches, so it is always appended and the alert "
                f"fires permanently -- use `or on() {m.group(2)}(...)`."
            )
    return findings


def validate_alert_groups(groups: list[dict[str, Any]]) -> list[str]:
    """Return a list of human-readable structural errors (empty == valid).

    This is the guard rail: a malformed alert definition is caught here (and in
    CI/tests) instead of silently failing to deploy.
    """
    errors: list[str] = []
    seen_uids: dict[str, str] = {}

    if not isinstance(groups, list) or not groups:
        return ["'groups' must be a non-empty list"]

    for gi, group in enumerate(groups):
        where = f"group[{gi}]"
        if not isinstance(group, dict):
            errors.append(f"{where}: must be a mapping")
            continue
        name = group.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{where}: missing/empty 'name'")
        else:
            where = f"group '{name}'"
        folder = group.get("folder")
        if not isinstance(folder, str) or not folder.strip():
            errors.append(f"{where}: missing/empty 'folder'")
        try:
            parse_interval_seconds(group.get("interval"))
        except ValueError as exc:
            errors.append(f"{where}: {exc}")

        rules = group.get("rules")
        if not isinstance(rules, list) or not rules:
            errors.append(f"{where}: 'rules' must be a non-empty list")
            continue

        for ri, rule in enumerate(rules):
            rwhere = f"{where} rule[{ri}]"
            if not isinstance(rule, dict):
                errors.append(f"{rwhere}: must be a mapping")
                continue
            uid = rule.get("uid")
            title = rule.get("title")
            if isinstance(title, str) and title.strip():
                rwhere = f"{where} rule '{title}'"
            if not isinstance(uid, str) or not uid.strip():
                errors.append(f"{rwhere}: missing/empty 'uid'")
            elif uid in seen_uids:
                errors.append(
                    f"{rwhere}: duplicate uid '{uid}' (also in {seen_uids[uid]})"
                )
            else:
                seen_uids[uid] = rwhere
            if not isinstance(title, str) or not title.strip():
                errors.append(f"{rwhere}: missing/empty 'title'")
            if "for" not in rule:
                errors.append(f"{rwhere}: missing 'for' duration")
            condition = rule.get("condition")
            if not isinstance(condition, str) or not condition.strip():
                errors.append(f"{rwhere}: missing/empty 'condition'")

            data = rule.get("data")
            if not isinstance(data, list) or not data:
                errors.append(f"{rwhere}: 'data' must be a non-empty list")
                continue
            ref_ids: set[str] = set()
            for di, node in enumerate(data):
                if not isinstance(node, dict):
                    errors.append(f"{rwhere}: data[{di}] must be a mapping")
                    continue
                ref_id = node.get("refId")
                if not isinstance(ref_id, str) or not ref_id.strip():
                    errors.append(f"{rwhere}: data[{di}] missing 'refId'")
                else:
                    ref_ids.add(ref_id)
                if not isinstance(node.get("datasourceUid"), str):
                    errors.append(f"{rwhere}: data[{di}] missing 'datasourceUid'")
                model = node.get("model")
                if not isinstance(model, dict):
                    errors.append(f"{rwhere}: data[{di}] missing 'model' mapping")
                elif node.get("datasourceUid") not in (None, "__expr__"):
                    expr = model.get("expr")
                    if isinstance(expr, str) and expr.strip():
                        for finding in find_promql_gating_antipatterns(expr):
                            errors.append(
                                f"{rwhere}: data[{di}] PromQL gating anti-pattern"
                                f" -- {finding}"
                            )
            if isinstance(condition, str) and condition not in ref_ids:
                errors.append(
                    f"{rwhere}: condition '{condition}' not among data refIds "
                    f"{sorted(ref_ids)}"
                )

    return errors


# Default query time window used by Grafana for instant alert queries.
DEFAULT_RELATIVE_TIME_RANGE: dict[str, int] = {"from": 300, "to": 0}


def _threshold_expression(model: dict[str, Any]) -> str | None:
    """Return the source refId for a Grafana threshold expression node."""
    conditions = model.get("conditions")
    if not isinstance(conditions, list) or not conditions:
        return None
    first = conditions[0]
    if not isinstance(first, dict):
        return None
    query = first.get("query")
    if not isinstance(query, dict):
        return None
    params = query.get("params")
    if not isinstance(params, list) or not params:
        return None
    ref_id = params[0]
    return ref_id if isinstance(ref_id, str) and ref_id.strip() else None


def _normalize_expression_node(node: dict[str, Any]) -> dict[str, Any]:
    """Return a provisioning-API-safe copy of one alert data node."""
    out = copy.deepcopy(node)
    rtr = out.get("relativeTimeRange")
    if not isinstance(rtr, dict) or not rtr.get("from"):
        out["relativeTimeRange"] = dict(DEFAULT_RELATIVE_TIME_RANGE)

    model = out.get("model")
    if not isinstance(model, dict):
        return out
    if (
        out.get("datasourceUid") == "__expr__"
        and model.get("type") == "threshold"
        and not model.get("expression")
    ):
        expression = _threshold_expression(model)
        if expression:
            model["expression"] = expression
    return out


def _ensure_relative_time_range(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return query data with a default relativeTimeRange when missing.

    The provisioning API rejects queries whose time range is unset or zero-wide
    (``from: 0, to: 0``).  Existing exported rules use ``from: 300, to: 0``.
    """
    out: list[dict[str, Any]] = []
    for node in data:
        if not isinstance(node, dict):
            out.append(node)
            continue
        out.append(_normalize_expression_node(node))
    return out


def build_provisioned_rule(
    rule: dict[str, Any], group: dict[str, Any], folder_uid: str
) -> dict[str, Any]:
    """Translate a file-format rule into a provisioning-API ProvisionedAlertRule."""
    for_value = rule["for"]
    payload: dict[str, Any] = {
        "uid": rule["uid"],
        "title": rule["title"],
        "condition": rule["condition"],
        "data": _ensure_relative_time_range(rule["data"]),
        "for": for_value if isinstance(for_value, str) else f"{int(for_value)}s",
        "folderUID": folder_uid,
        "ruleGroup": group["name"],
        "orgID": int(group.get("orgId", DEFAULT_ORG_ID)),
        "noDataState": rule.get("noDataState", DEFAULT_NO_DATA_STATE),
        "execErrState": rule.get("execErrState", DEFAULT_EXEC_ERR_STATE),
        "isPaused": bool(rule.get("isPaused", False)),
    }
    if isinstance(rule.get("labels"), dict):
        payload["labels"] = rule["labels"]
    if isinstance(rule.get("annotations"), dict):
        payload["annotations"] = rule["annotations"]
    return payload


def build_rule_group_payload(
    group: dict[str, Any], folder_uid: str
) -> dict[str, Any]:
    """Build the AlertRuleGroup body for the rule-group provisioning endpoint."""
    return {
        "title": group["name"],
        "folderUid": folder_uid,
        "interval": parse_interval_seconds(group["interval"]),
        "rules": [
            build_provisioned_rule(rule, group, folder_uid)
            for rule in group["rules"]
        ],
    }


# --------------------------------------------------------------------------- #
# HTTP (network) — thin wrappers around urllib so tests can patch urlopen
# --------------------------------------------------------------------------- #
def _api_key() -> str:
    """Return the Grafana API token from the environment or the macOS Keychain."""
    env_value = os.environ.get(ENV_API_KEY, "").strip()
    if env_value:
        return env_value
    security_bin = shutil.which("security")
    if not security_bin:
        raise RuntimeError(
            f"{ENV_API_KEY} is not set and macOS keychain tool 'security' was not found. "
            f"Set {ENV_API_KEY} in the environment."
        )
    result = subprocess.run(  # noqa: S603
        [security_bin, "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
        capture_output=True,
        text=True,
        check=True,
    )
    token = result.stdout.strip()
    if not token:
        raise RuntimeError(
            f"empty Grafana API key (env {ENV_API_KEY} unset and keychain "
            f"'{KEYCHAIN_SERVICE}' returned nothing)"
        )
    return token


def _request(
    method: str,
    path: str,
    key: str,
    payload: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> Any:
    headers = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }
    data: bytes | None = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(
        f"{GRAFANA_URL}{path}", data=data, headers=headers, method=method
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body) if body.strip() else None


def resolve_folder_uid(name: str, key: str, *, create: bool = True) -> str:
    """Resolve a Grafana folder title to its UID, optionally creating it."""
    folders = _request("GET", "/api/folders?limit=1000", key) or []
    for folder in folders:
        if isinstance(folder, dict) and folder.get("title") == name:
            uid = folder.get("uid")
            if isinstance(uid, str) and uid:
                return uid
    if not create:
        raise RuntimeError(f"folder '{name}' not found (and --no-create-folder set)")
    created = _request("POST", "/api/folders", key, payload={"title": name})
    uid = (created or {}).get("uid")
    if not isinstance(uid, str) or not uid:
        raise RuntimeError(f"failed to create folder '{name}'")
    return uid


def upsert_group(group: dict[str, Any], key: str, *, create_folder: bool = True) -> int:
    """Upsert a single rule group. Returns the number of rules written."""
    folder_uid = resolve_folder_uid(group["folder"], key, create=create_folder)
    payload = build_rule_group_payload(group, folder_uid)
    _request(
        "PUT",
        f"/api/v1/provisioning/folder/{folder_uid}/rule-groups/{group['name']}",
        key,
        payload=payload,
        # Keep rules editable in the UI instead of locking them as provisioned.
        extra_headers={"X-Disable-Provenance": "true"},
    )
    return len(payload["rules"])


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path", type=Path, default=ALERT_RULES_PATH, help="alert-rules.yaml path"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate the rules and exit without contacting Grafana",
    )
    parser.add_argument(
        "--no-create-folder",
        action="store_true",
        help="fail instead of creating a missing Grafana folder",
    )
    args = parser.parse_args(argv)

    if not args.path.exists():
        print(f"Alert rules file not found: {args.path}", file=sys.stderr)
        return 1

    try:
        groups = load_alert_groups(args.path)
    except Exception as exc:
        print(f"Failed to load {args.path}: {exc}", file=sys.stderr)
        return 1

    errors = validate_alert_groups(groups)
    if errors:
        print(f"Alert rules validation failed ({len(errors)} issue(s)):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    rule_count = sum(len(g["rules"]) for g in groups)
    print(f"Validated {len(groups)} group(s), {rule_count} rule(s).")

    if args.dry_run:
        print("--dry-run: not contacting Grafana.")
        return 0

    try:
        key = _api_key()
        for group in groups:
            written = upsert_group(
                group, key, create_folder=not args.no_create_folder
            )
            print(
                f"Upserted group '{group['name']}' "
                f"({written} rule(s)) in folder '{group['folder']}'."
            )
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read().decode('utf-8')}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Alert rules upsert failed: {exc}", file=sys.stderr)
        return 1

    print("Alert rules upsert complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
