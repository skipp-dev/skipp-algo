#!/usr/bin/env python3
"""Publish the live-overlay Grafana dashboard from repo to Grafana Cloud.

The dashboard is stored in the repo in the classic Grafana model (top-level
``panels`` / ``schemaVersion``). It is published through the Grafana App
Platform API surface (Kubernetes-style), which carries that classic model
unchanged inside ``spec`` (see ADR-0025):

    GET  /apis/dashboard.grafana.app/v1/namespaces/<ns>/dashboards/<uid>
    POST /apis/dashboard.grafana.app/v1/namespaces/<ns>/dashboards         # create
    PUT  /apis/dashboard.grafana.app/v1/namespaces/<ns>/dashboards/<uid>   # update

The existing ``resourceVersion`` is read before an update and echoed back so
concurrent UI edits surface as HTTP 409 instead of being silently overwritten.
Stacks without the App Platform API fall back to legacy POST /api/dashboards/db.
The namespace is ``default`` on-prem; Grafana Cloud uses ``stacks-<stackId>``
(override with ``--namespace``).

Authentication uses CLI/env first and falls back to the macOS keychain entry
``skipp.grafana.api`` by default.

Resolution order:
1) ``--token``
2) ``$<--token-env>`` (default: ``GRAFANA_API_TOKEN``)
3) ``$GRAFANA_API_TOKEN`` (only if ``--token-env`` points to a different var)
4) ``$GRAFANA_TOKEN``
5) Keychain (unless ``--no-keychain`` is set)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_DASHBOARD_PATH = Path("services/live_overlay_daemon/infra/grafana/dashboard.json")
DEFAULT_HOST = "bronzeporridge977.grafana.net"
DEFAULT_KEYCHAIN_SERVICE = "skipp.grafana.api"
DEFAULT_TOKEN_ENV = "GRAFANA_API_TOKEN"
DEFAULT_NAMESPACE = "default"
DEFAULT_FOLDER_UID = "cfpozahbhfzswc"


def _is_v2_dashboard(data: dict[str, Any]) -> bool:
    return data.get("kind") == "Dashboard" and isinstance(data.get("spec"), dict)


def _is_legacy_dashboard(data: dict[str, Any]) -> bool:
    return isinstance(data.get("panels"), list)


def _resolve_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish the live-overlay Grafana dashboard to Grafana Cloud."
    )
    parser.add_argument(
        "dashboard_path",
        nargs="?",
        type=Path,
        default=DEFAULT_DASHBOARD_PATH,
        help="Path to dashboard.json",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="Grafana Cloud host")
    parser.add_argument(
        "--namespace",
        default=DEFAULT_NAMESPACE,
        help="App Platform namespace ('default' on-prem; 'stacks-<stackId>' on Grafana Cloud)",
    )
    parser.add_argument(
        "--folder",
        default=DEFAULT_FOLDER_UID,
        help="Grafana folder uid stored as the grafana.app/folder annotation (empty to omit)",
    )
    parser.add_argument("--token", default=None, help="Grafana API token (Bearer)")
    parser.add_argument(
        "--token-env",
        default=DEFAULT_TOKEN_ENV,
        help=(
            "Primary env var to read token from "
            f"(default: {DEFAULT_TOKEN_ENV}; also falls back to GRAFANA_TOKEN)"
        ),
    )
    parser.add_argument(
        "--keychain-service",
        default=DEFAULT_KEYCHAIN_SERVICE,
        help="macOS keychain service name to read the token from",
    )
    parser.add_argument(
        "--no-keychain",
        action="store_true",
        help="Disable keychain lookup (recommended in CI/non-macOS runners; provide token via --token or env vars)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate without sending; prints a compact summary",
    )
    parser.add_argument(
        "--dry-run-full",
        action="store_true",
        help="With --dry-run, also print the full JSON payload",
    )
    parser.add_argument(
        "--message",
        default="sync from repo",
        help="Change message stored in Grafana",
    )
    return parser.parse_args(argv)


def _load_dashboard(dashboard_path: Path) -> dict[str, Any]:
    if not dashboard_path.exists():
        raise SystemExit(f"Dashboard not found: {dashboard_path}")
    data = json.loads(dashboard_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("Dashboard JSON must be a JSON object")

    if _is_v2_dashboard(data):
        return data
    if _is_legacy_dashboard(data):
        return data

    raise SystemExit(
        "Dashboard JSON must be either Grafana v2/Kubernetes shape "
        "(kind='Dashboard' + spec) or legacy Grafana v1 shape "
        "(top-level panels)."
    )


def _get_token(
    token: str | None,
    keychain_service: str,
    token_env: str,
    *,
    no_keychain: bool = False,
) -> str:
    if token:
        return token

    env_candidates = [token_env]
    if token_env != DEFAULT_TOKEN_ENV:
        env_candidates.append(DEFAULT_TOKEN_ENV)
    env_candidates.append("GRAFANA_TOKEN")

    seen: set[str] = set()
    for name in env_candidates:
        if not name or name in seen:
            continue
        seen.add(name)
        value = os.environ.get(name, "").strip()
        if value:
            return value

    if no_keychain:
        raise SystemExit(
            "Could not obtain Grafana API token: keychain lookup disabled. "
            f"Set ${token_env}, ${DEFAULT_TOKEN_ENV}, or $GRAFANA_TOKEN, or pass --token."
        )

    security_bin = shutil.which("security")
    if not security_bin:
        raise SystemExit(
            "Could not obtain Grafana API token: 'security' CLI not found in PATH. "
            f"Set ${token_env}, ${DEFAULT_TOKEN_ENV}, or $GRAFANA_TOKEN, pass --token, or run with --no-keychain in CI/non-macOS environments."
        )

    try:
        result = subprocess.run(  # noqa: S603
            [security_bin, "find-generic-password", "-s", keychain_service, "-a", os.environ.get("USER", ""), "-w"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        keychain_token = result.stdout.strip()
        if keychain_token:
            return keychain_token
        raise SystemExit(
            "Keychain lookup returned an empty token. "
            f"Set ${token_env}, ${DEFAULT_TOKEN_ENV}, or $GRAFANA_TOKEN, or pass --token."
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise SystemExit(
            "Could not obtain Grafana API token. "
            f"Set ${token_env}, ${DEFAULT_TOKEN_ENV}, or $GRAFANA_TOKEN, use --token, or run with --no-keychain in CI/non-macOS environments, "
            "or add a keychain entry for "
            f"service '{keychain_service}'. ({exc})"
        ) from exc


def _extract_spec_and_uid(data: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Return ``(spec, uid)`` for both classic and App Platform inputs.

    Option B keeps the classic dashboard model (top-level ``panels`` /
    ``schemaVersion``) inside ``spec``; panels are never rewritten into the
    v2alpha ``elements`` model (see ADR-0025).
    """
    if _is_v2_dashboard(data):
        spec = data["spec"]
        uid = str(data.get("metadata", {}).get("name") or spec.get("uid") or "").strip()
    else:
        spec = data
        uid = str(data.get("uid") or "").strip()
    if not uid:
        raise SystemExit("Dashboard is missing a uid (classic top-level 'uid' or metadata.name).")
    return spec, uid


