#!/usr/bin/env python3
"""Upsert the SMC Live Overlay Grafana notification routing from the repo.

Source of truth
---------------
``services/live_overlay_daemon/infra/grafana/notification-routing.yaml`` — the
declarative contact points + notification-policy tree (companion to
``alert-rules.yaml``). This is the "how alerts reach humans" half of alerting;
``grafana_alert_rules_upsert.py`` is the "which conditions alert" half.

Why this script exists
----------------------
Contact points and the notification policy were previously configured live-only
in the Grafana UI, so a Grafana rebuild (or a fresh stack) would silently drop
every route and alerts would deliver nowhere — which is exactly the state this
file was born from (0 contact points, root receiver ``empty``, 2026-07-11). This
makes routing reproducible and reviewable like the alert rules already are.

What it does
------------
* upserts every contact point via the provisioning API (idempotent create/update
  by name): ``POST``/``PUT /api/v1/provisioning/contact-points``;
* replaces the notification policy tree: ``PUT /api/v1/provisioning/policies``.

Both use ``X-Disable-Provenance: true`` so the objects stay UI-editable instead
of being locked as provisioned (mirrors the alert-rules upsert).

Secrets
-------
The Slack webhook is NEVER committed. ``${SLACK_WEBHOOK_URL}`` placeholders in
the YAML are substituted from the environment at apply time. ``--dry-run``
validates structure without the webhook and without any network call.

Auth
----
Reuses ``grafana_alert_rules_upsert`` for the Grafana base URL and token
(``GRAFANA_API_KEY`` env or macOS keychain ``skipp.grafana.api``) and the thin
``urllib`` request wrapper, so there is one auth path for all Grafana upserts.

Usage
-----
Run from the repository root::

    python scripts/grafana_notification_routing_upsert.py            # apply
    python scripts/grafana_notification_routing_upsert.py --dry-run  # validate only
"""

from __future__ import annotations

import argparse
import copy
import os
import re
import sys
import urllib.error
from pathlib import Path
from typing import Any

# Bootstrap the repo root onto sys.path so `from scripts.…` resolves under the
# direct-path invocation `python scripts/X.py` (the form the deploy workflow
# uses), not only `python -m scripts.X`. Must precede the first-party import
# below — pinned by tests/test_workflow_invoked_scripts_import_order.py; E402 is
# ignored for scripts/* in pyproject. Registered in the sys.path mutation ledger
# (tests/test_sys_path_mutation_ledger.py).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# One auth path for every Grafana upsert: reuse the token + HTTP helpers instead
# of duplicating the keychain/urllib plumbing.
from scripts.grafana_alert_rules_upsert import _api_key, _request

ROUTING_PATH = Path(
    "services/live_overlay_daemon/infra/grafana/notification-routing.yaml"
)
PROVENANCE_HEADER = {"X-Disable-Provenance": "true"}
# ${VAR} placeholders resolved from the environment at apply time.
_PLACEHOLDER_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")
_VALID_MATCHER_OPS = {"=", "!=", "=~", "!~"}


# --------------------------------------------------------------------------- #
# Parsing / validation (pure, unit-testable, no network)
# --------------------------------------------------------------------------- #
def load_routing(path: Path) -> dict[str, Any]:
    """Load the routing document (contact points + policy) from YAML."""
    import yaml  # local import: keeps --help working without PyYAML installed

    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path}: top-level YAML must be a mapping")
    return document


def find_placeholders(obj: Any) -> set[str]:
    """Return every ``${VAR}`` env-placeholder name referenced anywhere in obj."""
    found: set[str] = set()
    if isinstance(obj, str):
        found.update(_PLACEHOLDER_RE.findall(obj))
    elif isinstance(obj, dict):
        for value in obj.values():
            found |= find_placeholders(value)
    elif isinstance(obj, list):
        for item in obj:
            found |= find_placeholders(item)
    return found


