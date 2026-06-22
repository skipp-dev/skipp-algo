#!/usr/bin/env python3
"""Publish the live-overlay Grafana dashboard from repo to Grafana Cloud.

The dashboard is stored in Grafana API v2 format (apiVersion: dashboard.grafana.app/v2)
and is pushed via the Kubernetes-style dashboards API:

    POST /api/v1/dashboards

Authentication uses CLI/env first and falls back to the macOS keychain entry
``skipp.grafana.api`` by default.

Resolution order:
1) ``--token``
2) ``$<--token-env>`` (default: ``GRAFANA_API_TOKEN``)
3) ``$GRAFANA_API_TOKEN``
4) ``$GRAFANA_TOKEN``
5) Keychain (unless ``--no-keychain`` is set)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_DASHBOARD_PATH = Path("services/live_overlay_daemon/infra/grafana/dashboard.json")
DEFAULT_HOST = "bronzeporridge977.grafana.net"
DEFAULT_KEYCHAIN_SERVICE = "skipp.grafana.api"
DEFAULT_TOKEN_ENV = "GRAFANA_API_TOKEN"


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
        help="Disable keychain lookup (useful in CI/agent sandboxes)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print payload without sending",
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
    if data.get("kind") != "Dashboard":
        raise SystemExit("Dashboard JSON is not in Kubernetes-style Dashboard format")
    if "spec" not in data:
        raise SystemExit("Dashboard JSON missing 'spec' field")
    return data


def _get_token(
    token: str | None,
    keychain_service: str,
    token_env: str,
    *,
    no_keychain: bool = False,
) -> str:
    if token:
        return token

    env_candidates = [token_env, DEFAULT_TOKEN_ENV, "GRAFANA_TOKEN"]
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

    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", keychain_service, "-a", os.environ.get("USER", ""), "-w"],
            capture_output=True,
            text=True,
            check=True,
        )
        keychain_token = result.stdout.strip()
        if keychain_token:
            return keychain_token
        raise SystemExit(
            "Keychain lookup returned an empty token. "
            f"Set ${token_env}, ${DEFAULT_TOKEN_ENV}, or $GRAFANA_TOKEN, or pass --token."
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise SystemExit(
            "Could not obtain Grafana API token. "
            f"Set ${token_env}, ${DEFAULT_TOKEN_ENV}, or $GRAFANA_TOKEN, use --token, "
            "or add a keychain entry for "
            f"service '{keychain_service}'. ({exc})"
        ) from exc


def _prepare_payload(data: dict[str, Any], message: str) -> dict[str, Any]:
    """Return the payload expected by the /api/v1/dashboards endpoint.

    The repo file is already in the Kubernetes-style Dashboard format, but we
    strip server-managed metadata that must not be sent on upsert and add the
    standard change message annotation.
    """
    # The repo dashboard is maintained in Grafana API v2 shape and is sent as-is.
    payload: dict[str, Any] = {
        "apiVersion": data.get("apiVersion", "dashboard.grafana.app/v2"),
        "kind": "Dashboard",
        "metadata": {},
        "spec": data["spec"],
    }

    # Preserve only client-relevant metadata. Server-managed fields like
    # resourceVersion, generation, creationTimestamp and uid are stripped.
    meta = data.get("metadata", {})
    for key in ("name", "annotations", "labels"):
        if key in meta:
            payload["metadata"][key] = meta[key]

    # Ensure the change message is recorded as an annotation.
    annotations = payload["metadata"].setdefault("annotations", {})
    annotations["grafana.app/message"] = message

    return payload


def _post(host: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"https://{host}/api/v1/dashboards"
    body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Grafana API error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach Grafana API: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    args = _resolve_args(argv)
    data = _load_dashboard(args.dashboard_path)
    token = _get_token(
        args.token,
        args.keychain_service,
        args.token_env,
        no_keychain=args.no_keychain,
    )
    payload = _prepare_payload(data, args.message)

    if args.dry_run:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    result = _post(args.host, token, payload)
    metadata = result.get("metadata", {})
    print(
        f"Published {args.dashboard_path} to {args.host}\n"
        f"  uid:      {metadata.get('uid', 'n/a')}\n"
        f"  name:     {metadata.get('name', 'n/a')}\n"
        f"  version:  {metadata.get('resourceVersion', 'n/a')}\n"
        f"  response: {result.get('status', 'ok')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

