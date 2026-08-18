#!/usr/bin/env python3
"""Fail-closed health and expiry probe for the PRE-A0 MLflow candidate."""

from __future__ import annotations

import argparse
import base64
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from scripts.smc_atomic_write import atomic_write_json

DEFAULT_MODEL_NAME = "skipp-pre-a0"
DEFAULT_ALIAS = "candidate"
DEFAULT_ARTIFACT_ID = "de97b74e6c6f645a513ece01"
DEFAULT_RUNTIME_CONTRACT = "local-json-v1"
DEFAULT_DECLARED_REQUIREMENTS = (
    Path(__file__).resolve().parents[1] / "services" / "mlflow_tracking" / "requirements.txt"
)


def _tracking_uri(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/")
    ):
        raise ValueError("tracking URI must be an origin-only credential-free HTTPS URL")
    return value.rstrip("/")


def _request(url: str, username: str | None = None, password: str | None = None) -> Request:
    headers = {"Accept": "application/json"}
    if username is not None and password is not None:
        token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    return Request(url, headers=headers)


def _status(request: Request) -> int:
    try:
        with urlopen(request, timeout=15) as response:
            return int(response.status)
    except HTTPError as exc:
        return int(exc.code)


def _body(request: Request) -> bytes:
    with urlopen(request, timeout=15) as response:
        if int(response.status) != 200:
            raise RuntimeError(f"MLflow API returned HTTP {response.status}")
        return response.read()


def _json(request: Request) -> dict[str, object]:
    payload = json.loads(_body(request))
    if not isinstance(payload, dict):
        raise RuntimeError("MLflow API response must be an object")
    return payload


_VERSION_SHAPE = re.compile(r"^\d+\.\d+(\.\d+)?([a-z0-9.]*)$")


def _deployed_mlflow_version(origin: str, username: str, password: str) -> str | None:
    """The running server's version via GET /version, or None if unreadable.

    Format-tolerant on purpose (2026-08-18, Doppelgaenger-Sweep): the endpoint
    serves the bare version string; should a future MLflow wrap it in JSON,
    both shapes parse. Anything that does not look like a version yields None
    so a vendor surprise becomes a visible warning, never a false mismatch.
    """
    try:
        raw = _body(_request(f"{origin}/version", username, password)).decode().strip()
    except (HTTPError, OSError, RuntimeError, UnicodeDecodeError):
        return None
    if raw.startswith('"'):
        try:
            raw = str(json.loads(raw))
        except ValueError:
            return None
    return raw if _VERSION_SHAPE.match(raw) else None