def resolve_placeholders(obj: Any, env: dict[str, str]) -> Any:
    """Return a copy of obj with every ``${VAR}`` substituted from env.

    Raises ``KeyError`` (via a clear ValueError) if a referenced variable is
    unset, so a missing secret fails loudly instead of shipping the literal
    ``${SLACK_WEBHOOK_URL}`` to Grafana.
    """
    if isinstance(obj, str):
        def _sub(match: re.Match[str]) -> str:
            name = match.group(1)
            value = env.get(name)
            if value is None or value == "":
                raise ValueError(
                    f"environment variable {name} referenced by the routing "
                    f"config is unset/empty"
                )
            return value

        return _PLACEHOLDER_RE.sub(_sub, obj)
    if isinstance(obj, dict):
        return {k: resolve_placeholders(v, env) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_placeholders(v, env) for v in obj]
    return obj


def validate_routing(doc: dict[str, Any]) -> list[str]:
    """Return a list of human-readable structural errors (empty == valid)."""
    errors: list[str] = []

    contact_points = doc.get("contactPoints")
    names: set[str] = set()
    if not isinstance(contact_points, list) or not contact_points:
        errors.append("'contactPoints' must be a non-empty list")
        contact_points = []
    for i, cp in enumerate(contact_points):
        where = f"contactPoints[{i}]"
        if not isinstance(cp, dict):
            errors.append(f"{where}: must be a mapping")
            continue
        name = cp.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{where}: missing/empty 'name'")
        else:
            where = f"contact point '{name}'"
            if name in names:
                errors.append(f"{where}: duplicate name")
            names.add(name)
        if not isinstance(cp.get("type"), str) or not cp.get("type", "").strip():
            errors.append(f"{where}: missing/empty 'type'")
        if not isinstance(cp.get("settings"), dict) or not cp.get("settings"):
            errors.append(f"{where}: 'settings' must be a non-empty mapping")

    policy = doc.get("policy")
    if not isinstance(policy, dict) or not policy:
        errors.append("'policy' must be a non-empty mapping")
        return errors

    root_receiver = policy.get("receiver")
    if not isinstance(root_receiver, str) or not root_receiver.strip():
        errors.append("policy: missing/empty root 'receiver'")
    elif names and root_receiver not in names:
        errors.append(
            f"policy: root receiver '{root_receiver}' is not a defined contact point"
        )

    group_by = policy.get("group_by")
    if group_by is not None and not (
        isinstance(group_by, list) and all(isinstance(g, str) for g in group_by)
    ):
        errors.append("policy: 'group_by' must be a list of strings")

    routes = policy.get("routes", [])
    if routes and not isinstance(routes, list):
        errors.append("policy: 'routes' must be a list")
        routes = []
    for ri, route in enumerate(routes):
        rwhere = f"policy.routes[{ri}]"
        if not isinstance(route, dict):
            errors.append(f"{rwhere}: must be a mapping")
            continue
        receiver = route.get("receiver")
        if not isinstance(receiver, str) or not receiver.strip():
            errors.append(f"{rwhere}: missing/empty 'receiver'")
        elif names and receiver not in names:
            errors.append(
                f"{rwhere}: receiver '{receiver}' is not a defined contact point"
            )
        matchers = route.get("object_matchers")
        if not isinstance(matchers, list) or not matchers:
            errors.append(f"{rwhere}: 'object_matchers' must be a non-empty list")
            continue
        for mi, matcher in enumerate(matchers):
            if not (isinstance(matcher, list) and len(matcher) == 3):
                errors.append(
                    f"{rwhere}: object_matchers[{mi}] must be [label, op, value]"
                )
                continue
            label, op, value = matcher
            if not (isinstance(label, str) and label.strip()):
                errors.append(f"{rwhere}: object_matchers[{mi}] label must be a string")
            if op not in _VALID_MATCHER_OPS:
                errors.append(
                    f"{rwhere}: object_matchers[{mi}] op '{op}' not in "
                    f"{sorted(_VALID_MATCHER_OPS)}"
                )
            if not isinstance(value, str):
                errors.append(f"{rwhere}: object_matchers[{mi}] value must be a string")

    return errors


def build_contact_point_body(cp: dict[str, Any]) -> dict[str, Any]:
    """Return a provisioning-API embedded-contact-point body."""
    body: dict[str, Any] = {
        "name": cp["name"],
        "type": cp["type"],
        "settings": copy.deepcopy(cp.get("settings", {})),
        "disableResolveMessage": bool(cp.get("disableResolveMessage", False)),
    }
    return body


