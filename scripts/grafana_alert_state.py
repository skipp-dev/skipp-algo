"""Read-only Grafana alert-state reader — the missing half of the upsert flow.

``grafana_alert_rules_upsert.py`` provisions rules (repo -> Grafana) but until
now nothing could READ the live firing state back, so "is anything firing?"
required opening the UI. This tool answers it from the terminal:

* active alert instances (Alertmanager ``/api/alertmanager/grafana/api/v2/alerts``)
* per-rule evaluation state (``/api/prometheus/grafana/api/v1/rules``), where
  ``health=error`` (unevaluable rule) is surfaced in the active view too — an
  unevaluable rule is operationally worse than a firing one.

Auth & HTTP are **reused** from ``scripts.grafana_alert_rules_upsert``
(``GRAFANA_API_KEY`` env for CI, macOS Keychain ``skipp.grafana.api`` locally;
Bearer + urllib with the ledger-pinned call sites) — this module adds no new
network or subprocess call sites of its own. Strictly read-only: GET requests
only. The token is never printed.

Usage (module form — the upsert import needs the repo root on sys.path)::

    python -m scripts.grafana_alert_state              # firing/pending/unhealthy + instances
    python -m scripts.grafana_alert_state --all        # include inactive rules
    python -m scripts.grafana_alert_state --rule vix   # filter rules by substring
    python -m scripts.grafana_alert_state --json       # machine-readable
    python -m scripts.grafana_alert_state --fail-on-firing  # exit 1 if anything fires
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

try:
    from scripts.grafana_alert_rules_upsert import _api_key, _request
except ImportError as exc:  # pragma: no cover - invocation-style guard
    raise SystemExit(
        "run as `python -m scripts.grafana_alert_state` from the repo root "
        f"(the upsert helpers must be importable): {exc}"
    ) from exc

_SEVERITY_ORDER = {"critical": 0, "high": 1, "warning": 2, "info": 3}


def summarize_active_alerts(alerts: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Flatten Alertmanager v2 alert instances, most severe first."""
    rows = []
    for alert in alerts:
        labels = alert.get("labels", {}) or {}
        rows.append(
            {
                "alertname": str(labels.get("alertname", "?")),
                "severity": str(labels.get("severity") or "-"),
                "state": str((alert.get("status", {}) or {}).get("state", "?")),
                "startsAt": str(alert.get("startsAt", ""))[:19],
            }
        )
    rows.sort(key=lambda r: (_SEVERITY_ORDER.get(r["severity"], 9), r["alertname"]))
    return rows


def summarize_rule_states(
    payload: dict[str, Any],
    *,
    only_active: bool = False,
    name_filter: str | None = None,
) -> list[dict[str, str]]:
    """Flatten the Prometheus rules API to per-alerting-rule state rows.

    ``only_active`` keeps firing/pending rules AND any rule with
    ``health != ok`` — an unevaluable rule must never disappear from the
    operational view just because it cannot reach the firing state.
    """
    data = payload.get("data")
    if not isinstance(data, dict) or "groups" not in data:  # 2026-08-15: Schema-Drift darf nie als "alles gesund" lesen
        raise ValueError(
            "Grafana rules API carries no data.groups -- schema drift or an "
            f"empty body; refusing to report 'no rules' (got: {str(payload)[:200]!r})"
        )
    rows = []
    for group in data["groups"] or []:
        for rule in group.get("rules", []) or []:
            if rule.get("type") == "recording":
                continue
            name = str(rule.get("name", "?"))
            state = str(rule.get("state", "?"))
            health = str(rule.get("health", "?"))
            if name_filter and name_filter.lower() not in name.lower():
                continue
            if only_active and state == "inactive" and health == "ok":
                continue
            rows.append({"name": name, "state": state, "health": health, "group": str(group.get("name", ""))})
    rows.sort(key=lambda r: (r["state"] != "firing", r["health"] == "ok", r["name"]))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true", help="include inactive+healthy rules")
    parser.add_argument("--rule", default=None, metavar="SUBSTR", help="filter rules by name substring")
    parser.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    parser.add_argument(
        "--fail-on-firing", action="store_true",
        help="exit 1 when any instance is active or any rule fires/is unhealthy (for scripts/CI)",
    )
    args = parser.parse_args(argv)

    key = _api_key()
    # `or []`/`or {}` hiess: ein leerer 200-Body (Proxy, Auth-Redirect,
    # API-Umbau) las als "0 Alerts, 0 Regeln" -- fuer das Werkzeug des
    # Sitzungsstart-Betriebschecks ist das die gefaehrlichste aller
    # Antworten. None ist jetzt laut; die ehrliche Ruhe ist eine
    # VORHANDENE leere Liste vom API.
    alerts_payload = _request("GET", "/api/alertmanager/grafana/api/v2/alerts", key)
    rules_payload = _request("GET", "/api/prometheus/grafana/api/v1/rules", key)
    if alerts_payload is None or rules_payload is None:
        print(
            "ERROR: Grafana returned an empty body "
            f"(alerts={'ok' if alerts_payload is not None else 'EMPTY'}, "
            f"rules={'ok' if rules_payload is not None else 'EMPTY'}) -- "
            "refusing to report 'all healthy' on a reading that never happened.",
            file=sys.stderr,
        )
        return 2
    instances = summarize_active_alerts(alerts_payload)
    try:
        rules = summarize_rule_states(
            rules_payload,
            only_active=not args.all,
            name_filter=args.rule,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps({"active_instances": instances, "rules": rules}, indent=2))
    else:
        print(f"Active alert instances: {len(instances)}")
        for r in instances:
            print(f"  [{r['state']}] {r['alertname']} (sev={r['severity']}) since {r['startsAt']}")
        label = "all rules" if args.all else "firing/pending/unhealthy rules"
        print(f"{label.capitalize()}: {len(rules)}")
        for r in rules:
            print(f"  [{r['state']:8}] {r['name']} (health={r['health']})")

    if args.fail_on_firing and (instances or any(r["state"] != "inactive" or r["health"] != "ok" for r in rules)):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
