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
rules deleted from the repo). The result is a 1:1 reproducible deploy of the
groups defined in ``alert-rules.yaml``.

Groups *removed* from the YAML are not deleted from Grafana automatically: the
per-group PUT cannot see groups it is not given. Pass ``--prune`` to delete live
rule groups (in the folders this file manages) that are absent from the YAML;
without it, such orphans are reported as warnings so drift is at least visible.

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

    # Duplicate mapping keys are silent data loss with PyYAML (last key wins:
    # a duplicated ``annotations:`` above the real one is tolerated, reordered
    # it silently nulls summary/runbook) and a hard parse error with go-yaml
    # (Grafana file provisioning). Reject them at load time so the drift can
    # never reach the API.
    class _DupKeyLoader(yaml.SafeLoader):
        pass

    def _construct_no_dup_mapping(
        loader: yaml.SafeLoader, node: Any, deep: bool = False
    ) -> dict[Any, Any]:
        keys = [loader.construct_object(key_node, deep=deep) for key_node, _ in node.value]
        seen: set[Any] = set()
        for key in keys:
            if key in seen:
                raise ValueError(
                    f"{path}: duplicate YAML mapping key {key!r} near line "
                    f"{node.start_mark.line + 1} — PyYAML silently keeps only "
                    "the last value and go-yaml (Grafana provisioning) rejects "
                    "the document"
                )
            seen.add(key)
        return yaml.SafeLoader.construct_mapping(loader, node, deep)

    _DupKeyLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_no_dup_mapping
    )

    # Use the low-level loader API directly (what yaml.load does internally)
    # so no `yaml.load(...)` call site exists — _DupKeyLoader is SafeLoader-
    # based, so this stays safe while keeping the duplicate-key rejection.
    _loader = _DupKeyLoader(path.read_text(encoding="utf-8"))
    try:
        document = _loader.get_single_data()
    finally:
        _loader.dispose()
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


# Grafana rejects an alert rule whose uid exceeds this with HTTP 400
# ("UID is longer than 40 symbols"). Enforced here rather than only at the API
# because the upsert applies group-by-group: one over-long uid 400s its group
# and strands every LATER group unapplied, leaving alerting in a partial-apply
# mixed state. #3510 landed a 41-char uid on 2026-07-13 and every publish run
# failed that way until 2026-07-15 -- two days in which no alert-rule change
# reached Grafana. Validation runs before the first POST, so catching it here
# turns a silent half-deploy into a loud pre-flight failure.
MAX_UID_LENGTH = 40

# The portable uid subset this repo commits to: lowercase ASCII words joined by
# single ASCII hyphens. This is a REPO-LOCAL contract, deliberately narrower than
# whatever Grafana would accept -- it is not a claim about Grafana's own charset
# rules, which are not documented in the error surface we have observed.
#
# It exists because MAX_UID_LENGTH alone cannot see the likelier typo. A uid that
# swaps the ASCII hyphen for a typographic en-dash (U+2013) is the SAME length,
# renders almost identically in a review diff, and passes every check above:
#   lo-credential-monitor-stale   (27 chars, ASCII)
#   lo-credential-monitor-stale   (27 chars, en-dash -- a different string)
# The uniqueness check cannot help either, since the two are distinct strings. So
# Grafana either 400s on a rule that looks correct, or -- worse -- accepts it as a
# SEPARATE rule, leaving the hyphenated original orphaned and firing forever while
# CI and the publish run both stay green. That is the same "the rule exists but
# nobody notices" class the uid-length guard was added for.
#
# The mechanism is not hypothetical here: this repo's alert YAML is authored by
# agents and pasted between rendered Markdown, Slack and Outlook, all of which
# autocorrect hyphens. Pinning the subset also keeps len() an unambiguous stand-in
# for Grafana's "symbols" count, which only coincides for ASCII.
#
# fullmatch (not match): `$` would also accept a trailing newline.
UID_CHARSET_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
# Per-character set, used only to name the offending characters in the error.
# UID_CHARSET_RE cannot do that job: it requires a leading alphanumeric, so a
# legitimate '-' would fullmatch as False and be reported as an offender.
UID_CHAR_RE = re.compile(r"[a-z0-9-]")


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
            elif len(uid) > MAX_UID_LENGTH:
                errors.append(
                    f"{rwhere}: uid '{uid}' is {len(uid)} chars; Grafana rejects "
                    f"uids longer than {MAX_UID_LENGTH} with HTTP 400"
                )
            elif not UID_CHARSET_RE.fullmatch(uid):
                offenders = sorted({c for c in uid if not UID_CHAR_RE.fullmatch(c)})
                errors.append(
                    f"{rwhere}: uid '{uid}' leaves the portable subset "
                    f"[a-z0-9] joined by '-' (offending: {offenders}). A "
                    f"look-alike character (en-dash for hyphen, NBSP for space) "
                    f"passes the length and uniqueness checks and reaches Grafana."
                )
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
                        if " and on(" in expr and "noDataState" not in rule:
                            errors.append(
                                f"{rwhere}: rule '{uid}': gated expr can evaluate "
                                "to empty -- declare noDataState explicitly "
                                "(OK for stand-down gates)"
                            )
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