def build_policy_body(policy: dict[str, Any]) -> dict[str, Any]:
    """Return the provisioning-API notification-policy (Route) body."""
    body: dict[str, Any] = {"receiver": policy["receiver"]}
    if isinstance(policy.get("group_by"), list):
        body["group_by"] = list(policy["group_by"])
    routes = []
    for route in policy.get("routes", []) or []:
        out: dict[str, Any] = {
            "receiver": route["receiver"],
            "object_matchers": [list(m) for m in route.get("object_matchers", [])],
            "continue": bool(route.get("continue", False)),
        }
        # 2026-08-30: pro Route durchgereicht, vorher STILL VERWORFEN.
        #
        # Bis hierher baute diese Funktion jede Route aus genau drei Feldern.
        # `group_by`, `group_wait`, `group_interval` und `repeat_interval`
        # standen in der YAML, wurden von den Tests gepinnt — und kamen bei
        # Grafana nie an. Aufgefallen ist es erst beim Nachlesen des LIVE-
        # Zustands nach dem Merge von #5202: Route vorhanden, Matcher richtig,
        # `group_by=None repeat=None`. Die Datei sagte das eine, die Instanz das
        # andere, und kein Test konnte den Unterschied sehen, weil alle die Datei
        # lesen.
        for feld in ("group_by", "group_wait", "group_interval", "repeat_interval"):
            wert = route.get(feld)
            if wert is not None:
                out[feld] = list(wert) if feld == "group_by" else wert
        routes.append(out)
    if routes:
        body["routes"] = routes
    return body


# --------------------------------------------------------------------------- #
# HTTP (network) — auth + request plumbing reused from grafana_alert_rules_upsert
# --------------------------------------------------------------------------- #
def upsert_contact_point(cp_body: dict[str, Any], key: str) -> str:
    """Create or update a contact point by name. Returns 'create' or 'update'."""
    existing_list = _request("GET", "/api/v1/provisioning/contact-points", key) or []
    existing = next(
        (c for c in existing_list if isinstance(c, dict) and c.get("name") == cp_body["name"]),
        None,
    )
    if existing and existing.get("uid"):
        _request(
            "PUT",
            f"/api/v1/provisioning/contact-points/{existing['uid']}",
            key,
            payload={**cp_body, "uid": existing["uid"]},
            extra_headers=PROVENANCE_HEADER,
        )
        return "update"
    _request(
        "POST",
        "/api/v1/provisioning/contact-points",
        key,
        payload=cp_body,
        extra_headers=PROVENANCE_HEADER,
    )
    return "create"


def policy_drift(gesendet: dict[str, Any], gelesen: Any) -> list[str]:
    """Welche Routen-Felder kamen NICHT so an, wie sie gesendet wurden?

    Reine Funktion, damit die Zusicherung testbar ist, ohne Grafana zu
    brauchen. Verglichen wird Route fuer Route in derselben Reihenfolge — die
    Reihenfolge IST Teil der Zusicherung, weil `continue: false` die erste
    passende Route gewinnen laesst.
    """
    if not isinstance(gelesen, dict):
        return [f"Ruecklese lieferte {type(gelesen).__name__}, kein Objekt"]
    a = gesendet.get("routes") or []
    b = gelesen.get("routes") or []
    if len(a) != len(b):
        return [f"Routenzahl: gesendet {len(a)}, gelesen {len(b)}"]
    abweichungen = []
    for i, (soll, ist) in enumerate(zip(a, b)):
        for feld in ("receiver", "object_matchers", "group_by", "group_wait",
                     "group_interval", "repeat_interval"):
            s, g = soll.get(feld), ist.get(feld)
            if s is None and g is None:
                continue
            if feld == "object_matchers":
                s = [list(m) for m in (s or [])]
                g = [list(m) for m in (g or [])]
            if s != g:
                abweichungen.append(f"routes[{i}].{feld}: gesendet {s!r}, gelesen {g!r}")
    return abweichungen


