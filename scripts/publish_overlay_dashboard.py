#!/usr/bin/env python3
"""Publish the live-overlay Grafana dashboard from repo to Grafana Cloud.

The default repo dashboard asset is maintained as legacy Grafana dashboard JSON.
This script accepts both legacy JSON and Grafana API v2 Dashboard objects,
normalizes to the v2 shape, and pushes via the Kubernetes-style dashboards API:

    POST /api/v1/dashboards

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


def _is_v2_dashboard(data: dict[str, Any]) -> bool:
    return data.get("kind") == "Dashboard" and isinstance(data.get("spec"), dict)


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
        help="Implies --dry-run and also prints the full JSON payload",
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

    # Native Grafana API v2 Dashboard object.
    if _is_v2_dashboard(data):
        return data
    if data.get("kind") == "Dashboard":
        raise SystemExit(
            "Grafana API v2 dashboard object requires a top-level object "
            "shape: kind='Dashboard' and spec=<object>."
        )

    # Legacy Grafana dashboard JSON (title/panels/schemaVersion at top-level).
    if "panels" in data or "schemaVersion" in data:
        dashboard_name_raw = data.get("uid")
        if dashboard_name_raw is None:
            dashboard_name_raw = data.get("title")
        if dashboard_name_raw is None:
            dashboard_name_raw = dashboard_path.stem
        dashboard_name = str(dashboard_name_raw)
        return {
            "apiVersion": "dashboard.grafana.app/v2",
            "kind": "Dashboard",
            "metadata": {"name": dashboard_name},
            "spec": data,
        }

    raise SystemExit(
        "Dashboard JSON must be either a Grafana API v2 Dashboard object "
        "(kind/spec) or legacy Grafana dashboard JSON (panels/schemaVersion)."
    )


def _get_token(
    token: str | None,
    keychain_service: str,
    token_env: str,
    *,
    no_keychain: bool = False,
) -> str:
    if token and token.strip():
        return token.strip()

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
            [security_bin, "find-generic-password", "-s", keychain_service, "-w"],
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


def _prepare_payload(data: dict[str, Any], message: str) -> dict[str, Any]:
    """Return the payload expected by the /api/v1/dashboards endpoint.

    The input is normalized to Kubernetes-style Dashboard format (native v2 or
    legacy JSON wrapped by `_load_dashboard`). We then strip server-managed
    metadata that must not be sent on upsert and add the standard change
    message annotation.
    """
    # Send a clean Dashboard v2 object built from normalized input.
    payload: dict[str, Any] = {
        "apiVersion": data.get("apiVersion", "dashboard.grafana.app/v2"),
        "kind": "Dashboard",
        "metadata": {},
        "spec": data["spec"],
    }

    # Preserve only client-relevant metadata. Server-managed fields like
    # resourceVersion, generation, creationTimestamp and uid are stripped.
    meta = data.get("metadata")
    if not isinstance(meta, dict):
        meta = {}

    name = meta.get("name")
    if name is not None:
        payload["metadata"]["name"] = name

    labels = meta.get("labels")
    if isinstance(labels, dict):
        payload["metadata"]["labels"] = labels

    annotations = meta.get("annotations")
    if isinstance(annotations, dict):
        payload["metadata"]["annotations"] = annotations

    # Ensure the change message is recorded as an annotation.
    annotations = payload["metadata"].get("annotations")
    if not isinstance(annotations, dict):
        annotations = {}
        payload["metadata"]["annotations"] = annotations
    annotations["grafana.app/message"] = message

    return payload


def _prepare_legacy_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a payload for legacy POST /api/dashboards/db upsert.

    Grafana Cloud stacks that do not expose /api/v1/dashboards can still accept
    the v2 Dashboard object inside the legacy wrapper.
    """
    message = payload.get("metadata", {}).get("annotations", {}).get("grafana.app/message", "sync from repo")
    return {
        "dashboard": payload,
        "overwrite": True,
        "message": message,
    }


def _post(host: str, token: str, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    attempts: list[tuple[str, dict[str, Any]]] = [
        ("/api/v1/dashboards", payload),
        ("/api/dashboards/db", _prepare_legacy_payload(payload)),
    ]

    for idx, (endpoint, endpoint_payload) in enumerate(attempts):
        url = f"https://{host}{endpoint}"
        body = json.dumps(endpoint_payload, indent=2, ensure_ascii=False).encode("utf-8")
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
                return json.loads(resp.read().decode("utf-8")), endpoint
        except urllib.error.HTTPError as exc:
            # If v1 is unavailable on this stack, try legacy endpoint.
            if idx == 0 and exc.code == 404:
                continue
            detail = exc.read().decode("utf-8", errors="replace")
            raise SystemExit(f"Grafana API error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise SystemExit(f"Could not reach Grafana API: {exc}") from exc

    raise SystemExit("Grafana API error: no endpoint attempt succeeded")


def main(argv: list[str] | None = None) -> int:
    args = _resolve_args(argv)
    if args.dry_run_full and not args.dry_run:
        # `--dry-run-full` is a strict superset of `--dry-run` and must never publish.
        args.dry_run = True
    data = _load_dashboard(args.dashboard_path)
    payload = _prepare_payload(data, args.message)

    if args.dry_run:
        summary = {
            "dry_run": True,
            "endpoint_primary": f"https://{args.host}/api/v1/dashboards",
            "endpoint_fallback": f"https://{args.host}/api/dashboards/db",
            "apiVersion": payload.get("apiVersion", "n/a"),
            "kind": payload.get("kind", "n/a"),
            "dashboard_name": payload.get("metadata", {}).get("name", "n/a"),
            "spec_elements": len(payload.get("spec", {}).get("elements", {})),
            "message": payload.get("metadata", {}).get("annotations", {}).get("grafana.app/message", "n/a"),
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

    result, endpoint_used = _post(args.host, token, payload)
    metadata = result.get("metadata", {})
    print(
        f"Published {args.dashboard_path} to {args.host}\n"
        f"  endpoint: {endpoint_used}\n"
        f"  uid:      {metadata.get('uid', 'n/a')}\n"
        f"  name:     {metadata.get('name', 'n/a')}\n"
        f"  version:  {metadata.get('resourceVersion', 'n/a')}\n"
        f"  response: {result.get('status', 'ok')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