def declared_mlflow_pin(requirements: Path) -> str:
    """The mlflow version the repo DECLARES for the tracking service."""
    for line in requirements.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^mlflow\[auth\]==([A-Za-z0-9.]+)\s*$", line.split("#")[0].strip())
        if match:
            return match.group(1)
    raise RuntimeError(f"no mlflow[auth]== pin found in {requirements}")


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def check_health(
    *,
    tracking_uri: str,
    username: str,
    password: str,
    model_name: str = DEFAULT_MODEL_NAME,
    alias: str = DEFAULT_ALIAS,
    expected_artifact_id: str = DEFAULT_ARTIFACT_ID,
    warn_before_days: float = 14.0,
    now: datetime | None = None,
    declared_mlflow_version: str | None = None,
) -> tuple[int, dict[str, object]]:
    origin = _tracking_uri(tracking_uri)
    if not username or not password:
        raise ValueError("monitor credentials are required")
    now_utc = (now or datetime.now(UTC)).astimezone(UTC)
    alias_url = f"{origin}/api/2.0/mlflow/registered-models/alias?{urlencode({'name': model_name, 'alias': alias})}"
    health_status = _status(_request(f"{origin}/health"))
    unauthenticated_status = _status(_request(alias_url))
    critical: list[str] = []
    warnings: list[str] = []
    if health_status != 200:
        critical.append(f"health_http_{health_status}")
    if unauthenticated_status != 401:
        critical.append(f"authentication_boundary_http_{unauthenticated_status}")

    # Deployed==declared tripwire (2026-08-18, Doppelgaenger-Sweep): the
    # tracking service only redeploys manually, so Dependabot bumps to
    # services/mlflow_tracking/requirements.txt change a replica nothing
    # executes. Measured 2026-08-18: the container ran mlflow 3.14.0 while the
    # repo declared 3.15.1 — three merged bumps, zero deploys, no alarm. This
    # hourly probe makes that drift page instead of rot.
    deployed_version: str | None = None
    if declared_mlflow_version is not None:
        deployed_version = _deployed_mlflow_version(origin, username, password)
        if deployed_version is None:
            warnings.append("deployed_version_unavailable")
        elif deployed_version != declared_mlflow_version:
            critical.append("deployed_version_mismatch")

    alias_payload = _json(_request(alias_url, username, password))
    version = alias_payload.get("model_version")
    if not isinstance(version, dict):
        raise RuntimeError("MLflow alias response is missing model_version")
    tags = {
        str(item.get("key")): str(item.get("value"))
        for item in version.get("tags", [])
        if isinstance(item, dict)
    }
    run_id = str(version.get("run_id", ""))
    run_url = f"{origin}/api/2.0/mlflow/runs/get?{urlencode({'run_id': run_id})}"
    run_payload = _json(_request(run_url, username, password))
    run = run_payload.get("run")
    if not isinstance(run, dict) or not isinstance(run.get("info"), dict):
        raise RuntimeError("MLflow run response is incomplete")
    run_status = str(run["info"].get("status", ""))

    expected_tags = {
        "pre_a0.artifact_id": expected_artifact_id,
        "pre_a0.gate.offline_evaluated": "true",
        "pre_a0.runtime_contract": DEFAULT_RUNTIME_CONTRACT,
        "pre_a0.promotion_status": alias,
    }
    for key, expected in expected_tags.items():
        if tags.get(key) != expected:
            critical.append(f"tag_mismatch:{key}")
    if str(version.get("status")) != "READY":
        critical.append("model_version_not_ready")
    if run_status != "FINISHED":
        critical.append("run_not_finished")
    review_after_raw = tags.get("pre_a0.review_after", "")
    try:
        review_after = _parse_timestamp(review_after_raw)
        remaining_days = (review_after - now_utc).total_seconds() / 86400.0
        if remaining_days <= 0:
            critical.append("model_expired")
        elif remaining_days <= warn_before_days:
            warnings.append("model_expiry_window")
    except (TypeError, ValueError):
        remaining_days = None
        critical.append("review_after_invalid")

    report: dict[str, object] = {
        "checked_at": now_utc.isoformat().replace("+00:00", "Z"),
        "tracking_host": urlsplit(origin).hostname,
        "health_http_status": health_status,
        "unauthenticated_alias_http_status": unauthenticated_status,
        "model_name": model_name,
        "alias": alias,
        "model_version": str(version.get("version", "")),
        "model_status": str(version.get("status", "")),
        "run_id": run_id,
        "run_status": run_status,
        "artifact_id": tags.get("pre_a0.artifact_id"),
        "bundle_id": tags.get("pre_a0.bundle_id"),
        "offline_gate": tags.get("pre_a0.gate.offline_evaluated"),
        "shadow_gate": tags.get("pre_a0.gate.shadow_evaluated"),
        "review_after": review_after_raw,
        "remaining_days": remaining_days,
        "deployed_mlflow_version": deployed_version,
        "declared_mlflow_version": declared_mlflow_version,
        "critical": critical,
        "warnings": warnings,
        "overall": "critical" if critical else "warning" if warnings else "healthy",
    }
    return (1 if critical else 2 if warnings else 0), report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracking-uri", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--alias", default=DEFAULT_ALIAS)
    parser.add_argument("--expected-artifact-id", default=DEFAULT_ARTIFACT_ID)
    parser.add_argument("--warn-before-days", type=float, default=14.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--declared-requirements",
        type=Path,
        default=DEFAULT_DECLARED_REQUIREMENTS,
        help="requirements file carrying the mlflow[auth]== pin the deploy must match",
    )
    args = parser.parse_args()
    rc, report = check_health(
        tracking_uri=args.tracking_uri,
        username=args.username,
        password=args.password,
        model_name=args.model_name,
        alias=args.alias,
        expected_artifact_id=args.expected_artifact_id,
        warn_before_days=args.warn_before_days,
        declared_mlflow_version=declared_mlflow_pin(args.declared_requirements),
    )
    if args.output:
        atomic_write_json(report, args.output, sort_keys=True)
    print(json.dumps(report, sort_keys=True))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