def put_policy(policy_body: dict[str, Any], key: str) -> None:
    """Replace the notification policy tree — und lies zurueck, was ankam.

    Die Ruecklese ist kein Luxus. Bis 2026-08-30 verwarf `build_policy_body`
    vier Routen-Felder still; die YAML, die Tests und die Absicht sagten das
    eine, die Instanz das andere. Ein Upsert, der nur sendet, kann diese Klasse
    strukturell nicht sehen — er hat ja alles getan, was er kennt.
    """
    _request(
        "PUT",
        "/api/v1/provisioning/policies",
        key,
        payload=policy_body,
        extra_headers=PROVENANCE_HEADER,
    )
    gelesen = _request("GET", "/api/v1/provisioning/policies", key)
    drift = policy_drift(policy_body, gelesen)
    if drift:
        raise RuntimeError(
            "Die Policy kam anders an, als sie gesendet wurde — deklariert ist "
            "nicht ausgeliefert:\n  " + "\n  ".join(drift)
        )
    # Die geglueckte Ruecklese wird AUSGESPROCHEN, nicht stillschweigend
    # vorausgesetzt. Ohne diese Zeile ist "Ruecklese hat stattgefunden" von
    # "Ruecklese wurde wegoptimiert" im Lauf nicht zu unterscheiden — und der
    # Beweis-Eintrag haette keine Versionsprobe.
    print(
        f"policy-readback: {len(policy_body.get('routes') or [])} Route(n) "
        "unveraendert angekommen"
    )


def _mask_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Redact URL/token/secret-ish contact-point settings for logging."""
    masked = {}
    for k, v in settings.items():
        if isinstance(v, str) and re.search(r"url|token|secret|password", k, re.I):
            masked[k] = f"<redacted:{len(v)}chars>" if v else v
        else:
            masked[k] = v
    return masked


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=ROUTING_PATH,
                        help="notification-routing.yaml path")
    parser.add_argument("--dry-run", action="store_true",
                        help="validate structure and exit without contacting Grafana")
    args = parser.parse_args(argv)

    if not args.path.exists():
        print(f"Routing file not found: {args.path}", file=sys.stderr)
        return 1

    try:
        doc = load_routing(args.path)
    except Exception as exc:
        print(f"Failed to load {args.path}: {exc}", file=sys.stderr)
        return 1

    errors = validate_routing(doc)
    if errors:
        print(f"Routing validation failed ({len(errors)} issue(s)):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    contact_points = doc["contactPoints"]
    referenced = sorted(find_placeholders(doc))
    print(f"Validated {len(contact_points)} contact point(s), 1 policy tree.")
    if referenced:
        print(f"Env placeholders referenced: {', '.join(referenced)}")

    if args.dry_run:
        # Structure is valid; report the plan without resolving the secret.
        for cp in contact_points:
            print(f"  contact-point '{cp['name']}' (type={cp['type']}, "
                  f"settings={_mask_settings(cp.get('settings', {}))})")
        pol = build_policy_body(doc["policy"])
        print(f"  policy: root.receiver={pol['receiver']} "
              f"routes={[r['object_matchers'] for r in pol.get('routes', [])]}")
        print("--dry-run: not contacting Grafana.")
        return 0

    # Resolve ${VAR} placeholders (e.g. SLACK_WEBHOOK_URL) — fail loudly if unset.
    try:
        resolved = resolve_placeholders(doc, dict(os.environ))
    except ValueError as exc:
        print(f"Placeholder resolution failed: {exc}", file=sys.stderr)
        return 1

    try:
        key = _api_key()
        # Contact points first: the policy references them by name.
        for cp in resolved["contactPoints"]:
            action = upsert_contact_point(build_contact_point_body(cp), key)
            print(f"Contact point '{cp['name']}' {action}d "
                  f"(type={cp['type']}, settings={_mask_settings(cp.get('settings', {}))}).")
        put_policy(build_policy_body(resolved["policy"]), key)
        pol = build_policy_body(resolved["policy"])
        print(f"Notification policy set: root.receiver={pol['receiver']}, "
              f"{len(pol.get('routes', []))} route(s).")
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read().decode('utf-8')}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, RuntimeError) as exc:
        print(f"Routing upsert failed: {exc}", file=sys.stderr)
        return 1

    print("Notification routing upsert complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
