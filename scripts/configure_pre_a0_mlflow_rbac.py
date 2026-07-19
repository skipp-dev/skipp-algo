#!/usr/bin/env python3
"""Idempotently configure least-privilege MLflow roles for PRE-A0."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class RoleSpec:
    name: str
    username: str
    description: str
    permissions: tuple[tuple[str, str, str], ...]


def _tracking_uri(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.path.rstrip("/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("tracking URI must be an origin-only credential-free HTTPS URL")
    return value.rstrip("/")


def _specs(experiment_id: str, model_name: str) -> tuple[RoleSpec, ...]:
    if not experiment_id.strip() or not model_name.strip():
        raise ValueError("experiment ID and model name are required")
    return (
        RoleSpec(
            "pre-a0-pilot-writer",
            "skipp-pre-a0-pilot",
            "PRE-A0 training, validated import, and reviewed alias promotion",
            (
                ("workspace", "*", "USE"),
                ("experiment", experiment_id, "EDIT"),
                ("registered_model", model_name, "EDIT"),
            ),
        ),
        RoleSpec(
            "pre-a0-monitor-reader",
            "skipp-pre-a0-monitor",
            "Read-only PRE-A0 health, identity, and expiry monitoring",
            (
                ("workspace", "*", "USE"),
                ("experiment", experiment_id, "READ"),
                ("registered_model", model_name, "READ"),
            ),
        ),
    )


def _password(spec: RoleSpec) -> str:
    suffix = "WRITER" if spec.name.endswith("writer") else "MONITOR"
    value = os.environ.get(f"PRE_A0_MLFLOW_{suffix}_PASSWORD", "")
    if len(value) < 32:
        raise ValueError(f"PRE_A0_MLFLOW_{suffix}_PASSWORD must contain at least 32 characters")
    return value


def _missing_resource(exc: Exception) -> bool:
    return getattr(exc, "error_code", None) == "RESOURCE_DOES_NOT_EXIST"


def _ensure_user(client: Any, spec: RoleSpec, rest_exception: type[Exception]) -> tuple[Any, str]:
    try:
        user = client.get_user(spec.username)
        action = "existing"
    except rest_exception as exc:
        if not _missing_resource(exc):
            raise
        user = client.create_user(spec.username, _password(spec))
        action = "created"
    if user.is_admin:
        raise RuntimeError(f"least-privilege user must not be admin: {spec.username}")
    return user, action


def _ensure_role(client: Any, spec: RoleSpec, *, workspace: str) -> tuple[Any, str]:
    matching = [
        role
        for role in client.list_all_roles()
        if role.workspace == workspace and role.name == spec.name
    ]
    if len(matching) > 1:
        raise RuntimeError(f"duplicate MLflow role: {spec.name}")
    if matching:
        return matching[0], "existing"
    return client.create_role(workspace, spec.name, spec.description), "created"


def _ensure_permissions(client: Any, role: Any, spec: RoleSpec) -> list[str]:
    existing = {
        (permission.resource_type, permission.resource_pattern): permission
        for permission in client.list_role_permissions(role.id)
    }
    actions: list[str] = []
    expected_keys = {(resource_type, pattern) for resource_type, pattern, _value in spec.permissions}
    unexpected = sorted(set(existing) - expected_keys)
    if unexpected:
        raise RuntimeError(f"role {spec.name} has unexpected permissions: {unexpected}")
    for resource_type, pattern, permission in spec.permissions:
        current = existing.get((resource_type, pattern))
        if current is None:
            client.add_role_permission(role.id, resource_type, pattern, permission)
            actions.append(f"created:{resource_type}:{pattern}:{permission}")
        elif current.permission != permission:
            client.update_role_permission(current.id, permission)
            actions.append(f"updated:{resource_type}:{pattern}:{permission}")
        else:
            actions.append(f"existing:{resource_type}:{pattern}:{permission}")
    return actions


_SYNTHETIC_USER_ROLE = re.compile(r"^__user_[0-9]+__$")


def _is_synthetic_user_role(role: Any) -> bool:
    """Return whether MLflow uses this role for the user's direct grants."""
    return bool(_SYNTHETIC_USER_ROLE.fullmatch(str(getattr(role, "name", ""))))


def _ensure_assignment(client: Any, username: str, role: Any) -> str:
    roles = client.list_user_roles(username)
    unexpected = sorted(
        existing.name
        for existing in roles
        if existing.id != role.id and not _is_synthetic_user_role(existing)
    )
    if unexpected:
        raise RuntimeError(f"user {username} has unexpected roles: {unexpected}")
    if any(existing.id == role.id for existing in roles):
        return "existing"
    client.assign_role(username, role.id)
    return "created"


def apply_rbac(
    *,
    tracking_uri: str,
    experiment_id: str,
    model_name: str,
    workspace: str = "default",
) -> dict[str, Any]:
    client_module = importlib.import_module("mlflow.server.auth.client")
    exceptions = importlib.import_module("mlflow.exceptions")
    client = client_module.AuthServiceClient(_tracking_uri(tracking_uri))
    results = []
    for spec in _specs(experiment_id, model_name):
        _user, user_action = _ensure_user(client, spec, exceptions.RestException)
        role, role_action = _ensure_role(client, spec, workspace=workspace)
        permission_actions = _ensure_permissions(client, role, spec)
        assignment_action = _ensure_assignment(client, spec.username, role)
        results.append(
            {
                "username": spec.username,
                "role": spec.name,
                "user": user_action,
                "role_action": role_action,
                "permissions": permission_actions,
                "assignment": assignment_action,
            }
        )
    return {"tracking_host": urlsplit(tracking_uri).hostname, "workspace": workspace, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracking-uri", required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--model-name", default="skipp-pre-a0")
    parser.add_argument("--workspace", default="default")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    specs = _specs(args.experiment_id, args.model_name)
    if not args.apply:
        result = {
            "action": "dry_run",
            "tracking_host": urlsplit(_tracking_uri(args.tracking_uri)).hostname,
            "workspace": args.workspace,
            "roles": [
                {
                    "name": spec.name,
                    "username": spec.username,
                    "permissions": spec.permissions,
                }
                for spec in specs
            ],
        }
    else:
        result = apply_rbac(
            tracking_uri=args.tracking_uri,
            experiment_id=args.experiment_id,
            model_name=args.model_name,
            workspace=args.workspace,
        )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