def _prepare_payload(data: dict[str, Any], message: str, folder_uid: str | None) -> dict[str, Any]:
    """Wrap the dashboard into a ``dashboard.grafana.app/v1`` App Platform resource.

    The repo dashboard is stored in the classic Grafana model (top-level
    ``panels`` / ``schemaVersion``). The v1 App Platform API carries that classic
    model unchanged inside ``spec`` (see ADR-0025); only the API surface and the
    resource envelope change. Server-managed metadata is intentionally omitted.
    """
    spec, uid = _extract_spec_and_uid(data)
    annotations: dict[str, str] = {"grafana.app/message": message}
    folder = folder_uid.strip() if folder_uid else ""
    if folder:
        annotations["grafana.app/folder"] = folder
    return {
        "apiVersion": "dashboard.grafana.app/v1",
        "kind": "Dashboard",
        "metadata": {"name": uid, "annotations": annotations},
        "spec": spec,
    }


def _prepare_legacy_payload(spec: dict[str, Any], message: str) -> dict[str, Any]:
    """Return a payload for the legacy ``POST /api/dashboards/db`` fallback.

    Used only when a stack does not expose the App Platform API. The classic
    dashboard model lives directly under ``dashboard``.
    """
    return {
        "dashboard": spec,
        "overwrite": True,
        "message": message,
    }


def _apis_collection(host: str, namespace: str) -> str:
    return f"https://{host}/apis/dashboard.grafana.app/v1/namespaces/{namespace}/dashboards"