def live_groups_by_folder(key: str) -> dict[str, set[str]]:
    """Return live provisioned rule-group names keyed by folder UID.

    Reads all provisioned alert rules (``GET /api/v1/provisioning/alert-rules``)
    and buckets their ``ruleGroup`` by ``folderUID`` so orphan groups (present
    in Grafana but absent from the YAML) can be detected.
    """
    rules = _request("GET", "/api/v1/provisioning/alert-rules", key) or []
    out: dict[str, set[str]] = {}
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        folder_uid = str(rule.get("folderUID") or "")
        group = str(rule.get("ruleGroup") or "")
        if folder_uid and group:
            out.setdefault(folder_uid, set()).add(group)
    return out


def delete_rule_group(folder_uid: str, group: str, key: str) -> None:
    """Delete a provisioned rule group (destructive; only via --prune)."""
    _request(
        "DELETE",
        f"/api/v1/provisioning/folder/{folder_uid}/rule-groups/{group}",
        key,
        extra_headers={"X-Disable-Provenance": "true"},
    )


def reconcile_orphan_groups(
    groups: list[dict[str, Any]], key: str, *, prune: bool = False
) -> list[str]:
    """Report (and optionally prune) live groups absent from the YAML.

    Only folders that appear in the YAML are inspected, so groups in unrelated
    folders are never touched. Returns the list of orphan ``folder/group``
    labels found (pruned or warned).
    """
    # desired[folder_uid] = {group names from YAML}
    desired: dict[str, set[str]] = {}
    folder_titles: dict[str, str] = {}
    for group in groups:
        folder_uid = resolve_folder_uid(group["folder"], key, create=False)
        desired.setdefault(folder_uid, set()).add(group["name"])
        folder_titles[folder_uid] = group["folder"]

    live = live_groups_by_folder(key)
    orphans: list[str] = []
    for folder_uid, desired_groups in desired.items():
        for live_name in sorted(live.get(folder_uid, set()) - desired_groups):
            label = f"{folder_titles.get(folder_uid, folder_uid)}/{live_name}"
            orphans.append(label)
            if prune:
                delete_rule_group(folder_uid, live_name, key)
                print(f"pruned orphan group: {label}")
            else:
                print(f"WARNING: orphan live group not in YAML: {label}", file=sys.stderr)
    return orphans


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
    parser.add_argument(
        "--prune",
        action="store_true",
        help="delete live rule groups (in managed folders) absent from the YAML "
        "(default: only warn about orphans)",
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

    # Bind before the try so the PARTIAL-APPLY diagnostic in the except blocks
    # is safe even when _api_key() raises before the upsert loop starts.
    total = len(groups)
    applied = 0
    try:
        key = _api_key()
        for group in groups:
            written = upsert_group(
                group, key, create_folder=not args.no_create_folder
            )
            applied += 1
            print(
                f"Upserted group '{group['name']}' "
                f"({written} rule(s)) in folder '{group['folder']}'."
            )
        reconcile_orphan_groups(groups, key, prune=args.prune)
    except urllib.error.HTTPError as exc:
        print(
            f"PARTIAL APPLY: {applied}/{total} groups updated — alerting is in a "
            f"mixed state; re-run to converge.", file=sys.stderr,
        )
        print(f"HTTP {exc.code}: {exc.read().decode('utf-8')}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(
            f"PARTIAL APPLY: {applied}/{total} groups updated — alerting is in a "
            f"mixed state; re-run to converge.", file=sys.stderr,
        )
        print(f"Alert rules upsert failed: {exc}", file=sys.stderr)
        return 1

    print("Alert rules upsert complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