def _request_json(
    url: str,
    token: str,
    *,
    method: str,
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Issue a JSON request and return ``(status_code, parsed_body)``.

    HTTP error status codes are returned (not raised) so callers can branch on
    404/409; transport errors still raise ``SystemExit``.
    """
    data = None
    if payload is not None:
        data = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {"message": raw}
        return exc.code, body
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach Grafana API: {exc}") from exc


def _get_resource_version(host: str, token: str, namespace: str, uid: str) -> str | None:
    """Return ``metadata.resourceVersion`` for an existing dashboard, or None (404)."""
    status, body = _request_json(f"{_apis_collection(host, namespace)}/{uid}", token, method="GET")
    if status == 404:
        return None
    if status >= 400:
        raise SystemExit(f"Grafana API error {status} on GET dashboard: {body.get('message', body)}")
    rv = body.get("metadata", {}).get("resourceVersion")
    return str(rv) if rv is not None else None


def _post(
    host: str,
    token: str,
    payload: dict[str, Any],
    *,
    namespace: str,
    uid: str,
    message: str,
) -> tuple[dict[str, Any], str]:
    """Upsert via the App Platform API; fall back to legacy ``/api/dashboards/db``.

    Optimistic concurrency: an existing ``resourceVersion`` is read first and
    echoed on PUT, so concurrent UI edits surface as 409 instead of being
    silently overwritten.
    """
    resource_version = _get_resource_version(host, token, namespace, uid)
    if resource_version is None:
        url, method = _apis_collection(host, namespace), "POST"
    else:
        url, method = f"{_apis_collection(host, namespace)}/{uid}", "PUT"
        payload = {**payload, "metadata": {**payload["metadata"], "resourceVersion": resource_version}}

    status, body = _request_json(url, token, method=method, payload=payload)
    if status == 404:
        # Stack does not expose the App Platform API: fall back to legacy upsert.
        legacy = _prepare_legacy_payload(payload["spec"], message)
        status, body = _request_json(f"https://{host}/api/dashboards/db", token, method="POST", payload=legacy)
        if status >= 400:
            raise SystemExit(f"Grafana API error {status} (legacy fallback): {body.get('message', body)}")
        return body, "/api/dashboards/db"
    if status == 409:
        raise SystemExit(
            "Grafana API 409 conflict: the dashboard changed in the UI since the last sync. "
            "Re-run to pick up the new resourceVersion (optimistic concurrency)."
        )
    if status >= 400:
        raise SystemExit(f"Grafana API error {status} on {method}: {body.get('message', body)}")
    return body, f"{method} {url}"


def main(argv: list[str] | None = None) -> int:
    args = _resolve_args(argv)
    if args.dry_run_full and not args.dry_run:
        args.dry_run = True

    data = _load_dashboard(args.dashboard_path)
    payload = _prepare_payload(data, args.message, args.folder)
    uid = payload["metadata"]["name"]
    collection = _apis_collection(args.host, args.namespace)

    if args.dry_run:
        summary = {
            "dry_run": True,
            "api_surface": "dashboard.grafana.app/v1",
            "namespace": args.namespace,
            "uid": uid,
            "folder": args.folder or "n/a",
            "endpoint_create": collection,
            "endpoint_update": f"{collection}/{uid}",
            "endpoint_legacy_fallback": f"https://{args.host}/api/dashboards/db",
            "apiVersion": payload["apiVersion"],
            "kind": payload["kind"],
            "spec_panels": len(payload["spec"].get("panels", [])),
            "schema_version": payload["spec"].get("schemaVersion", "n/a"),
            "message": args.message,
        }
        print("Dry-run: no network request sent.")
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        if args.dry_run_full:
            print("\nPayload:")
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    token = _get_token(
        args.token,
        args.keychain_service,
        args.token_env,
        no_keychain=args.no_keychain,
    )

    result, endpoint_used = _post(
        args.host,
        token,
        payload,
        namespace=args.namespace,
        uid=uid,
        message=args.message,
    )
    metadata = result.get("metadata", {})
    print(
        f"Published {args.dashboard_path} to {args.host}\n"
        f"  endpoint: {endpoint_used}\n"
        f"  uid:      {metadata.get('name', uid)}\n"
        f"  version:  {metadata.get('resourceVersion', 'n/a')}\n"
        f"  created:  {metadata.get('creationTimestamp', 'n/a')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

